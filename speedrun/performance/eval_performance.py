"""Performance model -- held-out accuracy on exam-style questions (section 9, step 2).

Step 2 asks us to *predict whether the student gets held-back exam-style questions
right*, and report accuracy on a held-out set. The performance model is the
memory->performance bridge: it discounts the memory signal (FSRS recall on the
card) by a measured transfer factor to predict success on a NEW, reworded question
testing the same idea.

    P_performance(correct on reworded q) = recall(card) * transfer_factor

We evaluate it honestly with a clean train/held-out split on the paraphrase set
(`speedrun/ai/paraphrase`). We split by CARD (not by question), so a held-out
card is entirely unseen while the transfer factor is fit -- no leakage between a
card's two reworded questions.

    * TRAIN   = half the cards (both reworded questions) -> fit the transfer factor.
    * HELD-OUT= the other half of the cards -> never seen while fitting.

Reported on the HELD-OUT questions:
    * accuracy of the performance model (the section-9.2 headline),
    * whether it beats a MEMORY-ONLY baseline (assume performance == memory, i.e.
      transfer_factor = 1) -- if modelling the transfer gap doesn't help predict
      held-out questions, we have not built the bridge,
    * Brier score + log loss for both (probabilistic quality, where the calibrated
      bridge should win even when hard-label accuracy ties).

Honesty: the committed attempts are ILLUSTRATIVE synthetic (`_sample: true`), so
this is `measured=false` -- it proves the harness and shows the shape of the
result, and must NOT set the engine's `mcatTransferFactor`. Drop in real attempts
(`paraphrase/attempts.json`) for a measured number, no code change.

Usage (from repo root):
    python -m speedrun.performance.eval_performance
    python -m speedrun.performance.eval_performance selftest
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
ARTIFACTS = HERE / "artifacts"
PARAPHRASE_DIR = HERE.parent / "ai" / "paraphrase"
SET_PATH = PARAPHRASE_DIR / "paraphrase_set.json"
ATTEMPTS_PATH = PARAPHRASE_DIR / "attempts.json"
ATTEMPTS_SAMPLE_PATH = PARAPHRASE_DIR / "attempts_sample.json"

_EPS = 1e-6
# A held-out sample: (predicted probability, actual outcome 0/1).
Sample = Tuple[float, int]


# --------------------------------------------------------------------------
# Data loading
# --------------------------------------------------------------------------
def _load_cards() -> List[dict]:
    try:
        data = json.loads(SET_PATH.read_text(encoding="utf-8"))
        return [c for c in data.get("cards", []) if isinstance(c, dict)]
    except (OSError, json.JSONDecodeError):
        return []


def _load_attempts() -> Tuple[Optional[dict], str, bool]:
    if ATTEMPTS_PATH.is_file():
        try:
            data = json.loads(ATTEMPTS_PATH.read_text(encoding="utf-8"))
            measured = not bool(data.get("_sample"))
            return data, "attempts.json", measured
        except (OSError, json.JSONDecodeError):
            pass
    if ATTEMPTS_SAMPLE_PATH.is_file():
        try:
            data = json.loads(ATTEMPTS_SAMPLE_PATH.read_text(encoding="utf-8"))
            return data, "attempts_sample.json (ILLUSTRATIVE synthetic)", False
        except (OSError, json.JSONDecodeError):
            pass
    return None, "none", False


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------
def _accuracy(samples: List[Sample]) -> float:
    if not samples:
        return 0.0
    hit = sum(1 for p, y in samples if (1 if p >= 0.5 else 0) == y)
    return hit / len(samples)


def _brier(samples: List[Sample]) -> float:
    return sum((p - y) ** 2 for p, y in samples) / len(samples) if samples else 0.0


def _log_loss(samples: List[Sample]) -> float:
    if not samples:
        return 0.0
    total = 0.0
    for p, y in samples:
        p = min(1.0 - _EPS, max(_EPS, p))
        total += -(y * math.log(p) + (1 - y) * math.log(1.0 - p))
    return total / len(samples)


# --------------------------------------------------------------------------
# Train / held-out evaluation
# --------------------------------------------------------------------------
def evaluate() -> Dict[str, object]:
    cards = _load_cards()
    attempts, source, measured = _load_attempts()
    if not cards or attempts is None:
        return {"ok": False, "reason": "no paraphrase set or attempts", "source": source}

    card_recall: Dict[str, float] = {
        str(k): float(v) for k, v in (attempts.get("card_recall") or {}).items()
    }
    reworded: Dict[str, float] = {
        str(k): float(v) for k, v in (attempts.get("reworded_correct") or {}).items()
    }

    # Usable cards: those with a recall value and >=1 reworded outcome.
    usable: List[Tuple[str, List[int]]] = []
    for card in cards:
        cid = str(card.get("card_id"))
        if cid not in card_recall:
            continue
        outcomes = [
            int(round(reworded[str(rq.get("qid"))]))
            for rq in card.get("reworded", [])
            if str(rq.get("qid")) in reworded
        ]
        if outcomes:
            usable.append((cid, outcomes))
    usable.sort(key=lambda x: x[0])

    # 2-fold cross-validation by CARD: fold A = even-indexed cards, fold B = odd.
    # Train on one fold, predict the other; pool both so EVERY question is held out
    # exactly once and is predicted by a model that never saw its card (no leakage).
    fold_a = [c for i, c in enumerate(usable) if i % 2 == 0]
    fold_b = [c for i, c in enumerate(usable) if i % 2 == 1]

    def fit_tf(train_cards: List[Tuple[str, List[int]]]) -> Tuple[float, float, float]:
        recalls = [card_recall[c] for c, _ in train_cards]
        r_mean = (sum(recalls) / len(recalls)) if recalls else 1.0
        outs = [y for _, ys in train_cards for y in ys]
        acc = (sum(outs) / len(outs)) if outs else 0.0
        tf = min(1.0, acc / r_mean) if r_mean > 0 else 0.0
        return tf, r_mean, acc

    perf: List[Sample] = []
    mem: List[Sample] = []
    test_rows: List[Tuple[str, int]] = []
    fold_factors: List[float] = []
    for train_cards, test_cards in ((fold_a, fold_b), (fold_b, fold_a)):
        tf, _, _ = fit_tf(train_cards)
        fold_factors.append(tf)
        for cid, ys in test_cards:
            r = card_recall.get(cid, 1.0)
            for y in ys:
                perf.append((max(_EPS, min(1.0 - _EPS, r * tf)), y))
                mem.append((max(_EPS, min(1.0 - _EPS, r)), y))
                test_rows.append((cid, y))

    transfer_factor = sum(fold_factors) / len(fold_factors) if fold_factors else 0.0
    tf_all, recall_mean, tr_acc = fit_tf(usable)

    # Discrimination: does memory separate who gets held-out questions right?
    hi = [y for (cid, y) in test_rows if card_recall.get(cid, 1.0) >= 0.5]
    lo = [y for (cid, y) in test_rows if card_recall.get(cid, 1.0) < 0.5]

    return {
        "ok": True,
        "source": source,
        "measured": measured,
        "cv": "2-fold by card",
        "n_cards": len(perf),
        "transfer_factor_train": transfer_factor,
        "fold_factors": fold_factors,
        "train_recall_mean": recall_mean,
        "train_reworded_acc": tr_acc,
        "heldout_base_rate": (sum(y for _, y in test_rows) / len(test_rows)) if test_rows else 0.0,
        "performance": {
            "accuracy": _accuracy(perf),
            "brier": _brier(perf),
            "log_loss": _log_loss(perf),
            "mean_predicted": sum(p for p, _ in perf) / len(perf) if perf else 0.0,
        },
        "memory_only": {
            "accuracy": _accuracy(mem),
            "brier": _brier(mem),
            "log_loss": _log_loss(mem),
            "mean_predicted": sum(p for p, _ in mem) / len(mem) if mem else 0.0,
        },
        "discrimination": {
            "recalled_group_acc": (sum(hi) / len(hi)) if hi else 0.0,
            "recalled_group_n": len(hi),
            "not_recalled_group_acc": (sum(lo) / len(lo)) if lo else 0.0,
            "not_recalled_group_n": len(lo),
        },
    }


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------
def _write_reports(res: Dict[str, object]) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "performance_eval.json").write_text(json.dumps(res, indent=2), encoding="utf-8")

    perf = res["performance"]  # type: ignore[index]
    mem = res["memory_only"]  # type: ignore[index]
    disc = res["discrimination"]  # type: ignore[index]
    brier_better = float(perf["brier"]) < float(mem["brier"])
    note = (
        "ILLUSTRATIVE synthetic attempts (`measured=false`): proves the harness and "
        "shows the result shape; does NOT set the engine transfer factor."
        if not res["measured"]
        else "Real attempts."
    )

    lines = [
        "# Performance model -- held-out accuracy (section 9, step 2)",
        "",
        "**Question:** can we predict whether the student answers a NEW, reworded "
        "exam-style question correctly?",
        "",
        "**Model:** `P(correct) = FSRS_recall(card) x transfer_factor`, the "
        "memory->performance bridge. Source: " + note,
        "",
        "**Protocol (2-fold cross-validation by card on the 30-card paraphrase "
        "set):** cards are split into two halves; we train the transfer factor on "
        "one half and predict the other, then swap, so **every** reworded question "
        "is held out exactly once and predicted by a model that never saw its card "
        "(no leakage between a card's two questions).",
        "",
        "- Transfer factor (2-fold mean): **{:.3f}** "
        "(overall recall {:.1%} -> reworded {:.1%}).".format(
            float(res["transfer_factor_train"]),
            float(res["train_recall_mean"]),
            float(res["train_reworded_acc"]),
        ),
        "- Held-out questions (pooled over both folds): **{}**, base correct rate "
        "**{:.1%}**.".format(res["n_cards"], float(res["heldout_base_rate"])),
        "",
        "## Held-out results",
        "",
        "| Model | accuracy | Brier | log loss | mean predicted |",
        "| --- | ---: | ---: | ---: | ---: |",
        "| **Performance (memory x transfer)** | {:.1%} | **{:.4f}** | {:.4f} | {:.1%} |".format(
            float(perf["accuracy"]), float(perf["brier"]),
            float(perf["log_loss"]), float(perf["mean_predicted"]),
        ),
        "| Memory-only baseline (assume perf = memory) | {:.1%} | {:.4f} | {:.4f} | {:.1%} |".format(
            float(mem["accuracy"]), float(mem["brier"]),
            float(mem["log_loss"]), float(mem["mean_predicted"]),
        ),
        "",
        "**Performance model held-out accuracy: {:.1%}.** Modelling the transfer gap "
        "{} the memory-only baseline on Brier score ({:.4f} vs {:.4f}) -- the "
        "memory-only model is over-confident because it assumes recalling the card "
        "equals answering a reworded question, which the paraphrase gap shows is "
        "false.".format(
            float(perf["accuracy"]),
            "beats" if brier_better else "does NOT beat",
            float(perf["brier"]), float(mem["brier"]),
        ),
        "",
        "## Does memory separate performance? (discrimination)",
        "",
        "- Held-out accuracy when the card WAS recalled: **{:.1%}** (n={}).".format(
            float(disc["recalled_group_acc"]), disc["recalled_group_n"]
        ),
        "- Held-out accuracy when the card was NOT recalled: **{:.1%}** (n={}).".format(
            float(disc["not_recalled_group_acc"]), disc["not_recalled_group_n"]
        ),
        "",
        "Recall predicts reworded success (the gap between the two groups), but recall "
        "alone over-states it -- which is exactly why the bridge applies a discount "
        "rather than treating memory as performance.",
        "",
        "## Honesty / limits",
        "",
        "- Synthetic attempts, so this is a **harness + shape** result, not a measured "
        "MCAT claim; `measured=false`, engine config is not set from it.",
        "- The bridge here is a single global transfer factor. The Rust engine "
        "(`mcat_performance`) applies it per topic; richer per-question difficulty and "
        "timing features (section 9.2) plug into the same held-out evaluation.",
        "",
        "## Reproduce",
        "",
        "```bash",
        "python -m speedrun.performance.eval_performance",
        "python -m speedrun.performance.eval_performance selftest",
        "```",
    ]
    (ARTIFACTS / "report_performance.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# Selftest
# --------------------------------------------------------------------------
def _selftest() -> bool:
    ok = True

    # Metric sanity: perfect probabilistic predictions score 0 Brier.
    b0 = _brier([(1.0 - _EPS, 1), (_EPS, 0)])
    m_ok = b0 < 1e-4
    print("  Brier of perfect predictions ~ 0: {}".format("PASS" if m_ok else "FAIL"))
    ok = ok and m_ok

    # An overconfident (0.99) model must score worse on noisy outcomes.
    noisy = [(0, 0), (0, 0), (0, 1), (0, 1)]  # true rate 0.5
    honest = _brier([(0.5, y) for _, y in noisy])
    over = _brier([(0.99, y) for _, y in noisy])
    over_ok = over > honest
    print("  overconfident scores worse: {}".format("PASS" if over_ok else "FAIL"))
    ok = ok and over_ok

    # End-to-end on the committed data: runs, produces a valid transfer factor, and
    # the calibrated bridge does not do WORSE than memory-only on Brier.
    res = evaluate()
    e2e_ok = bool(res.get("ok")) and 0.0 <= float(res["transfer_factor_train"]) <= 1.0  # type: ignore[arg-type]
    brier_ok = float(res["performance"]["brier"]) <= float(res["memory_only"]["brier"]) + 1e-9  # type: ignore[index]
    print("  end-to-end on committed data: {}".format("PASS" if e2e_ok else "FAIL"))
    print("  bridge Brier <= memory-only Brier: {}".format("PASS" if brier_ok else "FAIL"))
    ok = ok and e2e_ok and brier_ok

    print("performance selftest: {}".format("ALL PASS" if ok else "FAIL"))
    return ok


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="MCAT performance held-out eval (section 9.2)")
    ap.add_argument("cmd", nargs="?", default="run", choices=["run", "selftest"])
    args = ap.parse_args(argv)

    if args.cmd == "selftest":
        return 0 if _selftest() else 1

    res = evaluate()
    if not res.get("ok"):
        print("performance eval: no data ({})".format(res.get("source")))
        return 1
    _write_reports(res)
    perf = res["performance"]  # type: ignore[index]
    mem = res["memory_only"]  # type: ignore[index]
    print("Performance held-out eval ({})".format(res["source"]))
    print("  transfer_factor(train)={:.3f}  held-out n={}".format(
        float(res["transfer_factor_train"]), res["n_cards"]))
    print("  performance: acc={:.1%}  Brier={:.4f}   memory-only: acc={:.1%}  Brier={:.4f}".format(
        float(perf["accuracy"]), float(perf["brier"]),
        float(mem["accuracy"]), float(mem["brier"])))
    print("  reports -> {}".format(ARTIFACTS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
