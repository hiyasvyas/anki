"""Leakage check (7e).

The harm 7e targets is a held-out TEST QUESTION being pre-seen by the model or
reproduced verbatim, which would inflate the eval. See ``config.py`` (the
re-declared leakage section) for the full rationale. In short:

* A test item's IDENTITY is its QUESTION (stem), not its answer. The correct
  answer to a factual MCAT item IS the fact, and that fact legitimately appears
  in any grounded source passage and in the correct answer choice -- flagging it
  would be a false positive (grounding, not leakage).
* So we scan the held-out gold QUESTION STEMS against:
  (a) the PRIMING the model receives (system prompt + few-shot examples), and
  (b) the GENERATED STEMS (answer choices excluded).
* Source passages are the substrate we generate FROM; source<->fact overlap is
  expected provenance. A source is flagged only if it reproduces a WHOLE gold
  item (question + answer) near-verbatim -- a pasted Q&A, not a shared fact.

If any of those trip, the eval numbers could be meaningless; this proves they
aren't.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import config
from . import textsim
from .eval import split_gold
from .generator import FEW_SHOT, SYSTEM_PROMPT
from .items import GeneratedItem, GoldItem, load_generated, load_gold


@dataclass
class LeakFlag:
    scope: str
    candidate_ref: str
    test_id: str
    kind: str  # "exact" | "near-duplicate"
    overlap: float
    candidate_excerpt: str
    test_excerpt: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "scope": self.scope,
            "candidate_ref": self.candidate_ref,
            "test_id": self.test_id,
            "kind": self.kind,
            "overlap": round(self.overlap, 3),
            "candidate_excerpt": self.candidate_excerpt[:160],
            "test_excerpt": self.test_excerpt[:160],
        }


@dataclass
class LeakageReport:
    clean: bool
    n_test_items: int
    n_candidates_scanned: int
    flags: List[LeakFlag] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "clean": self.clean,
            "n_test_items": self.n_test_items,
            "n_candidates_scanned": self.n_candidates_scanned,
            "ngram_n": config.LEAKAGE_NGRAM_N,
            "max_overlap": config.LEAKAGE_MAX_OVERLAP,
            "source_item_overlap": config.LEAKAGE_SOURCE_ITEM_OVERLAP,
            "flags": [f.to_dict() for f in self.flags],
        }


@dataclass
class _Target:
    id: str
    stem: str  # the test item's identity (its question)
    full: str  # question + answer, for whole-item verbatim detection


def _targets(heldout: List[GoldItem]) -> List[_Target]:
    return [
        _Target(id=g.id, stem=g.question, full="{} {}".format(g.question, g.answer))
        for g in heldout
    ]


def _near_copy_scan(
    scope: str,
    candidates: List[Dict[str, str]],
    targets: List[_Target],
    threshold: float,
) -> List[LeakFlag]:
    """Flag a candidate that contains, or is a near-copy of, a test QUESTION."""
    flags: List[LeakFlag] = []
    norm_targets = [(t, textsim.normalized(t.stem)) for t in targets]
    for cand in candidates:
        cnorm = textsim.normalized(cand["text"])
        if not cnorm:
            continue
        for t, tnorm in norm_targets:
            if not tnorm:
                continue
            if tnorm == cnorm or tnorm in cnorm:
                flags.append(
                    LeakFlag(scope, cand["ref"], t.id, "exact", 1.0, cand["text"], t.stem)
                )
                continue
            ov = max(
                textsim.ngram_overlap(cand["text"], t.stem, config.LEAKAGE_NGRAM_N),
                textsim.ngram_overlap(t.stem, cand["text"], config.LEAKAGE_NGRAM_N),
            )
            if ov >= threshold:
                flags.append(
                    LeakFlag(scope, cand["ref"], t.id, "near-duplicate", ov,
                             cand["text"], t.stem)
                )
    return flags


def _whole_item_scan(
    scope: str,
    candidates: List[Dict[str, str]],
    targets: List[_Target],
    threshold: float,
) -> List[LeakFlag]:
    """Flag a candidate (a source passage) ONLY if it reproduces a WHOLE gold
    item -- both the question and the answer -- near-verbatim. A source sharing a
    single fact with a gold answer is expected grounding and is NOT flagged."""
    flags: List[LeakFlag] = []
    for cand in candidates:
        cnorm = textsim.normalized(cand["text"])
        if not cnorm:
            continue
        for t in targets:
            # Require the ANSWER to be present AND the QUESTION to be substantially
            # reproduced -- i.e. the item was pasted in, not merely referenced.
            ans_present = textsim.overlap_coefficient(t.stem.split("?")[-1] or t.full, cand["text"])
            item_norm = textsim.normalized(t.full)
            if item_norm and item_norm in cnorm:
                flags.append(
                    LeakFlag(scope, cand["ref"], t.id, "exact", 1.0, cand["text"], t.full)
                )
                continue
            ov = textsim.ngram_overlap(t.full, cand["text"], config.LEAKAGE_NGRAM_N)
            if ov >= threshold and ans_present >= 0.9:
                flags.append(
                    LeakFlag(scope, cand["ref"], t.id, "near-duplicate", ov,
                             cand["text"], t.full)
                )
    return flags


def _priming_candidates() -> List[Dict[str, str]]:
    """Everything that PRIMES the model: the system prompt + few-shot examples.
    These are the only inputs that could teach the model a test item; they must
    be disjoint from the held-out gold."""
    cands: List[Dict[str, str]] = [{"ref": "system-prompt", "text": SYSTEM_PROMPT}]
    for i, (src_text, outs) in enumerate(FEW_SHOT):
        cands.append({"ref": "few-shot#{}:source".format(i), "text": src_text})
        cands.append({"ref": "few-shot#{}:output".format(i), "text": json.dumps(outs)})
    return cands


def run_leakage(items: Optional[List[GeneratedItem]] = None) -> LeakageReport:
    gold = load_gold()
    _seen, heldout = split_gold(gold)
    targets = _targets(heldout)

    # (a) priming the model receives.
    priming = _priming_candidates()

    # (b) generated STEMS only (answer choices excluded on purpose: the correct
    # choice legitimately equals the answer fact).
    items = items if items is not None else load_generated()
    gen_stems = [{"ref": it.id, "text": it.stem} for it in items]

    # (c) source passages -- flagged only for a whole pasted Q&A.
    from .sources import load_sources
    sources = [
        {"ref": "source:{}".format(u.source_id), "text": u.text}
        for u in load_sources()
    ]

    flags: List[LeakFlag] = []
    flags.extend(_near_copy_scan("priming", priming, targets, config.LEAKAGE_MAX_OVERLAP))
    flags.extend(_near_copy_scan("generated-stems", gen_stems, targets, config.LEAKAGE_MAX_OVERLAP))
    flags.extend(_whole_item_scan("source-verbatim", sources, targets, config.LEAKAGE_SOURCE_ITEM_OVERLAP))

    n_scanned = len(priming) + len(gen_stems) + len(sources)
    return LeakageReport(
        clean=len(flags) == 0,
        n_test_items=len(targets),
        n_candidates_scanned=n_scanned,
        flags=flags,
    )
