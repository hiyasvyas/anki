"""Crash-test worker: opens the collection and reviews cards forever until it is
hard-killed by the parent. Never exits cleanly on its own -- the whole point is
that the parent kills it mid-review. Run indirectly via `crash_test.py`.

    python -m speedrun.crash._worker <collection.anki2>
"""

from __future__ import annotations

import sys


def main() -> int:
    from anki.collection import Collection

    path = sys.argv[1]
    col = Collection(path)
    did = col.decks.id("MCAT::Crash")
    col.decks.select(did)
    # Review as fast as possible; refill by rolling to a new study day when the
    # queue empties. Each answerCard writes through the shared Rust backend, so a
    # kill can land before, during, or after a committed write.
    while True:
        card = col.sched.getCard()
        if card is None:
            col.db.execute("update col set crt = crt - 86400")
            col.close(downgrade=False)
            col = Collection(path)
            col.decks.select(did)
            continue
        col.sched.answerCard(card, 3)


if __name__ == "__main__":
    raise SystemExit(main())
