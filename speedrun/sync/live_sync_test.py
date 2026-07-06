"""Live two-way sync + conflict test (challenge 7b), end-to-end over HTTP.

This drives **two independent client collections** through the *same* Rust sync
engine that the desktop app and the AnkiDroid phone build share, talking to a
real self-hosted Anki sync server. It models the phone<->desktop merge
deterministically and re-runnably, and proves the two things challenge 7b asks
for:

  Part 1 -- review N cards on one device offline + N *different* cards on the
            other offline, reconnect, sync: all 2N reviews land in one place,
            none lost, none double-counted.
  Part 2 -- review the *same* card on both devices offline, then sync: the
            conflict rule ("newest modification wins per object; revlog is
            append-only") picks a clear, correct winner and keeps both review
            rows.

The harness starts its **own** server on a throwaway base dir + free port, so
the real `speedrun/syncbase` collection (behind the GUI/emulator proof in
`speedrun/sync-test.md`) is never touched.

Run (from repo root, with the project's built backend on the path):

    $env:PYTHONPATH = "$PWD\\out\\pylib"
    out\\pyenv\\Scripts\\python.exe -m speedrun.sync.live_sync_test

Writes `speedrun/sync/artifacts/report_sync_live.md` and `sync_live.json`.
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from anki.collection import Collection

USER = "hiya"
PASSWORD = "mcat123"
N_SEED = 25          # cards seeded in the shared baseline
N_EACH = 10          # cards each device reviews offline (disjoint sets)
CONFLICT_IDX = 20    # index (in sorted cids) of the shared conflict card

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"


# --------------------------------------------------------------------------- #
# server subprocess
# --------------------------------------------------------------------------- #
def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(port: int, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.2)
    raise TimeoutError(f"sync server did not open port {port} in {timeout}s")


def start_server(base: Path, port: int) -> subprocess.Popen:
    base.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["SYNC_USER1"] = f"{USER}:{PASSWORD}"
    env["SYNC_HOST"] = "127.0.0.1"
    env["SYNC_PORT"] = str(port)
    env["SYNC_BASE"] = str(base)
    env["RUST_LOG"] = "anki=warn"
    # Launch the server inline via the backend so we don't depend on the
    # `anki.syncserver` module being present in the built `out/pylib`.
    launch = "from anki._backend import RustBackend; RustBackend.syncserver()"
    proc = subprocess.Popen(
        [sys.executable, "-c", launch],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _wait_for_port(port)
    return proc


# --------------------------------------------------------------------------- #
# client helpers
# --------------------------------------------------------------------------- #
def open_col(path: Path) -> Collection:
    return Collection(str(path))


def seed(col: Collection, n: int) -> None:
    """Create `n` Basic notes and lift the daily new-card limit so we can
    review any of them on demand."""
    nt = col.models.by_name("Basic") or col.models.all()[0]
    did = col.decks.id("Default")
    for i in range(n):
        note = col.new_note(nt)
        note.fields[0] = f"Q{i:03d}"
        note.fields[1] = f"A{i:03d}"
        col.add_note(note, did)
    # allow reviewing all of them today
    conf = col.decks.config_dict_for_deck_id(did)
    conf["new"]["perDay"] = n + 50
    conf["rev"]["perDay"] = n + 50
    col.decks.update_config(conf)


def login(col: Collection, endpoint: str):
    return col.sync_login(USER, PASSWORD, endpoint)


def sync(col: Collection, path: Path, endpoint: str, prefer_upload: bool) -> Collection:
    """Perform a full sync handshake. Returns a (possibly reopened) Collection."""
    auth = login(col, endpoint)
    out = col.sync_collection(auth, False)
    req = out.required
    if req in (out.NO_CHANGES, out.NORMAL_SYNC):
        # normal sync already applied by sync_collection
        return col

    if req == out.FULL_DOWNLOAD:
        upload = False
    elif req == out.FULL_UPLOAD:
        upload = True
    else:  # FULL_SYNC -- ambiguous, caller decides
        upload = prefer_upload

    auth = login(col, endpoint)
    # Same dance the desktop app does: detach the Python db handle, let the
    # backend perform the full transfer (it closes + reopens the collection
    # internally), then reconnect our handle without re-opening the file.
    col.close_for_full_sync()
    col.full_upload_or_download(auth=auth, server_usn=None, upload=upload)
    col.reopen(after_full_sync=True)
    return col


def review_cids(col: Collection, cids: list[int], ease: int) -> list[dict[str, Any]]:
    """Answer the given cards with `ease`; return each resulting revlog/card row."""
    rows = []
    for cid in cids:
        card = col.get_card(cid)
        card.start_timer()
        col.sched.answerCard(card, ease)
        card.load()
        rows.append({"cid": cid, "ease": ease, "ivl": card.ivl, "type": int(card.type)})
    return rows


# --------------------------------------------------------------------------- #
# server-side verification (read the server's own collection)
# --------------------------------------------------------------------------- #
def server_db(base: Path) -> Path:
    return base / USER / "collection.anki2"


def read_server(base: Path) -> sqlite3.Connection:
    """Open a *copy* of the server collection (+wal) read-only so we never race
    the running server."""
    src = server_db(base)
    tmp = Path(tempfile.mkdtemp()) / "server_snapshot.anki2"
    import shutil

    shutil.copy2(src, tmp)
    for suf in ("-wal", "-shm"):
        s = Path(str(src) + suf)
        if s.exists():
            shutil.copy2(s, str(tmp) + suf)
    return sqlite3.connect(str(tmp))


def revlog_stats(con: sqlite3.Connection) -> tuple[int, int]:
    total, distinct = con.execute(
        "SELECT COUNT(*), COUNT(DISTINCT id) FROM revlog"
    ).fetchone()
    return int(total), int(distinct)


# --------------------------------------------------------------------------- #
# main scenario
# --------------------------------------------------------------------------- #
def run() -> dict[str, Any]:
    work = Path(tempfile.mkdtemp(prefix="mcat_sync_"))
    server_base = work / "serverbase"
    port = _free_port()
    endpoint = f"http://127.0.0.1:{port}/"
    result: dict[str, Any] = {"endpoint": endpoint}

    proc = start_server(server_base, port)
    try:
        # ---- baseline: A seeds + uploads, B downloads -> identical baseline ---
        a_path = work / "desktop.anki2"
        b_path = work / "phone.anki2"
        a = open_col(a_path)
        seed(a, N_SEED)
        a = sync(a, a_path, endpoint, prefer_upload=True)     # full upload

        b = open_col(b_path)
        b = sync(b, b_path, endpoint, prefer_upload=False)    # full download

        cids_a = sorted(a.find_cards(""))
        cids_b = sorted(b.find_cards(""))
        result["baseline_cards_desktop"] = len(cids_a)
        result["baseline_cards_phone"] = len(cids_b)
        result["baseline_identical"] = cids_a == cids_b
        assert cids_a == cids_b, "baseline collections differ after full sync"
        cids = cids_a

        # ---- Part 1: offline divergent reviews, then sync -------------------
        desk_set = cids[0:N_EACH]                 # desktop reviews these
        phone_set = cids[N_EACH:2 * N_EACH]       # phone reviews these (disjoint)
        review_cids(a, desk_set, ease=3)          # "desktop", Good, offline
        review_cids(b, phone_set, ease=3)         # "phone", Good, offline

        # reconnect: push desktop, then phone (pulls desktop + pushes phone),
        # then desktop again (pulls phone) -> all converge
        a = sync(a, a_path, endpoint, prefer_upload=False)
        b = sync(b, b_path, endpoint, prefer_upload=False)
        a = sync(a, a_path, endpoint, prefer_upload=False)

        con = read_server(server_base)
        total, distinct = revlog_stats(con)
        con.close()
        result["part1"] = {
            "reviewed_desktop": N_EACH,
            "reviewed_phone": N_EACH,
            "server_revlog_rows": total,
            "server_revlog_distinct_ids": distinct,
            "duplicate_ids": total - distinct,
            "expected": 2 * N_EACH,
            "pass": total == 2 * N_EACH and distinct == 2 * N_EACH,
        }

        # ---- Part 2: same card both offline, deterministic winner -----------
        conflict_cid = cids[CONFLICT_IDX]
        # desktop reviews FIRST (Again), phone reviews LATER (Easy) -> phone wins
        desk_state = review_cids(a, [conflict_cid], ease=1)[0]   # Again
        time.sleep(1.5)                                          # ensure later mtime
        phone_state = review_cids(b, [conflict_cid], ease=4)[0]  # Easy (later)

        a = sync(a, a_path, endpoint, prefer_upload=False)       # push desktop
        b = sync(b, b_path, endpoint, prefer_upload=False)       # push phone (wins)
        a = sync(a, a_path, endpoint, prefer_upload=False)       # pull winner

        con = read_server(server_base)
        srv_ivl, srv_type, srv_mod = con.execute(
            "SELECT ivl, type, mod FROM cards WHERE id=?", (conflict_cid,)
        ).fetchone()
        conflict_revs = con.execute(
            "SELECT COUNT(*) FROM revlog WHERE cid=?", (conflict_cid,)
        ).fetchone()[0]
        con.close()

        winner_is_phone = srv_ivl == phone_state["ivl"] and srv_ivl != desk_state["ivl"]
        result["part2"] = {
            "conflict_cid": conflict_cid,
            "desktop_review": {"ease": "Again(1)", "ivl": desk_state["ivl"]},
            "phone_review_later": {"ease": "Easy(4)", "ivl": phone_state["ivl"]},
            "server_card_ivl": srv_ivl,
            "server_card_type": srv_type,
            "server_revlog_rows_for_card": conflict_revs,
            "winner": "phone (later mtime)" if winner_is_phone else "UNEXPECTED",
            "both_reviews_retained": conflict_revs == 2,
            "pass": winner_is_phone and conflict_revs == 2,
        }

        a.close()
        b.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    result["overall_pass"] = bool(
        result.get("baseline_identical")
        and result["part1"]["pass"]
        and result["part2"]["pass"]
    )
    return result


def write_reports(result: dict[str, Any]) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "sync_live.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )

    p1 = result["part1"]
    p2 = result["part2"]
    md = f"""# Live two-way sync + conflict test (challenge 7b)

