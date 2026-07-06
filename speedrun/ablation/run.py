"""Study-feature ablation: interleaving (spec section 8).

Pre-registered hypothesis (stated before any result was computed):

    "Mixing related MCAT topics within a study session (interleaving) raises
     accuracy on new MIXED-TOPIC questions -- ones that require telling two
     confusable topics apart -- at the SAME study time, compared with studying
     one topic at a time (blocked)."

Primary metric (pre-registered): mean accuracy on a held-out set of mixed-topic
discrimination questions. Primary comparison: interleave ON minus interleave OFF,
PAIRED across the same simulated students (so the only thing that differs is the
study *order*, not the amount of study).

Three arms compared on the SAME questions with the SAME study budget (section 8):

  1. full      -- the app: weakness-targeted allocation + INTERLEAVED order.
  2. ablation  -- the app with the one feature OFF: same weakness-targeted
                  allocation, but BLOCKED order (interleaving removed).
  3. plain     -- plain Anki baseline: uniform position order, BLOCKED, no
                  weakness targeting.

Arms 1 and 2 study each topic the *identical* number of times, so their memory is
identical by construction; the ONLY difference between them is interleaved vs
blocked order. That isolates the feature (1 vs 2). Comparing 1 vs 3 shows whether
the whole app beats the obvious baseline at all.

HONESTY / WHY A SIMULATION. We cannot ethically gather real learners studying and
then sitting full-lengths in a one-week sprint (the brief says to grade the steps
honestly, not to fake a trial). So this is a transparent MECHANISM simulation, not
a human study, and it is labelled as such everywhere. Crucially the interleaving
benefit is NOT a hand-set "interleaving bonus": it emerges from a documented
mechanism -- discrimination between two confusable topics only strengthens when
the learner meets both topics close together in time, which interleaving produces
far more often than blocked study. Because the effect is emergent, the same model
also produces honest NULL results, which we report:

  * on a single-topic (memory-only) metric, interleaving shows ~0 effect;
  * when topics are not confusable, interleaving shows ~0 effect.

A fair test has to be able to fail. These null conditions are how this one can.

Mechanism sources (see speedrun/evidence.md / the Brainlift): interleaving aids
discrimination/transfer for confusable, complex material (interleaving
meta-analysis + systematic review); retrieval practice builds memory regardless
of order (Roediger & Karpicke); memory != performance (Barnett & Ceci far-transfer
taxonomy). The model encodes exactly those three claims and nothing more.

One command (stdlib only, deterministic):

    python -m speedrun.ablation.run            # run + write artifacts
    python -m speedrun.ablation.run selftest   # determinism + null checks
"""

from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path
from typing import Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
ARTIFACTS = HERE / "artifacts"

# --------------------------------------------------------------------------
# Pre-registered protocol (declared before results)
# --------------------------------------------------------------------------
HYPOTHESIS = (
    "Interleaving related MCAT topics within a session raises accuracy on new "
    "mixed-topic (confusable-pair) questions at equal study time, vs blocked study."
)
PRIMARY_METRIC = "mean accuracy on held-out mixed-topic discrimination questions"
PRIMARY_COMPARISON = "interleave ON minus interleave OFF, paired across students"
DIRECTION = "interleave ON > interleave OFF"
# Failure condition, pre-registered: if the paired 95% CI includes 0 (or is
# negative), we report the feature as NOT shown to help. That is a real result.

# --------------------------------------------------------------------------
# Model constants (fixed; the RNG only draws per-student latent traits)
# --------------------------------------------------------------------------
N_TOPICS = 8
# Confusable topic pairs (siblings). Mixed-topic questions live on these pairs.
PAIRS: List[Tuple[int, int]] = [(0, 1), (2, 3), (4, 5), (6, 7)]
STUDY_BUDGET = 320  # total study reps per arm (== "equal study time")
COOCCUR_WINDOW = 3  # two sibling-topic reps within this gap build discrimination
DEFAULT_SEED = 20260703
DEFAULT_STUDENTS = 300

_PAIR_OF: Dict[int, int] = {}
_SIBLING: Dict[int, int] = {}
for _pi, (_a, _b) in enumerate(PAIRS):
    _PAIR_OF[_a] = _pi
    _PAIR_OF[_b] = _pi
    _SIBLING[_a] = _b
    _SIBLING[_b] = _a


