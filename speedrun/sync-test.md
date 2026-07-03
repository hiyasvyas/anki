# Two-Way Sync + Offline (Challenge 3 / 7b)

Desktop and phone share **one engine** and **one collection**. They sync through
Anki's own self-hosted sync server — the same server that is compiled into the
Rust engine we modified (`rslib/src/sync/http_server`). Nothing is rewritten; we
use Anki's real sync protocol, so reviews flow between the apps without loss or
double-counting.

## Setup (re-runnable)

The server is Anki's built-in one, launched from this build:

```powershell
# From the anki repo root. out/pyenv is the project's uv venv; out/pylib holds
# the generated protobuf modules.
$env:PYTHONPATH = "<repo>\out\pylib"
$env:SYNC_USER1 = "hiya:mcat123"      # the only account; no signup anywhere
$env:SYNC_HOST  = "0.0.0.0"
$env:SYNC_PORT  = "8090"              # NOT 8080: the dev desktop app runs its
                                      # Chromium web-debugger on 127.0.0.1:8080,
                                      # which would shadow the sync server on
                                      # loopback (and via the emulator's 10.0.2.2).
$env:SYNC_BASE  = "<data dir>"        # server stores each user's collection+media here
out\pyenv\Scripts\python.exe -m anki.syncserver
# -> INFO listening addr=0.0.0.0:8090
```

Client config (log in as `hiya` / `mcat123`, no AnkiWeb):

- **Desktop**: Preferences → Syncing → self-hosted server `http://127.0.0.1:8090/`.
- **AnkiDroid (emulator)**: Settings → Sync → custom sync server
  `http://10.0.2.2:8090/` (`10.0.2.2` is the AVD's alias for the host loopback).

Because the server, the desktop client, and the AnkiDroid build are all produced
from the **same 26.05 engine tree**, the sync protocol versions match exactly.
Self-hosting also keeps the 227 MB MCAT deck + media off any public server and
lets the whole test run on a LAN / fully offline.

## The conflict rule (write it down)

**Newest modification wins, per object; the review log is append-only.**

Two independent facts, straight from the engine:

1. **Reviews are never lost or double-counted.** Every review is one row in
   `revlog`, keyed by its creation time in epoch-milliseconds — a globally unique
   id. Merging just re-inserts rows by id (idempotent), so 9 phone + 9 desktop
   reviews = 18 distinct rows, and re-syncing can never duplicate one.
   (`rslib/src/sync/collection/chunks.rs::merge_revlog`.)

2. **A card's _scheduling state_ is resolved last-writer-wins by modification
   time.** When the same card was changed on both devices, the incoming version
   replaces the local one iff the local copy isn't newer:

   ```
   // rslib/src/sync/collection/chunks.rs  (add_or_update_card_if_newer)
   !existing_card.usn.is_pending_sync(pending_usn) || existing_card.mtime < entry.mtime
   ```

   i.e. the review made **later in wall-clock time** owns the card's final
   `due` / `ivl` / `type`. Notes, decks, deck-config and notetypes use the same
   `mtime`-based rule (`changes.rs`).

**Consequence (the honest part):** a card reviewed on two devices offline is
_logged twice_ (both reviews survive in the audit trail) but _advances once_ — as
the winner scheduled it. reps is not summed. This is correct: you don't want a
card double-advanced just because two devices touched it while offline.

## Results

### Part 1 — 18 offline/parallel reviews, none lost, none doubled

Baseline captured, phone put in airplane mode, then **9 reviews on the phone
(offline)** + **9 reviews on the desktop**, reconnect, sync both. Verified on the
server collection (`collection.anki2`, WAL included):

| Check                               | Result                                                      |
| ----------------------------------- | ----------------------------------------------------------- |
| Reviews after going offline (13:48) | **18** (9 phone @13:57 in airplane mode + 9 desktop @13:58) |
| Distinct cards                      | **18** → no overlap between devices                         |
| Duplicate revlog ids                | **none**                                                    |

The phone's 9 were entered with the network off and only reached the server on
reconnect → **offline review + deferred sync works**.

### Part 2 — same card, both devices offline, deterministic winner

One throwaway card (`conflict test` deck). Desktop reviewed it **first**
(`Again`), phone reviewed it **~23 s later** (`Easy`), then synced.

|                        | Review logged | Interval         |
| ---------------------- | ------------- | ---------------- |
| Desktop 14:08:56       | `Again`       | −60 (60 s lapse) |
| Phone 14:09:19 (later) | `Easy`        | +10 days         |

Final card state on the server: `ivl=10, type=review, card.mod=14:09:19` — the
**phone's later `Easy` won** the scheduling state, and **both** review rows are
present. Exactly what the `mtime`-wins rule predicts.

## Verification method

All counts were read from the server's own `collection.anki2` (copied with its
`-wal` so no committed change is missed), matching reviews by their millisecond
`revlog.id` and inspecting the conflict card's `cards` row. Re-runnable with the
snippet in Setup plus the same offline/parallel review sequence.
