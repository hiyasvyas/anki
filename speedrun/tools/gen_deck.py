#!/usr/bin/env python3
"""Reusable Anki deck/collection generator for the Speedrun MCAT fork.

Builds a brand-new Anki collection (``.anki2``) at a given path, populated with
a configurable number of Basic notes distributed across a configurable number
of subdecks (simulated "topics" like ``MCAT::Topic01``). Optionally simulates
graded reviews per card using the *real* backend scheduler
(``col.sched.answerCard``), so the generated collection contains genuine revlog
rows rather than hand-faked data.

This script must be run with the pylib pyenv Python and the built ``anki``
package on ``PYTHONPATH``. From the repo root
(``C:\\dev\\speedrun\\anki``), the exact invocation is:

    $env:PYTHONPATH="C:\\dev\\speedrun\\anki\\out\\pylib"; `
      & "C:\\dev\\speedrun\\anki\\out\\pyenv\\Scripts\\python.exe" `
      speedrun\\tools\\gen_deck.py `
      --out speedrun\\fixtures\\bench_50k.anki2 `
      --cards 50000 --decks 20 --reviews-per-card 0 --seed 1234

Notes:
  * ``--out`` must NOT already exist (we refuse to overwrite so you never
    clobber a real collection by accident). Delete it first if regenerating.
  * ``--reviews-per-card 0`` (the default) creates only new cards -- ideal for
    a pure benchmark fixture. When > 0, each card is answered R times through
    the scheduler, writing R graded revlog rows per card.
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import time


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate a new Anki collection with N cards across M subdecks."
    )
    p.add_argument("--out", required=True, help="Output .anki2 path (must not exist).")
    p.add_argument("--cards", type=int, default=50000, help="Total cards to create.")
    p.add_argument(
        "--decks",
        type=int,
        default=20,
        help="Number of topic subdecks (MCAT::TopicNN).",
    )
    p.add_argument(
        "--reviews-per-card",
        type=int,
        default=0,
        help="Graded reviews to simulate per card via the real scheduler (0 = none).",
    )
    p.add_argument("--seed", type=int, default=1234, help="RNG seed for reproducibility.")
    return p.parse_args(argv)


# A little varied text so notes are not byte-identical (keeps DB size realistic).
TOPIC_WORDS = [
    "amino acid", "glycolysis", "enzyme kinetics", "membrane potential",
    "Doppler effect", "Le Chatelier", "operant conditioning", "Nernst equation",
    "oxidative phosphorylation", "acid-base", "optics", "thermodynamics",
    "Mendelian genetics", "action potential", "titration", "buffer capacity",
    "social cognition", "attachment theory", "electrochemistry", "spectroscopy",
]


def _front_back(rng: random.Random, deck_idx: int, card_idx: int) -> tuple[str, str]:
    topic = TOPIC_WORDS[deck_idx % len(TOPIC_WORDS)]
    a, b = rng.randint(1, 999), rng.randint(1, 999)
    front = f"[Topic {deck_idx + 1:02d}] Q{card_idx}: define {topic} case #{a}"
    back = f"Answer {b}: {topic} explained (card {card_idx}, deck {deck_idx + 1})."
    return front, back


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rng = random.Random(args.seed)

    out_path = os.path.abspath(args.out)
    if os.path.exists(out_path):
        print(f"ERROR: output already exists, refusing to overwrite: {out_path}")
        return 2
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    # Import here so --help works without the built engine on PYTHONPATH.
    from anki.collection import Collection

    print(
        f"Generating {args.cards} cards across {args.decks} decks "
        f"({args.reviews_per_card} reviews/card) -> {out_path}"
    )
    t0 = time.time()

    col = Collection(out_path)
    try:
        basic = col.models.by_name("Basic")
        if basic is None:
            raise RuntimeError("Basic notetype not found in fresh collection")

        # Pre-create the topic subdecks and cache their ids.
        deck_ids = []
        for d in range(args.decks):
            name = f"MCAT::Topic{d + 1:02d}"
            deck_ids.append(col.decks.id(name))
        print(f"Created {len(deck_ids)} subdecks under 'MCAT'.")

        created = 0
        for i in range(args.cards):
            deck_idx = i % args.decks
            note = col.new_note(basic)
            front, back = _front_back(rng, deck_idx, i)
            note.fields[0] = front
            note.fields[1] = back
            col.add_note(note, deck_ids[deck_idx])
            created += 1
            if created % 5000 == 0:
                print(f"  ... {created}/{args.cards} cards ({time.time() - t0:.1f}s)")

        print(f"Card creation done: {created} cards in {time.time() - t0:.1f}s.")

        reviews_written = 0
        if args.reviews_per_card > 0:
            # Answer each card R times through the real scheduler. Ratings are
            # mostly "Good" with occasional "Hard"/"Easy"/"Again" for realism.
            ratings = [3, 3, 3, 2, 4, 1]
            cids = col.db.list("select id from cards")
            print(f"Simulating {args.reviews_per_card} reviews for {len(cids)} cards...")
            from anki.cards import Card

            for r in range(args.reviews_per_card):
                for cid in cids:
                    card = Card(col, cid)
                    ease = rng.choice(ratings)
                    col.sched.answerCard(card, ease)
                    reviews_written += 1
                    if reviews_written % 10000 == 0:
                        print(
                            f"  ... {reviews_written} reviews "
                            f"({time.time() - t0:.1f}s)"
                        )
            print(f"Reviews done: {reviews_written} graded reviews.")

        col.save()
        card_count = col.card_count()
        note_count = col.note_count()
        deck_count = len(col.decks.all_names_and_ids())
    finally:
        col.close()

    elapsed = time.time() - t0
    size_mb = os.path.getsize(out_path) / (1024 * 1024)
    print("---- SUMMARY ----")
    print(f"output       : {out_path}")
    print(f"cards created: {card_count}")
    print(f"notes created: {note_count}")
    print(f"decks (incl Default+MCAT parent): {deck_count}")
    print(f"reviews      : {reviews_written}")
    print(f"file size    : {size_mb:.1f} MB")
    print(f"elapsed      : {elapsed:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