# --------------------------------------------------------------------------
# Study-order generation
# --------------------------------------------------------------------------
def blocked_sequence(reps: List[int]) -> List[int]:
    """All reps of topic 0, then all of topic 1, ... (studying one topic at a time)."""
    seq: List[int] = []
    for topic, n in enumerate(reps):
        seq.extend([topic] * n)
    return seq


def interleaved_sequence(reps: List[int]) -> List[int]:
    """Round-robin across topics that still have reps left (mix topics together)."""
    remaining = list(reps)
    seq: List[int] = []
    total = sum(remaining)
    while len(seq) < total:
        for topic in range(len(remaining)):
            if remaining[topic] > 0:
                seq.append(topic)
                remaining[topic] -= 1
    return seq


def cooccurrences(seq: List[int], window: int) -> Dict[int, int]:
    """Per pair, how many times a rep is preceded (within `window`) by its sibling
    topic -- the close-in-time cross-topic exposures that build discrimination."""
    counts: Dict[int, int] = {p: 0 for p in range(len(PAIRS))}
    for i, topic in enumerate(seq):
        sib = _SIBLING[topic]
        lo = max(0, i - window)
        if sib in seq[lo:i]:
            counts[_PAIR_OF[topic]] += 1
    return counts


# --------------------------------------------------------------------------
# Per-student latent traits and closed-form learning dynamics
# --------------------------------------------------------------------------
def _draw_student(rng: random.Random) -> Dict[str, object]:
    return {
        # starting memory per topic (weak, varied) -> drives weakness targeting
        "m0": [rng.uniform(0.05, 0.35) for _ in range(N_TOPICS)],
        # memory gain per retrieval rep (order-independent)
        "alpha_m": rng.uniform(0.15, 0.35),
        # discrimination gained just by MASTERING a topic (order-independent):
        # learning a topic's own features already helps reject a confusable
        # sibling somewhat, even under blocked study. Both app arms get this.
        "alpha_w": rng.uniform(0.015, 0.030),
        # EXTRA discrimination per close sibling co-occurrence -- the interleaving
        # mechanism, and the ONLY channel that differs between the arms. Small, so
        # interleaving adds a moderate bump on top of blocked mastery, not a cliff.
        "alpha_d": rng.uniform(0.020, 0.050),
        # chance of rejecting a distractor with zero trained discrimination
        "base_disc": rng.uniform(0.45, 0.60),
    }


def _allocate(m0: List[float], budget: int, weakness_targeted: bool) -> List[int]:
    """Split the study budget across topics. Weakness-targeted allocation gives
    weaker topics more reps; plain Anki spreads uniformly by position."""
    if weakness_targeted:
        weights = [1.0 - m for m in m0]
    else:
        weights = [1.0] * len(m0)
    total_w = sum(weights) or 1.0
    raw = [budget * w / total_w for w in weights]
    reps = [int(x) for x in raw]
    # hand out the remaining reps to the largest fractional parts (deterministic)
    leftover = budget - sum(reps)
    order = sorted(range(len(reps)), key=lambda i: raw[i] - reps[i], reverse=True)
    for i in range(leftover):
        reps[order[i % len(order)]] += 1
    return reps


def _memory_after(m0: List[float], reps: List[int], alpha_m: float) -> List[float]:
    # repeated m <- m + alpha*(1-m)  =>  1-m_k = (1-m0)*(1-alpha)^k
    return [1.0 - (1.0 - m0[t]) * (1.0 - alpha_m) ** reps[t] for t in range(len(m0))]


def _discrimination(
    reps: List[int], counts: Dict[int, int], alpha_w: float, alpha_d: float
) -> Dict[int, float]:
    """Two independent channels build pair discrimination:

    * within-topic mastery (order-independent) -- driven by how much the pair's
      two topics were studied at all; identical for the full and ablation arms.
    * cross-topic co-occurrence (order-dependent) -- the interleaving mechanism;
      the only channel that differs between arms.

    disc = 1 - (1-within)*(1-cross): each rep of either channel chips away at the
    remaining confusability.
    """
    disc: Dict[int, float] = {}
    for p, (a, b) in enumerate(PAIRS):
        within = 1.0 - (1.0 - alpha_w) ** (reps[a] + reps[b])
        cross = 1.0 - (1.0 - alpha_d) ** counts[p]
        disc[p] = 1.0 - (1.0 - within) * (1.0 - cross)
    return disc


