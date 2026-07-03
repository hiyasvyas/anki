# Performance Model — one page

**Question it answers:** *Can the student answer a NEW, exam-style question that
uses this fact — including ones they have never seen?*

**Engine call:** `mcat_performance` (Rust, `rslib/src/stats/performance.rs`).
Read-only; reuses `mcat_deck_score` (memory) and `mcat_mastery` (per-topic) so it
can never drift from the memory model.

## The bridge, stated honestly
Remembering a card is **not** the same as answering a reworded question about it.
We model performance as memory discounted by a **measured transfer factor**:

```
performance      = clamp01(memory_score  · transfer_factor)
performance_low  = clamp01(memory_lower  · transfer_factor_lower)
performance_high = clamp01(memory_upper  · transfer_factor_upper)
```

- The transfer factor is **measured, not invented** — it comes from the
  paraphrase test (challenge 7d): for a set of cards we generate exam-style
  reworded questions and compare recall on the card vs accuracy on the reworded
  questions. The ratio (with its confidence interval) is written to
  `speedrun/ai/artifacts/transfer_factor.json` and loaded into the engine via
  the collection config key `mcatTransferFactor`.
- **Honest default:** if the factor has not been measured yet, it defaults to
  `1.0` and the response flags `transfer_measured = false`. In that state the app
  shows performance *equal to* memory rather than fabricating a discount — and
  says so. A gap only appears once we have measured one.

## Why separate from memory
If performance ≈ memory after measurement, we have **not** built the bridge and we
report that gap openly (per 7d). The whole point is to surface the difference
between "remembers the card" and "can use it on a new question."

## Sunday Step 2
Predict whether the student gets **held-out exam-style questions** right using
topic mastery, question difficulty, timing, and coverage; report accuracy on the
held-out set. The transfer factor is the first, simplest version of this
predictor and is upgraded as held-out attempt data accrues.

**Outputs:** overall `performance` + range, per-topic performance + range,
`transfer_factor` (+range), `transfer_measured`, `rated_cards`, `scorable_cards`.