Generated by `python -m speedrun.sync.live_sync_test`. Two independent client
collections ("desktop" and "phone") sync through the **same Rust engine** the
desktop app and the AnkiDroid build share, against a real self-hosted Anki sync
server started by the harness on a throwaway base + free port. Re-runnable; no
GUI, no network, nothing to click.

**Overall: {"PASS" if result["overall_pass"] else "FAIL"}**

## Baseline
- Endpoint: `{result["endpoint"]}`
- Desktop full-uploads a {result["baseline_cards_desktop"]}-card deck; phone
  full-downloads it. Baselines identical: **{result["baseline_identical"]}**.

## Part 1 -- {p1["reviewed_desktop"]} + {p1["reviewed_phone"]} offline reviews, none lost, none doubled
Desktop reviews {p1["reviewed_desktop"]} cards offline; phone reviews
{p1["reviewed_phone"]} **different** cards offline; then both sync.

| Check | Value |
| --- | --- |
| Server revlog rows | **{p1["server_revlog_rows"]}** (expected {p1["expected"]}) |
| Distinct revlog ids | **{p1["server_revlog_distinct_ids"]}** |
| Duplicate ids | **{p1["duplicate_ids"]}** |
| Verdict | **{"PASS" if p1["pass"] else "FAIL"}** |

