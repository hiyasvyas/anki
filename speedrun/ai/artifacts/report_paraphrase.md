# Paraphrase test / transfer factor (7d)

30 cards x 2 reworded exam-style questions. We compare recall on the card vs accuracy on the reworded questions; the **gap** is the memory->performance bridge.

Attempts source: **attempts_sample.json (ILLUSTRATIVE synthetic)** (measured=False).

transfer_factor = transfer_accuracy / recall_mean; gap = recall_mean - transfer_accuracy

- cards with attempts: **30**, reworded attempts: **60**
- recall on the card: **90.0%**
- accuracy on reworded questions: **71.7%**
- **gap (recall - reworded): 18.3%**
- **transfer factor: 0.796** (95% CI [0.658, 0.905], n=60)

_measured=false (illustrative/synthetic or no attempts): do **not** set `mcatTransferFactor` from this run. Provide real attempts in `paraphrase/attempts.json` for a measured factor._

Written to `transfer_factor.json` and `mcat_transfer_factor.json`.
