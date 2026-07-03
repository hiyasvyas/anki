"""Shared, stdlib-only helpers for the robustness checks.

Same design constraints as the coverage map: standard library only, the Anki
collection is opened READ-ONLY (never disturbs a running Anki) and is never
required -- each check falls back to a synthetic self-test dataset so it always
produces a real, deterministic report.
"""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import List, Set

HERE = Path(__file__).resolve().parent
ARTIFACTS = HERE / "artifacts"

_FIELD_SEP = "\x1f"  # Anki joins note fields with U+001F.
_HTML_RE = re.compile(r"<[^>]+>")
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9\-']*")

# Small generic stopword set (content words are what matter for similarity).
_STOPWORDS: Set[str] = {
    "a", "an", "the", "and", "or", "but", "if", "then", "of", "to", "in", "on",
    "for", "with", "as", "by", "at", "from", "into", "is", "are", "was", "were",
    "be", "been", "being", "it", "its", "this", "that", "these", "those",
    "which", "who", "what", "how", "why", "where", "will", "would", "can",
    "could", "should", "may", "might", "do", "does", "did", "has", "have",
    "had", "than", "so", "there", "here", "they", "them", "we", "you", "i",
    "about", "over", "under", "between", "each", "more", "most", "some", "any",
    "all", "both", "one", "also", "very",
}

# Negation cues used to spot "opposite" answers even when wording overlaps.
NEGATIONS: Set[str] = {
    "no", "not", "never", "none", "cannot", "can't", "false", "incorrect",
    "decrease", "decreases", "decreased", "lower", "lowers", "inhibit",
    "inhibits", "negative", "less", "fewer", "down",
}
AFFIRMATIONS: Set[str] = {
    "yes", "true", "correct", "increase", "increases", "increased", "raise",
    "raises", "activate", "activates", "positive", "more", "greater", "up",
}


def strip_html(text: str) -> str:
    return _HTML_RE.sub(" ", text or "").replace(_FIELD_SEP, " ").strip()


def tokens(text: str) -> List[str]:
    toks = _WORD_RE.findall((text or "").lower())
    return [t for t in toks if t not in _STOPWORDS and len(t) > 1]


def token_set(text: str) -> Set[str]:
    return set(tokens(text))


def jaccard(a: str, b: str) -> float:
    sa, sb = token_set(a), token_set(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


def has_polarity_flip(a: str, b: str) -> bool:
    """True if one answer reads affirmative and the other negative -- a cheap
    but real signal that two answers assert opposite things."""
    ta, tb = set(tokens(a)), set(tokens(b))
    a_neg, b_neg = bool(ta & NEGATIONS), bool(tb & NEGATIONS)
    a_pos, b_pos = bool(ta & AFFIRMATIONS), bool(tb & AFFIRMATIONS)
    return (a_neg and b_pos) or (a_pos and b_neg) or (a_neg != b_neg)


def open_ro(col_path: Path) -> sqlite3.Connection:
    uri = "file:{}?mode=ro&immutable=1".format(col_path.as_posix())
    return sqlite3.connect(uri, uri=True)


def collection_candidates() -> List[Path]:
    out: List[Path] = []
    roots: List[Path] = []
    appdata = os.environ.get("APPDATA")
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


def resolve_collection(explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit)
        if p.is_file():
            return p
    cands = collection_candidates()
    return cands[0] if cands else None


def ensure_artifacts() -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