def _mixed_topic_accuracy(
    memory: List[float], disc: Dict[int, float], base_disc: float, confusable: bool
) -> float:
    """Expected accuracy on mixed-topic questions: a question needs BOTH recall of
    the fact AND (for confusable pairs) discrimination to reject the sibling lure."""
    accs: List[float] = []
    for p, (a, b) in enumerate(PAIRS):
        if confusable:
            reject = base_disc + (1.0 - base_disc) * disc[p]
        else:
            reject = 1.0  # non-confusable: no lure, discrimination is irrelevant
        for t in (a, b):
            accs.append(memory[t] * reject)
    return sum(accs) / len(accs)


def _single_topic_accuracy(memory: List[float]) -> float:
    """Memory-only metric (no sibling lure). Order should NOT affect this."""
    return sum(memory) / len(memory)


# --------------------------------------------------------------------------
# One student, all three arms
# --------------------------------------------------------------------------
def _run_student(traits: Dict[str, object], confusable: bool = True) -> Dict[str, Dict[str, float]]:
    m0 = traits["m0"]  # type: ignore[assignment]
    alpha_m = float(traits["alpha_m"])
    alpha_w = float(traits["alpha_w"])
    alpha_d = float(traits["alpha_d"])
    base_disc = float(traits["base_disc"])

    reps_targeted = _allocate(m0, STUDY_BUDGET, weakness_targeted=True)  # arms 1 & 2
    reps_uniform = _allocate(m0, STUDY_BUDGET, weakness_targeted=False)  # arm 3

    arms_spec = {
        "full": (reps_targeted, interleaved_sequence(reps_targeted)),
        "ablation": (reps_targeted, blocked_sequence(reps_targeted)),
        "plain": (reps_uniform, blocked_sequence(reps_uniform)),
    }

    out: Dict[str, Dict[str, float]] = {}
    for arm, (reps, seq) in arms_spec.items():
        memory = _memory_after(m0, reps, alpha_m)
        disc = _discrimination(
            reps, cooccurrences(seq, COOCCUR_WINDOW), alpha_w, alpha_d
        )
        out[arm] = {
            "mixed": _mixed_topic_accuracy(memory, disc, base_disc, confusable),
            "single": _single_topic_accuracy(memory),
        }
    return out