Every review is one `revlog` row keyed by its epoch-ms id; merging re-inserts by
id (idempotent), so {p1["reviewed_desktop"]}+{p1["reviewed_phone"]} disjoint
reviews = {p1["expected"]} distinct rows and re-syncing can never duplicate one.

## Part 2 -- same card both offline, deterministic winner
The conflict rule: **newest modification wins per object; the revlog is
append-only.** Desktop reviewed card `{p2["conflict_cid"]}` first (`Again`), the
phone reviewed the *same* card ~1.5 s later (`Easy`), then both synced.

| | Review | Resulting interval |
| --- | --- | --- |
| Desktop (earlier) | {p2["desktop_review"]["ease"]} | {p2["desktop_review"]["ivl"]} |
| Phone (later) | {p2["phone_review_later"]["ease"]} | {p2["phone_review_later"]["ivl"]} |

- Final card state on the **server**: `ivl={p2["server_card_ivl"]}`,
  `type={p2["server_card_type"]}` -> matches the **phone's later `Easy`** ->
  winner: **{p2["winner"]}**.
- Revlog rows for the card: **{p2["server_revlog_rows_for_card"]}** -> **both**
  reviews retained (audit trail complete; the card advances once, as the winner
  scheduled it -- reps are not double-counted).
- Verdict: **{"PASS" if p2["pass"] else "FAIL"}**

## Why this is the phone<->desktop case
The desktop app and the AnkiDroid build both embed this exact Rust sync client
and merge logic (`rslib/src/sync/collection/`). Driving two client collections
against the real server exercises the same code path a phone and a desktop take;
the merge outcome is identical regardless of which client is "the phone". The
GUI/emulator walkthrough of the same scenario is in
[`../sync-test.md`](../sync-test.md).
"""
    (ARTIFACTS / "report_sync_live.md").write_text(md, encoding="utf-8")


def main() -> int:
    result = run()
    write_reports(result)
    print(json.dumps(result, indent=2))
    print("\nArtifacts:", ARTIFACTS)
    return 0 if result["overall_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
