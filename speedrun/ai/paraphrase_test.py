"""Challenge 7d -- the paraphrase test, and the measured "transfer factor".

The thesis of the app is memory != performance. A student can *recall* a
memorized card and still miss the same idea asked in different words. This step
measures that gap directly:

    transfer_factor = accuracy(reworded transfer questions) / recall(the card)
    gap             = recall - reworded_accuracy

We take 30 cards, each with 2 exam-style reworded questions
(``paraphrase/paraphrase_set.json``), and read a per-student ATTEMPTS file that
records (a) whether the student recalled each card and (b) whether they answered
each reworded question correctly. The gap between the two is the whole point: if
it is ~0, the performance model is just copying the memory model.

Honesty:
* With REAL attempts, the factor is ``measured=true`` and can be written to the
  Anki config key ``mcatTransferFactor`` so the Rust performance engine uses the
  measured bridge instead of its default 1.0.
* With the committed ILLUSTRATIVE sample attempts (``_sample: true``), the factor
  is ``measured=false`` and must NOT be used to set the engine config -- it only
  proves the harness runs and shows what the gap computation looks like.

Without any attempts file, we fall back to ``assumed_recall=1.0`` and report
``measured=false`` (no bridge measured yet).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import config

PARAPHRASE_DIR: Path = config.PKG_DIR / "paraphrase"
PARAPHRASE_SET_PATH: Path = PARAPHRASE_DIR / "paraphrase_set.json"
ATTEMPTS_PATH: Path = PARAPHRASE_DIR / "attempts.json"          # real (optional)
ATTEMPTS_SAMPLE_PATH: Path = PARAPHRASE_DIR / "attempts_sample.json"  # illustrative

# Fallback assumed recall on the exact memorized card when no attempts exist.
ASSUMED_RECALL: float = 1.0


def wilson_interval(successes: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    phat = successes / n
    denom = 1.0 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    margin = (z * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n)) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


@dataclass
class TransferFactor:
    factor: float
    lower: float
    upper: float
    n: int                    # number of reworded attempts (the CI's n)
    measured: bool
    assumed_recall: float     # = measured recall mean (kept name for compatibility)
    transfer_accuracy: float
    config_key: str
    # 7d extras:
    gap: float = 0.0
    n_cards: int = 0
    recall_correct: int = 0
    reworded_correct: int = 0
    source: str = "none"

    def to_dict(self) -> Dict[str, object]:
        return {
            "factor": round(self.factor, 4),
            "lower": round(self.lower, 4),
            "upper": round(self.upper, 4),
            "n": self.n,
            "measured": self.measured,
            "source": self.source,
            "recall_mean": round(self.assumed_recall, 4),
            "transfer_accuracy": round(self.transfer_accuracy, 4),
            "gap": round(self.gap, 4),
            "n_cards": self.n_cards,
            "config_key": self.config_key,
            "note": (
                "transfer_factor = transfer_accuracy / recall_mean; "
                "gap = recall_mean - transfer_accuracy. Set the Anki config key "
                "'{}' to 'factor' ONLY for a measured=true run.".format(self.config_key)
            ),
        }


def _load_paraphrase_set() -> List[dict]:
    try:
        data = json.loads(PARAPHRASE_SET_PATH.read_text(encoding="utf-8"))
        return [c for c in data.get("cards", []) if isinstance(c, dict)]
    except (OSError, json.JSONDecodeError):
        return []


def _load_attempts() -> Tuple[Optional[dict], str, bool]:
    """Return (attempts, source_desc, measured). Prefer a real attempts.json;
    else the illustrative sample; else none."""
    if ATTEMPTS_PATH.is_file():
        try:
            data = json.loads(ATTEMPTS_PATH.read_text(encoding="utf-8"))
            measured = not bool(data.get("_sample"))
            return data, "attempts.json ({})".format(
                "real" if measured else "marked _sample"), measured
        except (OSError, json.JSONDecodeError):
            pass
    if ATTEMPTS_SAMPLE_PATH.is_file():
        try:
            data = json.loads(ATTEMPTS_SAMPLE_PATH.read_text(encoding="utf-8"))
            return data, "attempts_sample.json (ILLUSTRATIVE synthetic)", False
        except (OSError, json.JSONDecodeError):
            pass
    return None, "none (no attempts file)", False


def compute() -> TransferFactor:
    cards = _load_paraphrase_set()
    attempts, source, measured = _load_attempts()

    if not cards or attempts is None:
        # No data to measure a bridge -> honest default.
        return TransferFactor(
            factor=1.0, lower=1.0, upper=1.0, n=0, measured=False,
            assumed_recall=ASSUMED_RECALL, transfer_accuracy=ASSUMED_RECALL,
            config_key=config.TRANSFER_FACTOR_CONFIG_KEY, gap=0.0, n_cards=len(cards),
            source=source,
        )

    card_recall: Dict[str, float] = {
        str(k): float(v) for k, v in (attempts.get("card_recall") or {}).items()
    }
    reworded_correct: Dict[str, float] = {
        str(k): float(v) for k, v in (attempts.get("reworded_correct") or {}).items()
    }

    # Recall: mean over the cards we have attempts for.
    recalls: List[float] = []
    reworded_hits = 0
    reworded_total = 0
    for card in cards:
        cid = str(card.get("card_id"))
        if cid in card_recall:
            recalls.append(card_recall[cid])
        for rq in card.get("reworded", []):
            qid = str(rq.get("qid"))
            if qid in reworded_correct:
                reworded_total += 1
                reworded_hits += int(round(reworded_correct[qid]))

    recall_mean = (sum(recalls) / len(recalls)) if recalls else ASSUMED_RECALL
    recall_correct = int(round(sum(recalls)))
    transfer_acc = (reworded_hits / reworded_total) if reworded_total else 0.0
    gap = recall_mean - transfer_acc
    factor = (transfer_acc / recall_mean) if recall_mean > 0 else 0.0
    lo, hi = wilson_interval(reworded_hits, reworded_total)
    lo_f = min(1.0, lo / recall_mean) if recall_mean > 0 else 0.0
    hi_f = min(1.0, hi / recall_mean) if recall_mean > 0 else 0.0

    return TransferFactor(
        factor=factor,
        lower=lo_f,
        upper=hi_f,
        n=reworded_total,
        measured=measured,
        assumed_recall=recall_mean,
        transfer_accuracy=transfer_acc,
        config_key=config.TRANSFER_FACTOR_CONFIG_KEY,
        gap=gap,
        n_cards=len(recalls),
        recall_correct=recall_correct,
        reworded_correct=reworded_hits,
        source=source,
    )


def write_transfer_factor(tf: Optional[TransferFactor] = None) -> TransferFactor:
    tf = tf if tf is not None else compute()
    payload = tf.to_dict()
    config.ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    config.TRANSFER_FACTOR_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    # Engine-facing copy. `measured` reflects whether REAL attempts were used, so
    # a sample run cannot be mistaken for a real bridge.
    engine_copy = config.ARTIFACTS_DIR / "mcat_transfer_factor.json"
    engine_copy.write_text(
        json.dumps(
            {
                config.TRANSFER_FACTOR_CONFIG_KEY: round(tf.factor, 4),
                "lower": round(tf.lower, 4),
                "upper": round(tf.upper, 4),
                "n": tf.n,
                "measured": tf.measured,
                "safe_to_set_config": tf.measured,
                "source": tf.source,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return tf
