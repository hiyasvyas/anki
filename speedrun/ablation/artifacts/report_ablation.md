# Study-feature ablation -- interleaving (section 8)

**Feature under test:** interleaving related topics within a session.

**Pre-registered hypothesis (stated before results):** Interleaving related MCAT topics within a session raises accuracy on new mixed-topic (confusable-pair) questions at equal study time, vs blocked study.

- **Primary metric:** mean accuracy on held-out mixed-topic discrimination questions
- **Primary comparison:** interleave ON minus interleave OFF, paired across students (interleave ON > interleave OFF)
- **Failure rule (pre-set):** if the paired 95% CI includes 0, the feature is reported as *not shown to help*.

> **This is a transparent mechanism simulation, not a human study.** We do not have real learners + full-length scores in a one-week sprint, so we do not claim one. The interleaving benefit is *emergent* from a documented mechanism (discrimination between confusable topics only strengthens when both are met close together in time), not a hand-set bonus -- which is why the same model yields the honest null results below.

## Setup

| | |
| --- | --- |
| Simulated students | 300 (seed 20260703) |
| Topics / confusable pairs | 8 / 4 |
| Study budget per arm (equal study time) | 320 reps |
| Co-occurrence window | 3 |

Three arms, same questions, same budget:

1. **full** = weakness-targeted allocation + **interleaved** order (the app).
2. **ablation** = same allocation, **blocked** order (interleaving OFF).
3. **plain** = uniform order, blocked, no weakness targeting (plain Anki).

Arms 1 and 2 study each topic the identical number of times, so their memory is identical by construction -- the only difference is study *order*.

## Results -- mixed-topic accuracy (primary metric)

| Arm | mixed-topic accuracy |
| --- | ---: |
| full (interleave ON) | 97.8% |
| ablation (interleave OFF) | 92.7% |
| plain Anki | 92.7% |

**Primary (isolates the feature): interleave ON - interleave OFF = +5.1 pp** (95% CI [+4.8 pp, +5.3 pp]) -> **SUPPORTED (paired 95% CI above 0)**.

Secondary (whole app vs plain Anki): +5.0 pp (95% CI [+4.8 pp, +5.3 pp]).

## Results that did NOT show an effect (honest null checks)

A fair test has to be able to fail. Two conditions where interleaving should *not* help, and doesn't:

1. **Single-topic (memory-only) metric.** Same students, same arms, but the questions carry no sibling lure. interleave ON - OFF = +0.0 pp (95% CI [+0.0 pp, +0.0 pp]) -- ~0 by construction, because order doesn't change how much memory each topic got. Interleaving is not a free memory boost.
2. **Non-confusable topics.** Re-run with the topics made non-confusable (no distractor to reject): interleave ON - OFF on mixed questions = +0.0 pp (95% CI [+0.0 pp, +0.0 pp]). With nothing to discriminate, interleaving buys nothing.

## What this does and does not prove

- It **does** show the harness runs the required 3-way, equal-time comparison with a pre-registered metric and a failure rule, and that the interleaving effect is confined to exactly the case learning science predicts (confusable, transfer-style questions) and vanishes elsewhere.
- It **does not** prove a real-world MCAT gain. The numbers come from a learner model, not students. Swapping in real per-arm study logs + reworded-question attempts (same schema as `speedrun/ai/paraphrase`) would turn this into a measured result without changing the harness.

## Reproduce

```bash
python -m speedrun.ablation.run           # writes this report + ablation.json
python -m speedrun.ablation.run selftest  # determinism + null-condition checks
```
