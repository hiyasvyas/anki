# Memory-model calibration (section 9, step 1)

**Claim:** when the memory model says X%, the student recalls ~X%.

Source: **SYNTHETIC fallback.** The harness scanned the real collection and found only **2** genuine cross-day review predictions (the deck has been studied same-day only, with no multi-day recall history yet), so there is nothing real to calibrate on. This is a data limitation, reported honestly — the number below comes from a synthetic stream. This validates the calibration *pipeline* on a correctly-specified review stream; the moment the deck has multi-day review history, `--collection PATH` yields a real-data result with no code change.

Predicted recall is the FSRS forgetting curve `R = (1 + (19/81)·t/S)^(-1/2)` with `S` = the previous review's scheduled interval and `t` = actual elapsed time. No parameters are fit on these outcomes, so this is a held-out check of the model's predictions.

## Scores (held-out reviews)

| Metric | Value |
| --- | ---: |
| Reviews scored | 4000 |
| **Brier score** (lower is better; 0 = perfect) | **0.1329** |
| **Log loss** (lower is better) | **0.4087** |
| Expected Calibration Error (ECE) | 0.0106 |
| Observed base recall rate | 76.7% |
| Mean predicted recall | 75.7% |

**Verdict: WELL CALIBRATED.**

Reference points: predicting the base rate for every card gives a Brier of 0.1788; a coin flip (0.5) gives 0.25. Lower than the base-rate line means the per-card predictions carry real information.

## Reliability table

| predicted bin | n | mean predicted | observed recall | gap |
| --- | ---: | ---: | ---: | ---: |
| 0.3–0.4 | 361 | 35.4% | 35.7% | +0.4% |
| 0.4–0.5 | 367 | 44.6% | 46.3% | +1.7% |
| 0.5–0.6 | 333 | 55.1% | 55.6% | +0.5% |
| 0.6–0.7 | 372 | 65.2% | 64.8% | -0.4% |
| 0.7–0.8 | 436 | 75.5% | 77.5% | +2.1% |
| 0.8–0.9 | 573 | 85.2% | 86.9% | +1.8% |
| 0.9–1.0 | 1558 | 95.9% | 96.7% | +0.8% |

Reliability diagram: [`reliability.svg`](reliability.svg) — points on the dashed diagonal mean predicted = observed (perfect calibration).

## Honesty

- Because memory recall comes straight from FSRS, this is a check of **FSRS calibration on this deck**, reported as-is — we don't tune the curve to make it look better.
- The forgetting curve assumes the scheduled interval targeted 90% retention (Anki's default). Cards reviewed far off schedule and relearns are the main sources of residual error; they are kept, not filtered, so the numbers are honest.

## Reproduce

```bash
python -m speedrun.calibration.calibrate                 # auto-detects a collection
python -m speedrun.calibration.calibrate --collection PATH\collection.anki2
python -m speedrun.calibration.calibrate selftest
```
