"""The gate that runs BEFORE any student sees a card.

For each generated MCQ it checks three things, using ONLY the card and its
cited source (plus, for the copy test, the set of questions the student is
already assumed to have seen):

(a) well-formedness  -- exactly four distinct non-empty choices, a valid single
    answer index, a non-trivial stem, and NO prompt-injection markers copied
    from the source.
(b) source grounding -- the correct answer + rationale must be supported by the
    cited source text (token overlap coefficient >= MIN_GROUNDING_SCORE).
(c) transfer, not copy -- the stem must NOT restate the source's own wording or
    a question the student has already seen (overlap < MAX_TRANSFER_SIMILARITY).
    This is the whole point of 7d: prove it tests the idea in different words.

Anything that fails is BLOCKED. Separately, ``answer_key_verdict`` classifies a
card's marked answer against the known gold answers as correct / wrong /
unverifiable -- a wrong fact is worse than no card, so it is tracked explicitly
and always blocked in the 7f report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import config
from . import textsim
from .items import GeneratedItem, GoldItem
from .sources import SourceUnit

# Substrings that should never appear in a clean generated card; their presence
# suggests prompt-injection text leaked from a source into the output.
INJECTION_MARKERS: List[str] = [
    "ignore previous",
    "ignore all previous",
    "disregard previous",
    "disregard all",
    "system prompt",
    "you are now",
    "as an ai language model",
    "assistant:",
    "<|",
    "|>",
    "[[",
]


@dataclass
class CheckResult:
    item_id: str
    source_id: str
    passed: bool
    wellformed: bool
    grounded: bool
    is_transfer: bool
    grounding_score: float
    transfer_sim: float
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "item_id": self.item_id,
            "source_id": self.source_id,
            "passed": self.passed,
            "wellformed": self.wellformed,
            "grounded": self.grounded,
            "is_transfer": self.is_transfer,
            "grounding_score": round(self.grounding_score, 4),
            "transfer_sim": round(self.transfer_sim, 4),
            "reasons": list(self.reasons),
        }


def _check_wellformed(item: GeneratedItem) -> List[str]:
    reasons: List[str] = []
    choices = [c.strip() for c in item.choices]
    if not (config.MIN_CHOICES <= len(choices) <= config.MAX_CHOICES):
        reasons.append(
            "expected {}-{} choices, got {}".format(
                config.MIN_CHOICES, config.MAX_CHOICES, len(choices)
            )
        )
    if any(not c for c in choices):
        reasons.append("one or more empty choices")
    normalized = [textsim.normalized(c) for c in choices]
    if len(set(normalized)) != len(normalized):
        reasons.append("duplicate choices")
    if not (0 <= item.answer_index < len(item.choices)):
        reasons.append("answer_index out of range")
    if len(textsim.tokenize(item.stem)) < 3:
        reasons.append("stem too short / trivial")
    haystack = " ".join([item.stem] + item.choices + [item.rationale]).lower()
    for marker in INJECTION_MARKERS:
        if marker in haystack:
            reasons.append("possible prompt-injection marker: '{}'".format(marker))
            break
    return reasons


def check_item(
    item: GeneratedItem,
    source: Optional[SourceUnit],
    reference_questions: Optional[List[str]] = None,
) -> CheckResult:
    reference_questions = reference_questions or []
    reasons: List[str] = []

    wf_reasons = _check_wellformed(item)
    wellformed = not wf_reasons
    reasons.extend(wf_reasons)

    # (b) grounding: correct answer + rationale supported by the source text.
    if source is None:
        grounding_score = 0.0
        reasons.append("cited source '{}' not found".format(item.source_id))
    else:
        answer_text = "{} {}".format(item.correct_choice, item.rationale)
        grounding_score = textsim.overlap_coefficient(answer_text, source.text)
    grounded = grounding_score >= config.MIN_GROUNDING_SCORE
    if not grounded:
        reasons.append(
            "grounding {:.2f} < {:.2f}".format(grounding_score, config.MIN_GROUNDING_SCORE)
        )

    # (c) transfer, not copy: stem must not restate source wording or a seen Q.
    sims: List[float] = []
    if source is not None:
        sims.append(textsim.overlap_coefficient(item.stem, source.text))
    for rq in reference_questions:
        sims.append(textsim.overlap_coefficient(item.stem, rq))
    transfer_sim = max(sims) if sims else 0.0
    is_transfer = transfer_sim < config.MAX_TRANSFER_SIMILARITY
    if not is_transfer:
        reasons.append(
            "near-copy: stem overlap {:.2f} >= {:.2f}".format(
                transfer_sim, config.MAX_TRANSFER_SIMILARITY
            )
        )

    passed = wellformed and grounded and is_transfer
    return CheckResult(
        item_id=item.id,
        source_id=item.source_id,
        passed=passed,
        wellformed=wellformed,
        grounded=grounded,
        is_transfer=is_transfer,
        grounding_score=grounding_score,
        transfer_sim=transfer_sim,
        reasons=reasons,
    )


def reference_questions_by_source(gold: List[GoldItem]) -> Dict[str, List[str]]:
    """The questions a student is assumed to have already seen, grouped by
    source, used for the copy test."""
    out: Dict[str, List[str]] = {}
    for g in gold:
        out.setdefault(g.source_id, []).append(g.question)
    return out


def check_all(
    items: List[GeneratedItem],
    sources_by_id: Dict[str, SourceUnit],
    gold: Optional[List[GoldItem]] = None,
) -> List[CheckResult]:
    refs = reference_questions_by_source(gold or [])
    results: List[CheckResult] = []
    for it in items:
        src = sources_by_id.get(it.source_id)
        results.append(check_item(it, src, refs.get(it.source_id, [])))
    return results


# --------------------------------------------------------------------------
# Answer-key verdict (factual correctness) -- used by eval and the 7f report.
# --------------------------------------------------------------------------
def answer_key_verdict(item: GeneratedItem, gold_for_source: List[GoldItem]) -> str:
    """Classify the card's marked answer against the known gold answers for the
    same source: 'correct', 'wrong', or 'unverifiable'.

    correct  -> the marked choice matches a known gold answer.
    wrong    -> a known gold answer exists AND some *other* choice matches it
                better than the marked one (the card marked a wrong option), or
                the marked choice contradicts the only relevant gold answer.
    unverifiable -> no gold answer covers this card's fact.
    """
    if not gold_for_source:
        return "unverifiable"
    marked = item.correct_choice
    # Score every gold answer against the marked choice; take the best-matching
    # gold answer as the fact this card is probably about.
    best_gold = None
    best_marked = 0.0
    for g in gold_for_source:
        s = textsim.overlap_coefficient(g.answer, marked)
        if s > best_marked:
            best_marked = s
            best_gold = g
    if best_gold is None:
        return "unverifiable"

    if best_marked >= config.ANSWER_MATCH_THRESHOLD:
        return "correct"

    # The marked choice didn't match any gold answer well. Check whether one of
    # the OTHER choices matches this card's most-relevant gold answer -- if so,
    # the card marked the wrong option (asserts a wrong fact). We pick the most
    # relevant gold answer by matching against the card's stem.
    relevant = _most_relevant_gold(item, gold_for_source)
    if relevant is None:
        return "unverifiable"
    for idx, choice in enumerate(item.choices):
        if idx == item.answer_index:
            continue
        if textsim.overlap_coefficient(relevant.answer, choice) >= config.ANSWER_MATCH_THRESHOLD:
            return "wrong"
    # Marked answer doesn't match and no distractor is the true answer either:
    # we can't objectively call it, so don't accuse it of a wrong fact.
    return "unverifiable"


def _most_relevant_gold(item: GeneratedItem, gold_for_source: List[GoldItem]) -> Optional[GoldItem]:
    best = None
    best_s = -1.0
    for g in gold_for_source:
        s = textsim.overlap_coefficient(g.question, item.stem) + 0.25 * textsim.overlap_coefficient(
            g.answer, " ".join(item.choices)
        )
        if s > best_s:
            best_s = s
            best = g
    return best


# --------------------------------------------------------------------------
# 7f gold-set report: three counts.
# --------------------------------------------------------------------------
@dataclass
class GoldReport:
    total: int
    correct_useful: int
    wrong: int
    correct_bad_teaching: int
    blocked: int
    pass_rate: float
    meets_cutoff: bool
    rows: List[Dict[str, object]] = field(default_factory=list)


def gold_set_report(
    items: List[GeneratedItem],
    sources_by_id: Dict[str, SourceUnit],
    gold: List[GoldItem],
) -> GoldReport:
    """Run the generated cards through the checker + answer key and bucket them:

    1. correct + useful          (ships)
    2. wrong (a wrong fact)       (blocked -- worst case)
    3. correct but bad teaching   (blocked -- vague/trivial/duplicate/ungrounded)
    """
    gold_by_source: Dict[str, List[GoldItem]] = {}
    for g in gold:
        gold_by_source.setdefault(g.source_id, []).append(g)
    refs = reference_questions_by_source(gold)

    correct_useful = 0
    wrong = 0
    bad_teaching = 0
    rows: List[Dict[str, object]] = []

    for it in items:
        src = sources_by_id.get(it.source_id)
        res = check_item(it, src, refs.get(it.source_id, []))
        verdict = answer_key_verdict(it, gold_by_source.get(it.source_id, []))

        if verdict == "wrong":
            category = "wrong"
            wrong += 1
        elif res.passed:
            category = "correct_useful"
            correct_useful += 1
        else:
            # Well-formed/grounded/transfer failed but not a proven wrong fact:
            # correct-but-bad-teaching (vague/trivial/duplicate/ungrounded).
            category = "correct_bad_teaching"
            bad_teaching += 1

        rows.append(
            {
                "item_id": it.id,
                "source_id": it.source_id,
                "category": category,
                "verdict": verdict,
                "passed_gate": res.passed,
                "grounding_score": round(res.grounding_score, 3),
                "transfer_sim": round(res.transfer_sim, 3),
                "reasons": res.reasons,
            }
        )

    total = len(items)
    blocked = wrong + bad_teaching
    pass_rate = (correct_useful / total) if total else 0.0
    meets = pass_rate >= config.GOLD_MIN_PASS_RATE
    return GoldReport(
        total=total,
        correct_useful=correct_useful,
        wrong=wrong,
        correct_bad_teaching=bad_teaching,
        blocked=blocked,
        pass_rate=pass_rate,
        meets_cutoff=meets,
        rows=rows,
    )
