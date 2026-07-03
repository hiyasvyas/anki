"""Robustness check: **two cards that state opposite facts** (spec section 10).

The danger: a deck contains two cards whose questions ask the same thing but
whose answers disagree (e.g. "does X increase Y?" -> "yes" and "-> no"). Left
alone, the memory model would happily average over them and report confident
mastery of a fact the deck itself contradicts. That is exactly the kind of
"confident number with nothing behind it" the honesty rule forbids.

What this does: scans the deck read-only for near-duplicate QUESTIONS whose
ANSWERS conflict (low answer overlap, or an affirmative-vs-negative polarity
flip), and reports them so they are surfaced -- not silently folded into a
mastery score. Cutoffs are declared before looking at any result.

Usage:  python -m speedrun.robustness.contradictions [--collection PATH]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import _common as C

# --------------------------------------------------------------------------
# DECLARED CUTOFFS (before results)
# --------------------------------------------------------------------------
FRONT_SIM_MIN = 0.80   # questions this similar are treated as "the same question"
ANSWER_DIFF_MAX = 0.40  # answers this dissimilar (or polarity-flipped) => conflict
MIN_ANSWER_TOKENS = 2   # answers with fewer real content tokens are not factual

# Resource-link / boilerplate tokens that are not part of a factual answer.
_BOILERPLATE = {
    "link", "links", "khan", "academy", "youtube", "video", "com", "www",
    "http", "https", "org", "watch", "url", "nbsp",
}

REPORT_PATH = C.ARTIFACTS / "report_contradictions.md"
JSON_PATH = C.ARTIFACTS / "contradictions.json"


def _bucket_key(front: str) -> Tuple[str, ...]:
    """Coarse key so we only compare plausibly-related questions (keeps this
    O(bucket^2), not O(n^2)): the 5 longest content tokens of the question."""
    toks = sorted(set(C.tokens(front)), key=lambda t: (-len(t), t))
    return tuple(sorted(toks[:5]))


def find_contradictions(cards: List[Tuple[str, str]]) -> List[dict]:
    """cards = list of (front, back). Returns a list of conflicting pairs."""
    buckets: Dict[Tuple[str, ...], List[Tuple[str, str]]] = {}
    for front, back in cards:
        key = _bucket_key(front)
        if not key:
            continue
        buckets.setdefault(key, []).append((front, back))

    flagged: List[dict] = []
    for items in buckets.values():
        if len(items) < 2:
            continue
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                f1, b1 = items[i]
                f2, b2 = items[j]
                if C.jaccard(f1, f2) < FRONT_SIM_MIN:
                    continue  # not really the same question
                ans_sim = C.jaccard(b1, b2)
                flip = C.has_polarity_flip(b1, b2)
                if ans_sim <= ANSWER_DIFF_MAX or flip:
                    flagged.append({
                        "question_a": f1, "answer_a": b1,
                        "question_b": f2, "answer_b": b2,
                        "answer_similarity": round(ans_sim, 3),
                        "polarity_flip": flip,
                    })
    return flagged


# --------------------------------------------------------------------------
# Data sources
# --------------------------------------------------------------------------
def _is_meaningful_answer(answer: str) -> bool:
    """A real factual answer, not a resource link / boilerplate."""
    content = [t for t in C.tokens(answer) if t not in _BOILERPLATE]
    return len(content) >= MIN_ANSWER_TOKENS


def cards_from_collection(col_path: Path) -> Tuple[List[Tuple[str, str]], dict]:
    """Only genuine question->answer (basic) cards are compared. Cloze notes
    (``{{cN::...}}``) are excluded: their cards test different blanks of the
    same sentence, so they are complementary, not contradictory, and comparing
    them produces false positives. Link/boilerplate answers are skipped too."""
    conn = C.open_ro(col_path)
    out: List[Tuple[str, str]] = []
    meta = {"notes_total": 0, "notes_scanned": 0,
            "skipped_cloze": 0, "skipped_boilerplate": 0}
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT n.id, n.flds FROM notes n JOIN cards c ON c.nid = n.id"
        )
        for _nid, flds in cur.fetchall():
            meta["notes_total"] += 1
            raw = str(flds or "")
            if "{{c" in raw:  # cloze note
                meta["skipped_cloze"] += 1
                continue
            parts = raw.split(C._FIELD_SEP)
            front = C.strip_html(parts[0] if parts else "")
            back = C.strip_html(" ".join(parts[1:]) if len(parts) > 1 else "")
            if not front or not back:
                continue
            if not _is_meaningful_answer(back):
                meta["skipped_boilerplate"] += 1
                continue
            out.append((front, back))
        meta["notes_scanned"] = len(out)
    finally:
        conn.close()
    return out, meta


def _selftest_cards() -> List[Tuple[str, str]]:
    """Synthetic deck containing exactly one contradictory pair (rows 0 & 1)."""
    return [
        ("Does increasing substrate concentration increase enzyme reaction rate?",
         "Yes, the rate increases with substrate until it saturates at Vmax."),
        ("Does increasing substrate concentration increase enzyme reaction rate?",
         "No, increasing substrate decreases the reaction rate."),
        ("What organelle is the site of the citric acid cycle?",
         "The mitochondrial matrix."),
        ("What is the powerhouse of the cell?",
         "The mitochondrion."),
    ]


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------
def write_reports(flagged: List[dict], source_desc: str, meta: dict) -> None:
    C.ensure_artifacts()
    JSON_PATH.write_text(json.dumps({
        "declared_cutoffs": {
            "front_similarity_min": FRONT_SIM_MIN,
            "answer_difference_max": ANSWER_DIFF_MAX,
        },
        "source": source_desc,
        "meta": meta,
        "contradictions_found": len(flagged),
        "pairs": flagged,
    }, indent=2), encoding="utf-8")

    lines: List[str] = []
    lines.append("# Contradiction check (opposite-fact cards)\n")
    lines.append("Source: **{}**.\n".format(source_desc))
    lines.append("## Declared cutoffs (before results)\n")
    lines.append("- same-question similarity >= `{}`".format(FRONT_SIM_MIN))
    lines.append("- conflicting-answer if answer similarity <= `{}` OR an "
                 "affirmative<->negative polarity flip\n".format(ANSWER_DIFF_MAX))
    lines.append("## Result\n")
    if "notes_total" in meta:
        lines.append("- notes total: **{}** (excluded {} cloze, {} link/boilerplate)"
                     .format(meta.get("notes_total", 0), meta.get("skipped_cloze", 0),
                             meta.get("skipped_boilerplate", 0)))
    lines.append("- basic Q->A notes compared: **{}**".format(meta.get("notes_scanned", 0)))
    lines.append("- **contradictory card pairs found: {}**\n".format(len(flagged)))
    if flagged:
        lines.append("These pairs are **surfaced and excluded from mastery "
                     "confidence** (the deck disagrees with itself, so we do not "
                     "report confident recall of that fact):\n")
        for k, p in enumerate(flagged, 1):
            lines.append("**{}. Q:** {}".format(k, p["question_a"]))
            lines.append("- A1: {}".format(p["answer_a"]))
            lines.append("- A2: {}  _(answer sim {}, polarity flip: {})_".format(
                p["answer_b"], p["answer_similarity"], p["polarity_flip"]))
            lines.append("")
    else:
        lines.append("No self-contradicting card pairs detected.\n")
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def run(collection: Optional[str] = None) -> dict:
    col_path = C.resolve_collection(collection)
    if col_path is not None:
        try:
            cards, meta = cards_from_collection(col_path)
            source_desc = "Anki collection ({})".format(col_path)
        except sqlite3.Error as e:
            cards, meta = _selftest_cards(), {"notes_scanned": 4}
            source_desc = "synthetic self-test (collection unreadable: {})".format(e)
    else:
        cards, meta = _selftest_cards(), {"notes_scanned": 4}
        source_desc = "synthetic self-test (no collection found)"

    flagged = find_contradictions(cards)
    write_reports(flagged, source_desc, meta)
    return {"contradictions": len(flagged), "source": source_desc,
            "scanned": meta.get("notes_scanned", 0)}


def _selftest() -> bool:
    """Deterministic correctness check: the synthetic deck has exactly 1 pair."""
    flagged = find_contradictions(_selftest_cards())
    ok = len(flagged) == 1 and flagged[0]["polarity_flip"]
    print("selftest contradictions: found={} expected=1 -> {}".format(
        len(flagged), "PASS" if ok else "FAIL"))
    return ok


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Contradiction check (opposite facts)")
    ap.add_argument("--collection", default=None)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return 0 if _selftest() else 1
    res = run(args.collection)
    print("contradictions: {} flagged (scanned {}) [source: {}]".format(
        res["contradictions"], res["scanned"], res["source"]))
    print("report -> {}".format(REPORT_PATH))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
