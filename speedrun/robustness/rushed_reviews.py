"""Robustness check: **a student who taps "Good" without reading** (section 10).

The danger: a student flips through cards, tapping a grade in a fraction of a
second without actually reading. Those reviews would inflate the memory model
and let the readiness give-up rule (>= 230 graded reviews) be satisfied with
noise instead of real study.

What this does: reads the review log (``revlog.time`` is the milliseconds the
student spent on the card) and counts reviews that are implausibly fast to be
real -- below a threshold declared before results. It reports the rushed rate
and the **honest graded count** (real reviews minus rushed), which is what the
readiness rule should count. So spamming "Good" cannot unlock a readiness score.

Usage:  python -m speedrun.robustness.rushed_reviews [--collection PATH]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import List, Optional, Tuple

from . import _common as C

# --------------------------------------------------------------------------
# DECLARED CUTOFFS (before results)
# --------------------------------------------------------------------------
# A review answered in under 800 ms was not read. (Even a fast, genuine "I know
# this" recognition + button press is ~1 s; 0.8 s is a deliberately conservative
# floor so we never discount a real review.)
MIN_HONEST_MS = 800
# The readiness give-up rule's review floor (mirrors the engine: ~1 full MCAT).
READINESS_MIN_REVIEWS = 230

REPORT_PATH = C.ARTIFACTS / "report_rushed_reviews.md"
JSON_PATH = C.ARTIFACTS / "rushed_reviews.json"


def classify(reviews: List[Tuple[int, int]]) -> dict:
    """reviews = list of (ease, time_ms). ease>0 is a real graded answer."""
    graded = [(ease, t) for (ease, t) in reviews if ease and ease > 0]
    rushed = [(ease, t) for (ease, t) in graded if 0 < t < MIN_HONEST_MS]
    n_graded = len(graded)
    n_rushed = len(rushed)
    honest = n_graded - n_rushed
    return {
        "graded_reviews": n_graded,
        "rushed_reviews": n_rushed,
        "rushed_rate": round(n_rushed / n_graded, 4) if n_graded else 0.0,
        "honest_graded_reviews": honest,
        "meets_readiness_floor_raw": n_graded >= READINESS_MIN_REVIEWS,
        "meets_readiness_floor_honest": honest >= READINESS_MIN_REVIEWS,
    }


def reviews_from_collection(col_path: Path) -> List[Tuple[int, int]]:
    conn = C.open_ro(col_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT ease, time FROM revlog")
        return [(int(e or 0), int(t or 0)) for (e, t) in cur.fetchall()]
    finally:
        conn.close()


def _selftest_reviews() -> List[Tuple[int, int]]:
    """8 genuine reviews (~3 s each) + 4 rushed taps (~0.2 s)."""
    real = [(3, 3000)] * 8
    rushed = [(3, 200)] * 4
    return real + rushed


def write_reports(stats: dict, source_desc: str) -> None:
    C.ensure_artifacts()
    JSON_PATH.write_text(json.dumps({
        "declared_cutoffs": {
            "min_honest_ms": MIN_HONEST_MS,
            "readiness_min_reviews": READINESS_MIN_REVIEWS,
        },
        "source": source_desc,
        **stats,
    }, indent=2), encoding="utf-8")

    lines: List[str] = []
    lines.append("# Rushed-review check (\"Good\" without reading)\n")
    lines.append("Source: **{}**.\n".format(source_desc))
    lines.append("## Declared cutoffs (before results)\n")
    lines.append("- a review under **{} ms** is too fast to have been read"
                 .format(MIN_HONEST_MS))
    lines.append("- readiness needs **{}** graded reviews -- counted on the "
                 "HONEST total, not the raw one\n".format(READINESS_MIN_REVIEWS))
    lines.append("## Result\n")
    lines.append("- graded reviews (raw): **{}**".format(stats["graded_reviews"]))
    lines.append("- rushed (excluded): **{}** ({:.1%})".format(
        stats["rushed_reviews"], stats["rushed_rate"]))
    lines.append("- **honest graded reviews: {}**".format(
        stats["honest_graded_reviews"]))
    lines.append("- readiness floor met on raw count: **{}**".format(
        stats["meets_readiness_floor_raw"]))
    lines.append("- readiness floor met on honest count: **{}**\n".format(
        stats["meets_readiness_floor_honest"]))
    lines.append("Rushed reviews are excluded from the count that gates a "
                 "readiness score, so tapping \"Good\" without reading cannot "
                 "unlock one.\n")
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def run(collection: Optional[str] = None) -> dict:
    col_path = C.resolve_collection(collection)
    if col_path is not None:
        try:
            reviews = reviews_from_collection(col_path)
            source_desc = "Anki collection ({})".format(col_path)
        except sqlite3.Error as e:
            reviews = _selftest_reviews()
            source_desc = "synthetic self-test (collection unreadable: {})".format(e)
    else:
        reviews = _selftest_reviews()
        source_desc = "synthetic self-test (no collection found)"

    stats = classify(reviews)
    stats["source"] = source_desc
    write_reports(stats, source_desc)
    return stats


def _selftest() -> bool:
    stats = classify(_selftest_reviews())
    ok = (stats["graded_reviews"] == 12 and stats["rushed_reviews"] == 4
          and stats["honest_graded_reviews"] == 8)
    print("selftest rushed: graded={} rushed={} honest={} -> {}".format(
        stats["graded_reviews"], stats["rushed_reviews"],
        stats["honest_graded_reviews"], "PASS" if ok else "FAIL"))
    return ok


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Rushed-review check")
    ap.add_argument("--collection", default=None)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return 0 if _selftest() else 1
    stats = run(args.collection)
    print("rushed: {}/{} graded reviews too fast ({:.1%}); honest={} [source: {}]"
          .format(stats["rushed_reviews"], stats["graded_reviews"],
                  stats["rushed_rate"], stats["honest_graded_reviews"],
                  stats["source"]))
    print("report -> {}".format(REPORT_PATH))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
