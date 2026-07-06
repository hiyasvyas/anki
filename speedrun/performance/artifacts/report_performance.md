# Performance model -- held-out accuracy (section 9, step 2)

**Question:** can we predict whether the student answers a NEW, reworded exam-style question correctly?

**Model:** `P(correct) = FSRS_recall(card) x transfer_factor`, the memory->performance bridge. Source: ILLUSTRATIVE synthetic attempts (`measured=false`): proves the harness and shows the result shape; does NOT set the engine transfer factor.

**Protocol (2-fold cross-validation by card on the 30-card paraphrase set):** cards are split into two halves; we train the transfer factor on one half and predict the other, then swap, so **every** reworded question is held out exactly once and predicted by a model that never saw its card (no leakage between a card's two questions).

- Transfer factor (2-fold mean): **0.801** (overall recall 90.0% -> reworded 71.7%).
- Held-out questions (pooled over both folds): **60**, base correct rate **71.7%**.

## Held-out results

| Model | accuracy | Brier | log loss | mean predicted |
| --- | ---: | ---: | ---: | ---: |
| **Performance (memory x transfer)** | 78.3% | **0.2090** | 0.8457 | 72.5% |
| Memory-only baseline (assume perf = memory) | 78.3% | 0.2167 | 2.9934 | 90.0% |

**Performance model held-out accuracy: 78.3%.** Modelling the transfer gap beats the memory-only baseline on Brier score (0.2090 vs 0.2167) -- the memory-only model is over-confident because it assumes recalling the card equals answering a reworded question, which the paraphrase gap shows is false.

## Does memory separate performance? (discrimination)

- Held-out accuracy when the card WAS recalled: **77.8%** (n=54).
- Held-out accuracy when the card was NOT recalled: **16.7%** (n=6).

Recall predicts reworded success (the gap between the two groups), but recall alone over-states it -- which is exactly why the bridge applies a discount rather than treating memory as performance.

## Honesty / limits

- Synthetic attempts, so this is a **harness + shape** result, not a measured MCAT claim; `measured=false`, engine config is not set from it.
- The bridge here is a single global transfer factor. The Rust engine (`mcat_performance`) applies it per topic; richer per-question difficulty and timing features (section 9.2) plug into the same held-out evaluation.

## Reproduce

```bash
python -m speedrun.performance.eval_performance
python -m speedrun.performance.eval_performance selftest
```
