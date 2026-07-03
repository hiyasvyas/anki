#!/usr/bin/env python3
"""Read-only review-data stats for an Anki collection.

Copies the given collection (plus any -wal/-shm sidecars) to a temp path and
opens the COPY, so the live/running Anki app is never locked. Prints card/note
counts, deck count, and revlog history statistics.

Run with the pylib pyenv Python + PYTHONPATH=out\\pylib, e.g.:

    $env:PYTHONPATH="C:\\dev\\speedrun\\anki\\out\\pylib"; `
      & "C:\\dev\\speedrun\\anki\\out\\pyenv\\Scripts\\python.exe" `
      speedrun\\tools\\collection_stats.py `
      "C:\\Users\\sunee\\AppData\\Roaming\\Anki2\\User 1\\collection.anki2"
"""

from __future__ import annotations

import datetime as dt
import os
import shutil
import sys
import tempfile


def _fmt_ms(ms: int | None) -> str:
    if not ms:
        return "n/a"
    return dt.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: collection_stats.py <path-to-collection.anki2>")
        return 2
    src = argv[1]
    if not os.path.exists(src):
        print(f"ERROR: source not found: {src}")
        return 2

    tmpdir = tempfile.mkdtemp(prefix="anki_stats_")
    copy_path = os.path.join(tmpdir, "collection_copy.anki2")
    shutil.copy2(src, copy_path)
    for suffix in ("-wal", "-shm"):
        side = src + suffix
        if os.path.exists(side):
            shutil.copy2(side, copy_path + suffix)
    print(f"Copied collection to {copy_path}")

    from anki.collection import Collection

    col = Collection(copy_path)
    try:
        card_count = col.card_count()
        note_count = col.note_count()
        decks = col.decks.all_names_and_ids()
        deck_count = len(decks)
        total_revlog = col.db.scalar("select count() from revlog")
        graded = col.db.scalar("select count() from revlog where ease between 1 and 4")
        distinct_cards = col.db.scalar(
            "select count(distinct cid) from revlog where ease between 1 and 4"
        )
        min_id = col.db.scalar("select min(id) from revlog")
        max_id = col.db.scalar("select max(id) from revlog")

        print("==== COLLECTION STATS ====")
        print(f"card_count()                 : {card_count}")
        print(f"note_count()                 : {note_count}")
        print(f"decks (all_names_and_ids)    : {deck_count}")
        print(f"revlog rows (total)          : {total_revlog}")
        print(f"graded reviews (ease 1-4)    : {graded}")
        print(f"distinct graded cards        : {distinct_cards}")
        print(f"revlog min id (ms)           : {min_id}  -> {_fmt_ms(min_id)}")
        print(f"revlog max id (ms)           : {max_id}  -> {_fmt_ms(max_id)}")
    finally:
        col.close()
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
