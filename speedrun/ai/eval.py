"""Held-out evaluation that MUST pass before any student sees a card.

We split the gold set deterministically into a "seen" portion and a HELD-OUT
portion (the generator never receives the held-out answers -- proven separately
by ``leakage.py``). We then check the AI generator's produced cards whose facts
correspond to held-out gold items and report, against pre-declared cutoffs:

* accuracy      -- of verifiable cards, the fraction whose marked answer agrees
                   with the known held-out answer.
* wrong-answer  -- the fraction whose marked answer is an outright wrong fact.
                   (A wrong fact is worse than no card, so this ceiling is strict.)
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import checker
from . import config
from .items import GeneratedItem, GoldItem, load_generated, load_gold


def split_gold(
    gold: List[GoldItem],
    heldout_fraction: float = config.EVAL_HELDOUT_FRACTION,
    seed: int = config.EVAL_SPLIT_SEED,
) -> Tuple[List[GoldItem], List[GoldItem]]:
    """Deterministic (seen, heldout) split."""
    items = list(gold)
    rng = random.Random(seed)
    rng.shuffle(items)
    n_heldout = int(round(len(items) * heldout_fraction))
    heldout = items[:n_heldout]
    seen = items[n_heldout:]
    return seen, heldout


@dataclass
class EvalResult:
    n_generated: int
    n_evaluable: int
    correct: int
    wrong: int
    unverifiable: int
    accuracy: float
    wrong_rate: float
    coverage: float
    meets_accuracy: bool
    meets_wrong_rate: bool
    passed: bool
    heldout_size: int
    rows: List[Dict[str, object]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "n_generated": self.n_generated,
            "heldout_size": self.heldout_size,
            "n_evaluable": self.n_evaluable,
            "correct": self.correct,
            "wrong": self.wrong,
            "unverifiable": self.unverifiable,
            "accuracy": round(self.accuracy, 3),
            "wrong_rate": round(self.wrong_rate, 3),
            "coverage": round(self.coverage, 3),
            "cutoffs": {
                "min_accuracy": config.EVAL_MIN_ACCURACY,
                "max_wrong_rate": config.EVAL_MAX_WRONG_RATE,
            },
            "meets_accuracy": self.meets_accuracy,
            "meets_wrong_rate": self.meets_wrong_rate,
            "passed": self.passed,
        }


def run_eval(
    items: Optional[List[GeneratedItem]] = None,
    gold: Optional[List[GoldItem]] = None,
) -> EvalResult:
    items = items if items is not None else load_generated()
    gold = gold if gold is not None else load_gold()
    _seen, heldout = split_gold(gold)

    heldout_by_source: Dict[str, List[GoldItem]] = {}
    for g in heldout:
        heldout_by_source.setdefault(g.source_id, []).append(g)

    correct = 0
    wrong = 0
    unverifiable = 0
    rows: List[Dict[str, object]] = []

    for it in items:
        gold_for_source = heldout_by_source.get(it.source_id)
        if not gold_for_source:
            continue  # nothing held out for this source -> not part of the eval
        verdict = checker.answer_key_verdict(it, gold_for_source)
        if verdict == "correct":
            correct += 1
        elif verdict == "wrong":
            wrong += 1
        else:
            unverifiable += 1
        rows.append({"item_id": it.id, "source_id": it.source_id, "verdict": verdict})

    considered = correct + wrong + unverifiable
    evaluable = correct + wrong
    accuracy = (correct / evaluable) if evaluable else 0.0
    wrong_rate = (wrong / evaluable) if evaluable else 0.0
    coverage = (evaluable / considered) if considered else 0.0

    meets_acc = accuracy >= config.EVAL_MIN_ACCURACY
    meets_wrong = wrong_rate <= config.EVAL_MAX_WRONG_RATE
    passed = meets_acc and meets_wrong and evaluable > 0

    return EvalResult(
        n_generated=len(items),
        n_evaluable=evaluable,
        correct=correct,
        wrong=wrong,
        unverifiable=unverifiable,
        accuracy=accuracy,
        wrong_rate=wrong_rate,
        coverage=coverage,
        meets_accuracy=meets_acc,
        meets_wrong_rate=meets_wrong,
        passed=passed,
        heldout_size=len(heldout),
        rows=rows,
    )
