"""CLI entrypoint for the Speedrun MCAT AI subsystem.

    python -m speedrun.ai.run [generate|check|eval|baselines|leakage|paraphrase|all]

`all` runs everything EXCEPT live generation (it uses the cached/sample
artifacts) and writes markdown reports to ``artifacts/report_*.md`` plus a
top-level ``artifacts/SUMMARY.md``. This is the "eval runs before any student
sees a card, and it works with the AI off" proof.
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import List

from . import baselines as baselines_mod
from . import checker as checker_mod
from . import config
from . import eval as eval_mod
from . import garbled_test as garbled_mod
from . import generator as generator_mod
from . import items as items_mod
from . import leakage as leakage_mod
from . import paraphrase_test as paraphrase_mod
from .sources import index_by_id, load_sources


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )


def _write(path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _artifact_tag() -> str:
    return "SAMPLE cached" if items_mod.is_sample_generated() else "cached/live"


# --------------------------------------------------------------------------
# generate
# --------------------------------------------------------------------------
def cmd_generate(args: argparse.Namespace) -> int:
    items = generator_mod.generate(n_per_source=args.n_per_source)
    print("generate: {} item(s) available (source: {}).".format(len(items), _artifact_tag()))
    return 0


# --------------------------------------------------------------------------
# check (gate + 7f gold-set three counts)
# --------------------------------------------------------------------------
def cmd_check(args: argparse.Namespace) -> checker_mod.GoldReport:
    units = load_sources()
    sources_by_id = index_by_id(units)
    gold = items_mod.load_gold()
    items = items_mod.load_generated()

    report = checker_mod.gold_set_report(items, sources_by_id, gold)

    lines: List[str] = []
    lines.append("# Checker report (pre-ship gate + 7f gold-set counts)\n")
    lines.append("Artifact source: **{}** ({} items).\n".format(_artifact_tag(), len(items)))
    lines.append("## Declared cutoffs (before results)\n")
    lines.append("- min grounding score: `{}`".format(config.MIN_GROUNDING_SCORE))
    lines.append("- max transfer similarity (copy threshold): `{}`".format(config.MAX_TRANSFER_SIMILARITY))
    lines.append("- choices required: `{}`".format(config.MIN_CHOICES))
    lines.append("- gold-set min pass rate: `{}`\n".format(config.GOLD_MIN_PASS_RATE))

    lines.append("## Three counts (7f)\n")
    lines.append("| Count | Meaning | N |")
    lines.append("| --- | --- | ---: |")
    lines.append("| 1. correct + useful | ships to students | {} |".format(report.correct_useful))
    lines.append("| 2. wrong (a wrong fact) | BLOCKED (worse than no card) | {} |".format(report.wrong))
    lines.append("| 3. correct-but-bad-teaching | BLOCKED (vague/trivial/dup/ungrounded) | {} |".format(report.correct_bad_teaching))
    lines.append("| total generated | | {} |".format(report.total))
    lines.append("")
    lines.append("Pass rate (correct+useful / total): **{:.1%}** "
                 "(cutoff {:.0%}) -> **{}**\n".format(
                     report.pass_rate, config.GOLD_MIN_PASS_RATE,
                     "MEETS CUTOFF" if report.meets_cutoff else "BELOW CUTOFF"))
    lines.append("Blocked (not shown to students): **{}**\n".format(report.blocked))

    lines.append("## Blocked items\n")
    any_blocked = False
    for row in report.rows:
        if row["category"] != "correct_useful":
            any_blocked = True
            lines.append("- `{}` ({}) [{}]: {}".format(
                row["item_id"], row["source_id"], row["category"],
                "; ".join(row["reasons"]) or row["verdict"]))
    if not any_blocked:
        lines.append("_(none)_")
    lines.append("")

    _write(config.ARTIFACTS_DIR / "report_check.md", "\n".join(lines))
    print("check: correct+useful={} wrong={} bad_teaching={} (pass_rate={:.1%}, {})".format(
        report.correct_useful, report.wrong, report.correct_bad_teaching,
        report.pass_rate, "MEETS" if report.meets_cutoff else "BELOW"))
    return report


# --------------------------------------------------------------------------
# eval
# --------------------------------------------------------------------------
def cmd_eval(args: argparse.Namespace) -> eval_mod.EvalResult:
    res = eval_mod.run_eval()
    lines: List[str] = []
    lines.append("# Held-out eval report\n")
    lines.append("Artifact source: **{}**.\n".format(_artifact_tag()))
    lines.append("## Declared cutoffs (before results)\n")
    lines.append("- min accuracy: `{}`".format(config.EVAL_MIN_ACCURACY))
    lines.append("- max wrong-answer rate: `{}`".format(config.EVAL_MAX_WRONG_RATE))
    lines.append("- held-out fraction: `{}` (seed `{}`)\n".format(
        config.EVAL_HELDOUT_FRACTION, config.EVAL_SPLIT_SEED))
    lines.append("## Results\n")
    lines.append("- held-out gold items: **{}**".format(res.heldout_size))
    lines.append("- evaluable generated cards: **{}**".format(res.n_evaluable))
    lines.append("- correct: **{}**, wrong: **{}**, unverifiable: **{}**".format(
        res.correct, res.wrong, res.unverifiable))
    lines.append("- accuracy: **{:.1%}** (cutoff {:.0%}) -> {}".format(
        res.accuracy, config.EVAL_MIN_ACCURACY,
        "PASS" if res.meets_accuracy else "FAIL"))
    lines.append("- wrong-answer rate: **{:.1%}** (ceiling {:.0%}) -> {}".format(
        res.wrong_rate, config.EVAL_MAX_WRONG_RATE,
        "PASS" if res.meets_wrong_rate else "FAIL"))
    lines.append("\n**Overall: {}**\n".format("PASS" if res.passed else "FAIL"))
    _write(config.ARTIFACTS_DIR / "report_eval.md", "\n".join(lines))
    print("eval: accuracy={:.1%} wrong_rate={:.1%} -> {}".format(
        res.accuracy, res.wrong_rate, "PASS" if res.passed else "FAIL"))
    return res


# --------------------------------------------------------------------------
# baselines
# --------------------------------------------------------------------------
def _metrics_table(comparison: baselines_mod.BaselineComparison) -> List[str]:
    cols = ["method", "n", "pass_rate", "grounded_rate", "transfer_ok_rate",
            "wellformed_rate", "wrong_fact_rate", "mean_grounding", "mean_transfer_sim"]
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for m in comparison.metrics:
        d = m.to_dict()
        lines.append("| " + " | ".join(str(d[c]) for c in cols) + " |")
    return lines


def cmd_baselines(args: argparse.Namespace) -> baselines_mod.BaselineComparison:
    comparison = baselines_mod.run_baselines()
    lines: List[str] = []
    lines.append("# Baselines: AI vs simpler methods (same checker)\n")
    lines.append("Backends actually used -> TF-IDF: `{}`, vector: `{}`.\n".format(
        comparison.backends.get("tfidf"), comparison.backends.get("vector")))
    lines.extend(_metrics_table(comparison))
    lines.append("")
    for name, beats in comparison.ai_beats.items():
        lines.append("- AI beats `{}` on pass rate: **{}**".format(name, beats))
    lines.append("")
    _write(config.ARTIFACTS_DIR / "report_baselines.md", "\n".join(lines))
    print("baselines: " + ", ".join(
        "{}={:.0%}".format(m.method, m.pass_rate) for m in comparison.metrics))
    return comparison


# --------------------------------------------------------------------------
# leakage
# --------------------------------------------------------------------------
def cmd_leakage(args: argparse.Namespace) -> leakage_mod.LeakageReport:
    report = leakage_mod.run_leakage()
    lines: List[str] = []
    lines.append("# Leakage report (7e)\n")
    lines.append("Scans generator inputs (prompt + few-shot) and generated items "
                 "against the held-out test set.\n")
    lines.append("- held-out test items: **{}**".format(report.n_test_items))
    lines.append("- candidates scanned: **{}**".format(report.n_candidates_scanned))
    lines.append("- n-gram size: `{}`, max overlap: `{}`".format(
        config.LEAKAGE_NGRAM_N, config.LEAKAGE_MAX_OVERLAP))
    lines.append("\n**Result: {}**\n".format("CLEAN" if report.clean else "DIRTY -- LEAK FOUND"))
    if report.flags:
        lines.append("## Flags\n")
        for f in report.flags:
            d = f.to_dict()
            lines.append("- [{}] `{}` ~ test `{}` ({}, overlap={})".format(
                d["scope"], d["candidate_ref"], d["test_id"], d["kind"], d["overlap"]))
    _write(config.ARTIFACTS_DIR / "report_leakage.md", "\n".join(lines))
    print("leakage: {} ({} flags)".format(
        "CLEAN" if report.clean else "DIRTY", len(report.flags)))
    return report


# --------------------------------------------------------------------------
# paraphrase / transfer factor
# --------------------------------------------------------------------------
def cmd_paraphrase(args: argparse.Namespace) -> paraphrase_mod.TransferFactor:
    tf = paraphrase_mod.write_transfer_factor()
    lines: List[str] = []
    lines.append("# Paraphrase test / transfer factor (7d)\n")
    lines.append("30 cards x 2 reworded exam-style questions. We compare recall on "
                 "the card vs accuracy on the reworded questions; the **gap** is the "
                 "memory->performance bridge.\n")
    lines.append("Attempts source: **{}** (measured={}).\n".format(tf.source, tf.measured))
    lines.append("transfer_factor = transfer_accuracy / recall_mean; "
                 "gap = recall_mean - transfer_accuracy\n")
    lines.append("- cards with attempts: **{}**, reworded attempts: **{}**".format(
        tf.n_cards, tf.n))
    lines.append("- recall on the card: **{:.1%}**".format(tf.assumed_recall))
    lines.append("- accuracy on reworded questions: **{:.1%}**".format(tf.transfer_accuracy))
    lines.append("- **gap (recall - reworded): {:.1%}**".format(tf.gap))
    lines.append("- **transfer factor: {:.3f}** (95% CI [{:.3f}, {:.3f}], n={})\n".format(
        tf.factor, tf.lower, tf.upper, tf.n))
    if tf.measured:
        lines.append("Set Anki config key `{}` = `{:.4f}` so the Rust performance "
                     "engine uses this measured bridge instead of 1.0.\n".format(
                         tf.config_key, tf.factor))
    else:
        lines.append("_measured=false (illustrative/synthetic or no attempts): do "
                     "**not** set `{}` from this run. Provide real attempts in "
                     "`paraphrase/attempts.json` for a measured factor._\n".format(
                         tf.config_key))
    lines.append("Written to `{}` and `{}`.\n".format(
        config.TRANSFER_FACTOR_PATH.name, "mcat_transfer_factor.json"))
    _write(config.ARTIFACTS_DIR / "report_paraphrase.md", "\n".join(lines))
    print("paraphrase: recall={:.1%} reworded={:.1%} gap={:.1%} factor={:.3f} "
          "(measured={})".format(
              tf.assumed_recall, tf.transfer_accuracy, tf.gap, tf.factor, tf.measured))
    return tf


# --------------------------------------------------------------------------
# all
# --------------------------------------------------------------------------
def cmd_all(args: argparse.Namespace) -> int:
    check_report = cmd_check(args)
    eval_res = cmd_eval(args)
    comparison = cmd_baselines(args)
    leak = cmd_leakage(args)
    tf = cmd_paraphrase(args)

    lines: List[str] = []
    lines.append("# Speedrun MCAT AI -- SUMMARY\n")
    lines.append("_Generated by `python -m speedrun.ai.run all`. Artifact source: "
                 "**{}** (runs with the AI off, before any student sees a card)._\n".format(
                     _artifact_tag()))

    lines.append("## Eval (held-out)\n")
    lines.append("- accuracy: **{:.1%}** (cutoff {:.0%}) -> **{}**".format(
        eval_res.accuracy, config.EVAL_MIN_ACCURACY,
        "PASS" if eval_res.meets_accuracy else "FAIL"))
    lines.append("- wrong-answer rate: **{:.1%}** (ceiling {:.0%}) -> **{}**".format(
        eval_res.wrong_rate, config.EVAL_MAX_WRONG_RATE,
        "PASS" if eval_res.meets_wrong_rate else "FAIL"))
    lines.append("- evaluable cards: {} / held-out gold: {}".format(
        eval_res.n_evaluable, eval_res.heldout_size))
    lines.append("- **overall eval: {}**\n".format("PASS" if eval_res.passed else "FAIL"))

    lines.append("## Gold-set three counts (7f)\n")
    lines.append("| Count | N |")
    lines.append("| --- | ---: |")
    lines.append("| 1. correct + useful (ships) | {} |".format(check_report.correct_useful))
    lines.append("| 2. wrong fact (blocked) | {} |".format(check_report.wrong))
    lines.append("| 3. correct-but-bad-teaching (blocked) | {} |".format(check_report.correct_bad_teaching))
    lines.append("| total | {} |".format(check_report.total))
    lines.append("")
    lines.append("Pass rate **{:.1%}** (cutoff {:.0%}) -> **{}**\n".format(
        check_report.pass_rate, config.GOLD_MIN_PASS_RATE,
        "MEETS CUTOFF" if check_report.meets_cutoff else "BELOW CUTOFF"))

    lines.append("## Baselines side-by-side (same checker)\n")
    lines.append("Backends -> TF-IDF: `{}`, vector: `{}`.\n".format(
        comparison.backends.get("tfidf"), comparison.backends.get("vector")))
    lines.extend(_metrics_table(comparison))
    lines.append("")
    for name, beats in comparison.ai_beats.items():
        lines.append("- AI beats `{}` on pass rate: **{}**".format(name, beats))
    lines.append("")

    lines.append("## Leakage (7e)\n")
    lines.append("- **{}** ({} flags over {} candidates vs {} held-out items)\n".format(
        "CLEAN" if leak.clean else "DIRTY", len(leak.flags),
        leak.n_candidates_scanned, leak.n_test_items))

    lines.append("## Paraphrase gap / transfer factor (7d)\n")
    lines.append("- recall on card **{:.1%}** vs reworded accuracy **{:.1%}** -> "
                 "**gap {:.1%}**".format(tf.assumed_recall, tf.transfer_accuracy, tf.gap))
    lines.append("- **transfer factor {:.3f}** (95% CI [{:.3f}, {:.3f}], n={}), "
                 "measured={}".format(tf.factor, tf.lower, tf.upper, tf.n, tf.measured))
    if tf.measured:
        lines.append("- set Anki config key `{}` = `{:.4f}`\n".format(tf.config_key, tf.factor))
    else:
        lines.append("- _measured=false: illustrative only; do not set the engine "
                     "config from this run_\n")

    all_pass = (eval_res.passed and check_report.meets_cutoff and leak.clean
                and all(comparison.ai_beats.values()))
    lines.append("## Bottom line\n")
    lines.append("**{}** -- eval {}, gold-set {}, leakage {}, AI beats baselines {}.\n".format(
        "READY (all gates green)" if all_pass else "NOT READY (a gate is red)",
        "PASS" if eval_res.passed else "FAIL",
        "MEETS" if check_report.meets_cutoff else "BELOW",
        "CLEAN" if leak.clean else "DIRTY",
        "YES" if all(comparison.ai_beats.values()) else "NO"))

    _write(config.SUMMARY_PATH, "\n".join(lines))
    print("\nSUMMARY written to {}".format(config.SUMMARY_PATH))
    return 0


def cmd_garbled(args: argparse.Namespace) -> int:
    return garbled_mod.main()


COMMANDS = {
    "generate": cmd_generate,
    "check": cmd_check,
    "eval": cmd_eval,
    "baselines": cmd_baselines,
    "leakage": cmd_leakage,
    "paraphrase": cmd_paraphrase,
    "garbled": cmd_garbled,
    "all": cmd_all,
}


def main(argv: "list[str] | None" = None) -> int:
    _setup_logging()
    parser = argparse.ArgumentParser(
        prog="python -m speedrun.ai.run",
        description="Speedrun MCAT AI: transfer-question generator + gates.",
    )
    parser.add_argument("command", choices=sorted(COMMANDS.keys()), help="step to run")
    parser.add_argument("--n-per-source", type=int, default=1,
                        help="questions to generate per source (generate only)")
    args = parser.parse_args(argv)
    fn = COMMANDS[args.command]
    result = fn(args)
    if isinstance(result, int):
        return result
    return 0


if __name__ == "__main__":
    sys.exit(main())
