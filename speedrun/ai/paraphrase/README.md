# Paraphrase test (challenge 7d)

Proves the app measures **performance**, not just **memory**. We take **30 cards**,
each with **2 exam-style reworded questions** that test the same idea in new
words, then compare **recall on the card** with **accuracy on the reworded
questions**. If the two are basically equal, the performance model is just
copying the memory model. The **gap** is the memory→performance bridge.

## Files
- `paraphrase_set.json` — 30 cards × 2 reworded questions (grounded in the cited
  gold facts; stems deliberately avoid the card's wording).
- `attempts_sample.json` — **illustrative synthetic** attempts (`_sample: true`)
  so the harness runs today. A run on this file is `measured=false` and must NOT
  set the engine config.
- `attempts.json` *(you create)* — real attempts, same shape as the sample:
  `card_recall` (card_id → 1/0 recalled) and `reworded_correct` (qid → 1/0). A run
  on real attempts is `measured=true`.

## Run (from repo root)
```powershell
python -m speedrun.ai.run paraphrase
```
Writes `../artifacts/report_paraphrase.md`, `transfer_factor.json`, and
`mcat_transfer_factor.json` (which includes `safe_to_set_config`).

## Current illustrative result
recall **90.0%** vs reworded **71.7%** → **gap 18.3%**, transfer factor **0.796**
(CI [0.658, 0.905], n=60), `measured=false`. Real student attempts (or the app's
logged reviews: recall from FSRS, correctness from answering the reworded
questions) replace the sample to yield a measured factor for the Rust engine.
