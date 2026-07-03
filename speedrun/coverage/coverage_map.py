"""Coverage map -- challenge 7c.

Lists every content category on the MCAT outline, checks which ones the study
deck actually covers, and reports the percent covered per section and overall.
If overall coverage is below the declared line it ABSTAINS -- the same
give-up rule the readiness engine uses (>= 50% topic coverage). A deck that
skips a whole high-weight section must not be able to claim "ready".

Design constraints:
* standard library only (sqlite3/json/argparse) -- no third-party deps, no build;
* the Anki collection is opened READ-ONLY (``?mode=ro``), so a running Anki is
  never disturbed; and it is never required -- with no collection we fall back
  to the AI harness gold-set topics as a documented proxy so the report still
  runs today.

Usage (from repo root):
    python speedrun/coverage/coverage_map.py [--collection PATH] [--threshold 0.5]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

HERE = Path(__file__).resolve().parent
OUTLINE_PATH = HERE / "mcat_outline.json"
REPORT_PATH = HERE / "coverage_report.md"
JSON_PATH = HERE / "coverage.json"
GOLD_FALLBACK = HERE.parent / "ai" / "gold" / "gold_set.json"

# Declared line (matches the readiness engine's MIN_TOPIC_COVERAGE).
DEFAULT_THRESHOLD = 0.50


# --------------------------------------------------------------------------
# Collection discovery + read-only topic extraction
# --------------------------------------------------------------------------
def collection_candidates() -> List[Path]:
    out: List[Path] = []
    appdata = os.environ.get("APPDATA")
    roots: List[Path] = []
    if appdata:
        roots.append(Path(appdata) / "Anki2")
    home = Path.home()
    roots.append(home / ".local" / "share" / "Anki2")
    roots.append(home / "Library" / "Application Support" / "Anki2")
    for root in roots:
        try:
            if not root.exists():
                continue
            for profile in sorted(root.iterdir()):
                col = profile / "collection.anki2"
                if col.is_file():
                    out.append(col)
        except OSError:
            continue
    return out


def _open_ro(col_path: Path) -> sqlite3.Connection:
    uri = "file:{}?mode=ro&immutable=1".format(col_path.as_posix())
    return sqlite3.connect(uri, uri=True)


def topics_from_collection(col_path: Path) -> Tuple[List[str], Dict[str, int]]:
    """Return (topic_strings, meta). Topic strings come from the names of decks
    that actually have cards, plus note tags -- i.e. what the deck really
    covers, not empty placeholders."""
    conn = _open_ro(col_path)
    strings: Set[str] = set()
    meta = {"decks_with_cards": 0, "notes": 0}
    try:
        cur = conn.cursor()

        # Decks that have >= 1 card.
        try:
            cur.execute("SELECT DISTINCT did FROM cards")
            dids = {int(r[0]) for r in cur.fetchall()}
        except sqlite3.Error:
            dids = set()

        # Deck id -> name. Modern schema has a `decks` table; older stores JSON
        # in col.decks.
        did_to_name: Dict[int, str] = {}
        try:
            cur.execute("SELECT id, name FROM decks")
            did_to_name = {int(i): str(n) for i, n in cur.fetchall()}
        except sqlite3.Error:
            try:
                cur.execute("SELECT decks FROM col")
                row = cur.fetchone()
                if row and row[0]:
                    decks_json = json.loads(row[0])
                    for k, v in decks_json.items():
                        try:
                            did_to_name[int(k)] = str(v.get("name", ""))
                        except (ValueError, AttributeError):
                            continue
            except (sqlite3.Error, json.JSONDecodeError):
                pass

        for did in dids:
            name = did_to_name.get(did, "")
            if not name:
                continue
            strings.add(name)
            for part in name.split("::"):
                if part.strip():
                    strings.add(part.strip())
        meta["decks_with_cards"] = len(dids)

        # Tags on notes that have cards.
        try:
            cur.execute(
                "SELECT DISTINCT n.tags FROM notes n JOIN cards c ON c.nid = n.id"
            )
            for (tags,) in cur.fetchall():
                for tag in str(tags or "").split():
                    strings.add(tag)
                    for part in tag.split("::"):
                        if part.strip():
                            strings.add(part.strip())
        except sqlite3.Error:
            pass

        try:
            cur.execute("SELECT COUNT(*) FROM notes")
            meta["notes"] = int(cur.fetchone()[0])
        except sqlite3.Error:
            pass
    finally:
        conn.close()
    return sorted(strings), meta


def topics_from_gold() -> Tuple[List[str], Dict[str, int]]:
    """Fallback: derive deck-topic strings from the AI harness gold set so the
    coverage map still produces a real report with no collection present."""
    strings: Set[str] = set()
    try:
        data = json.loads(GOLD_FALLBACK.read_text(encoding="utf-8"))
        for item in data.get("items", []):
            topic = str(item.get("topic", ""))
            if not topic:
                continue
            strings.add(topic)
            for part in topic.split("::"):
                if part.strip():
                    strings.add(part.strip())
    except (OSError, json.JSONDecodeError):
        pass
    return sorted(strings), {"decks_with_cards": 0, "notes": 0}


# --------------------------------------------------------------------------
# Matching + coverage
# --------------------------------------------------------------------------
def build_blob(topic_strings: List[str]) -> str:
    return " || ".join(s.lower() for s in topic_strings)


def category_covered(keywords: List[str], blob: str) -> Optional[str]:
    """Word-boundary match so short keywords don't match inside longer words
    (e.g. `ph` must not match `phospholipid`). Short keywords (<4 alnum chars)
    require a whole-word match; longer ones allow a suffix (stem prefix), so
    `atom` still matches `atoms`/`atomic`."""
    for kw in keywords:
        k = kw.lower()
        core = re.sub(r"[^a-z0-9]", "", k)
        if len(core) < 4:
            pat = r"\b" + re.escape(k) + r"\b"
        else:
            pat = r"\b" + re.escape(k)
        if re.search(pat, blob):
            return kw
    return None


def compute_coverage(outline: dict, topic_strings: List[str]) -> dict:
    blob = build_blob(topic_strings)
    sections_out: List[dict] = []
    total = 0
    covered = 0

    for section in outline["sections"]:
        if section.get("skills_based"):
            cars_hit = any(
                k in blob for k in ("cars", "reading", "passage", "critical analysis")
            )
            sections_out.append({
                "id": section["id"], "name": section["name"],
                "skills_based": True,
                "passage_practice_detected": cars_hit,
                "categories": [],
            })
            continue

        cats_out: List[dict] = []
        sec_total = 0
        sec_covered = 0
        for cat in section["categories"]:
            hit = category_covered(cat.get("keywords", []), blob)
            is_cov = hit is not None
            sec_total += 1
            total += 1
            if is_cov:
                sec_covered += 1
                covered += 1
            cats_out.append({
                "id": cat["id"], "title": cat["title"],
                "covered": is_cov, "matched_keyword": hit,
            })
        sections_out.append({
            "id": section["id"], "name": section["name"], "skills_based": False,
            "covered": sec_covered, "total": sec_total,
            "fraction": (sec_covered / sec_total) if sec_total else 0.0,
            "categories": cats_out,
        })

    overall = (covered / total) if total else 0.0
    return {
        "overall_covered": covered,
        "overall_total": total,
        "overall_fraction": overall,
        "sections": sections_out,
    }


def missing_categories(cov: dict) -> List[str]:
    out: List[str] = []
    for s in cov["sections"]:
        if s.get("skills_based"):
            continue
        for c in s["categories"]:
            if not c["covered"]:
                out.append("{} {}".format(c["id"], c["title"]))
    return out


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------
def write_reports(cov: dict, threshold: float, source_desc: str, meta: dict) -> None:
    show = cov["overall_fraction"] >= threshold
    JSON_PATH.write_text(json.dumps({
        "declared_threshold": threshold,
        "topic_source": source_desc,
        "collection_meta": meta,
        "show_score": show,
        **cov,
    }, indent=2), encoding="utf-8")

    lines: List[str] = []
    lines.append("# MCAT coverage map (challenge 7c)\n")
    lines.append("Topic source: **{}**.\n".format(source_desc))
    lines.append("Declared abstain line: **{:.0%}** overall content coverage "
                 "(matches the readiness engine's give-up rule).\n".format(threshold))
    lines.append("## Overall\n")
    lines.append("- **{}/{} content categories covered = {:.1%}**".format(
        cov["overall_covered"], cov["overall_total"], cov["overall_fraction"]))
    lines.append("- Dashboard decision: **{}**\n".format(
        "SHOW score" if show else "ABSTAIN (below the coverage line)"))

    lines.append("## By section\n")
    lines.append("| Section | Covered | Total | % |")
    lines.append("| --- | ---: | ---: | ---: |")
    for s in cov["sections"]:
        if s.get("skills_based"):
            lines.append("| {} (skills-based) | {} | -- | -- |".format(
                s["name"],
                "passage practice detected" if s.get("passage_practice_detected")
                else "no passage practice detected"))
        else:
            lines.append("| {} | {} | {} | {:.0%} |".format(
                s["name"], s["covered"], s["total"], s["fraction"]))
    lines.append("")

    lines.append("## Covered categories\n")
    for s in cov["sections"]:
        if s.get("skills_based"):
            continue
        covered = [c for c in s["categories"] if c["covered"]]
        if not covered:
            continue
        lines.append("**{}**".format(s["name"]))
        for c in covered:
            lines.append("- {} {}  _(matched: `{}`)_".format(
                c["id"], c["title"], c["matched_keyword"]))
        lines.append("")

    miss = missing_categories(cov)
    lines.append("## Missing categories ({}) -- highest-value study gaps\n".format(len(miss)))
    for m in miss:
        lines.append("- {}".format(m))
    lines.append("")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="MCAT coverage map (7c)")
    parser.add_argument("--collection", type=str, default=None,
                        help="path to collection.anki2 (else auto-discover)")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                        help="abstain below this overall coverage fraction")
    args = parser.parse_args(argv)

    outline = json.loads(OUTLINE_PATH.read_text(encoding="utf-8"))

    col_path: Optional[Path] = None
    if args.collection:
        p = Path(args.collection)
        if p.is_file():
            col_path = p
        else:
            print("warning: --collection not found: {}".format(p))
    if col_path is None:
        cands = collection_candidates()
        col_path = cands[0] if cands else None

    if col_path is not None:
        try:
            topic_strings, meta = topics_from_collection(col_path)
            source_desc = "Anki collection ({})".format(col_path)
        except sqlite3.Error as e:
            print("could not read collection ({}); using gold-set proxy".format(e))
            topic_strings, meta = topics_from_gold()
            source_desc = "gold-set proxy (collection unreadable)"
    else:
        topic_strings, meta = topics_from_gold()
        source_desc = ("gold-set proxy -- no Anki collection found; connect one "
                       "for live coverage")

    cov = compute_coverage(outline, topic_strings)
    write_reports(cov, args.threshold, source_desc, meta)

    show = cov["overall_fraction"] >= args.threshold
    print("coverage: {}/{} categories = {:.1%} ({}) [source: {}]".format(
        cov["overall_covered"], cov["overall_total"], cov["overall_fraction"],
        "SHOW" if show else "ABSTAIN", source_desc))
    print("report -> {}".format(REPORT_PATH))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
