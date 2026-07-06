# Study-feature ablation — interleaving (spec section 8)

One study feature, tested the way section 8 asks: **three builds, same questions,
same study time**, with a pre-registered metric and a failure rule.

- **Feature:** interleaving related topics within a session (vs blocked study).
- **Hypothesis (pre-set):** interleaving raises accuracy on new **mixed-topic**
  questions — ones that require telling two confusable topics apart — at equal
  study time.
- **Arms:** `full` (interleaved + weakness-targeted) · `ablation` (same
  allocation, blocked — feature OFF) · `plain` (uniform, blocked — plain Anki).
- **Primary comparison:** `full − ablation`, **paired** across the same simulated
  students, so only the study *order* differs. Failure rule: if the paired 95% CI
  includes 0, the feature is reported as *not shown to help*.

## Run it (stdlib only, deterministic)

```bash
python -m speedrun.ablation.run           # writes artifacts/report_ablation.md + ablation.json
python -m speedrun.ablation.run selftest  # determinism + both null-condition checks
```

## Honesty

This is a **transparent mechanism simulation, not a human study** — we don't have
real learners plus full-length scores in a one-week sprint, and we don't claim to.
The interleaving effect is **emergent** from one documented mechanism
(discrimination between confusable topics strengthens only when both are met close
together in time), not a hand-set bonus. Because it's emergent, the same model
produces honest **null results**, which the report keeps:

- no effect on a single-topic **memory-only** metric (order doesn't change how much
  memory each topic got);
- no effect when topics are **not confusable** (nothing to discriminate).

To turn this into a *measured* result without changing the harness, drop in real
per-arm study logs + reworded-question attempts (same schema as
`speedrun/ai/paraphrase`). The mechanism sources (interleaving meta-analysis,
retrieval-practice, Barnett & Ceci far-transfer taxonomy) are in
[`../evidence.md`](../evidence.md) and the Brainlift.