# --------------------------------------------------------------------------
# Aggregation + paired statistics (stdlib only)
# --------------------------------------------------------------------------
def _mean(xs: List[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _paired_ci(diffs: List[float]) -> Tuple[float, float, float]:
    """Mean paired difference and a 95% normal-approx CI."""
    n = len(diffs)
    mean = _mean(diffs)
    if n < 2:
        return mean, mean, mean
    var = sum((d - mean) ** 2 for d in diffs) / (n - 1)
    se = math.sqrt(var / n)
    half = 1.96 * se
    return mean, mean - half, mean + half


def simulate(n_students: int, seed: int, confusable: bool = True) -> Dict[str, object]:
    rng = random.Random(seed)
    per_arm_mixed: Dict[str, List[float]] = {"full": [], "ablation": [], "plain": []}
    per_arm_single: Dict[str, List[float]] = {"full": [], "ablation": [], "plain": []}
    d_interleave_mixed: List[float] = []   # full - ablation (isolates the feature)
    d_wholeapp_mixed: List[float] = []      # full - plain   (whole app vs baseline)
    d_interleave_single: List[float] = []   # null metric: should be ~0

    for _ in range(n_students):
        traits = _draw_student(rng)
        r = _run_student(traits, confusable=confusable)
        for arm in per_arm_mixed:
            per_arm_mixed[arm].append(r[arm]["mixed"])
            per_arm_single[arm].append(r[arm]["single"])
        d_interleave_mixed.append(r["full"]["mixed"] - r["ablation"]["mixed"])
        d_wholeapp_mixed.append(r["full"]["mixed"] - r["plain"]["mixed"])
        d_interleave_single.append(r["full"]["single"] - r["ablation"]["single"])

    prim_mean, prim_lo, prim_hi = _paired_ci(d_interleave_mixed)
    whole_mean, whole_lo, whole_hi = _paired_ci(d_wholeapp_mixed)
    null_mean, null_lo, null_hi = _paired_ci(d_interleave_single)

    return {
        "n_students": n_students,
        "seed": seed,
        "confusable": confusable,
        "arms_mixed_mean": {a: _mean(v) for a, v in per_arm_mixed.items()},
        "arms_single_mean": {a: _mean(v) for a, v in per_arm_single.items()},
        "primary": {
            "comparison": PRIMARY_COMPARISON,
            "mean_diff": prim_mean,
            "ci95": [prim_lo, prim_hi],
            "significant": prim_lo > 0.0,
        },
        "secondary_whole_app_vs_plain": {
            "mean_diff": whole_mean,
            "ci95": [whole_lo, whole_hi],
            "significant": whole_lo > 0.0,
        },
        "null_single_topic": {
            "mean_diff": null_mean,
            "ci95": [null_lo, null_hi],
            "near_zero": abs(null_mean) < 1e-9,
        },
    }


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------
def _pct(x: float) -> str:
    return "{:.1f}%".format(100.0 * x)


def _pp(x: float) -> str:
    return "{:+.1f} pp".format(100.0 * x)


def _write_reports(main: Dict[str, object], null_cond: Dict[str, object]) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "ablation.json").write_text(
        json.dumps({"main": main, "non_confusable_sensitivity": null_cond}, indent=2),
        encoding="utf-8",
    )

    am = main["arms_mixed_mean"]  # type: ignore[index]
    asg = main["arms_single_mean"]  # type: ignore[index]
    prim = main["primary"]  # type: ignore[index]
    whole = main["secondary_whole_app_vs_plain"]  # type: ignore[index]
    null1 = main["null_single_topic"]  # type: ignore[index]
    nc = null_cond["primary"]  # type: ignore[index]

    verdict = (
        "SUPPORTED (paired 95% CI above 0)"
        if prim["significant"]
        else "NOT SHOWN (paired 95% CI includes 0)"
    )

    lines = [
        "# Study-feature ablation -- interleaving (section 8)",
        "",
        "**Feature under test:** interleaving related topics within a session.",
        "",
        "**Pre-registered hypothesis (stated before results):** " + HYPOTHESIS,
        "",
        "- **Primary metric:** " + PRIMARY_METRIC,
        "- **Primary comparison:** " + PRIMARY_COMPARISON + " (" + DIRECTION + ")",
        "- **Failure rule (pre-set):** if the paired 95% CI includes 0, the feature "
        "is reported as *not shown to help*.",
        "",
        "> **This is a transparent mechanism simulation, not a human study.** We do "
        "not have real learners + full-length scores in a one-week sprint, so we do "
        "not claim one. The interleaving benefit is *emergent* from a documented "
        "mechanism (discrimination between confusable topics only strengthens when "
        "both are met close together in time), not a hand-set bonus -- which is why "
        "the same model yields the honest null results below.",
        "",
        "## Setup",
        "",
        "| | |",
        "| --- | --- |",
        "| Simulated students | {} (seed {}) |".format(main["n_students"], main["seed"]),
        "| Topics / confusable pairs | {} / {} |".format(N_TOPICS, len(PAIRS)),
        "| Study budget per arm (equal study time) | {} reps |".format(STUDY_BUDGET),
        "| Co-occurrence window | {} |".format(COOCCUR_WINDOW),
        "",
        "Three arms, same questions, same budget:",
        "",
        "1. **full** = weakness-targeted allocation + **interleaved** order (the app).",
        "2. **ablation** = same allocation, **blocked** order (interleaving OFF).",
        "3. **plain** = uniform order, blocked, no weakness targeting (plain Anki).",
        "",
        "Arms 1 and 2 study each topic the identical number of times, so their memory "
        "is identical by construction -- the only difference is study *order*.",
        "",
        "## Results -- mixed-topic accuracy (primary metric)",
        "",
        "| Arm | mixed-topic accuracy |",
        "| --- | ---: |",
        "| full (interleave ON) | {} |".format(_pct(float(am["full"]))),
        "| ablation (interleave OFF) | {} |".format(_pct(float(am["ablation"]))),
        "| plain Anki | {} |".format(_pct(float(am["plain"]))),
        "",
        "**Primary (isolates the feature): interleave ON - interleave OFF = {}** "
        "(95% CI [{}, {}]) -> **{}**.".format(
            _pp(float(prim["mean_diff"])),
            _pp(float(prim["ci95"][0])),
            _pp(float(prim["ci95"][1])),
            verdict,
        ),
        "",
        "Secondary (whole app vs plain Anki): {} (95% CI [{}, {}]).".format(
            _pp(float(whole["mean_diff"])),
            _pp(float(whole["ci95"][0])),
            _pp(float(whole["ci95"][1])),
        ),
        "",
        "## Results that did NOT show an effect (honest null checks)",
        "",
        "A fair test has to be able to fail. Two conditions where interleaving should "
        "*not* help, and doesn't:",
        "",
        "1. **Single-topic (memory-only) metric.** Same students, same arms, but the "
        "questions carry no sibling lure. interleave ON - OFF = {} (95% CI [{}, {}]) "
        "-- ~0 by construction, because order doesn't change how much memory each "
        "topic got. Interleaving is not a free memory boost.".format(
            _pp(float(null1["mean_diff"])),
            _pp(float(null1["ci95"][0])),
            _pp(float(null1["ci95"][1])),
        ),
        "2. **Non-confusable topics.** Re-run with the topics made non-confusable "
        "(no distractor to reject): interleave ON - OFF on mixed questions = {} "
        "(95% CI [{}, {}]). With nothing to discriminate, interleaving buys nothing.".format(
            _pp(float(nc["mean_diff"])),
            _pp(float(nc["ci95"][0])),
            _pp(float(nc["ci95"][1])),
        ),
        "",
        "## What this does and does not prove",
        "",
        "- It **does** show the harness runs the required 3-way, equal-time comparison "
        "with a pre-registered metric and a failure rule, and that the interleaving "
        "effect is confined to exactly the case learning science predicts "
        "(confusable, transfer-style questions) and vanishes elsewhere.",
        "- It **does not** prove a real-world MCAT gain. The numbers come from a learner "
        "model, not students. Swapping in real per-arm study logs + reworded-question "
        "attempts (same schema as `speedrun/ai/paraphrase`) would turn this into a "
        "measured result without changing the harness.",
        "",
        "## Reproduce",
        "",
        "```bash",
        "python -m speedrun.ablation.run           # writes this report + ablation.json",
        "python -m speedrun.ablation.run selftest  # determinism + null-condition checks",
        "```",
    ]
    (ARTIFACTS / "report_ablation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# Selftest
# --------------------------------------------------------------------------
def _selftest() -> bool:
    ok = True

    # Determinism: same seed -> identical primary effect.
    a = simulate(60, DEFAULT_SEED)
    b = simulate(60, DEFAULT_SEED)
    det = a["primary"]["mean_diff"] == b["primary"]["mean_diff"]  # type: ignore[index]
    print("  determinism: {}".format("PASS" if det else "FAIL"))
    ok = ok and det

    # Mechanism: with confusable pairs, interleaving should help (positive, CI>0).
    helps = a["primary"]["significant"]  # type: ignore[index]
    print("  interleaving helps on confusable mixed questions: {}".format(
        "PASS" if helps else "FAIL"))
    ok = ok and bool(helps)

    # Null 1: single-topic (memory-only) effect is ~0.
    null_ok = a["null_single_topic"]["near_zero"]  # type: ignore[index]
    print("  null (single-topic memory) ~ 0: {}".format("PASS" if null_ok else "FAIL"))
    ok = ok and bool(null_ok)

    # Null 2: non-confusable topics -> effect ~0 (CI includes 0).
    nc = simulate(60, DEFAULT_SEED, confusable=False)
    nc_ok = not nc["primary"]["significant"]  # type: ignore[index]
    print("  null (non-confusable topics) not significant: {}".format(
        "PASS" if nc_ok else "FAIL"))
    ok = ok and bool(nc_ok)

    print("ablation selftest: {}".format("ALL PASS" if ok else "FAIL"))
    return ok


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="MCAT study-feature ablation (section 8)")
    ap.add_argument("cmd", nargs="?", default="run", choices=["run", "selftest"])
    ap.add_argument("--students", type=int, default=DEFAULT_STUDENTS)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = ap.parse_args(argv)

    if args.cmd == "selftest":
        return 0 if _selftest() else 1

    main_res = simulate(args.students, args.seed, confusable=True)
    null_cond = simulate(args.students, args.seed, confusable=False)
    _write_reports(main_res, null_cond)

    prim = main_res["primary"]  # type: ignore[index]
    print("Ablation (interleaving), {} students, seed {}".format(
        args.students, args.seed))
    print("  interleave ON - OFF (mixed-topic): {:+.1f} pp  CI95 [{:+.1f}, {:+.1f}]  {}".format(
        100 * float(prim["mean_diff"]),
        100 * float(prim["ci95"][0]),
        100 * float(prim["ci95"][1]),
        "SUPPORTED" if prim["significant"] else "NOT SHOWN",
    ))
    print("  reports -> {}".format(ARTIFACTS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
