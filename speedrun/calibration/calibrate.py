"""Memory-model calibration -- spec section 9, step 1 (required).

Claim being tested: *when the memory model says 80%, the student recalls about
80% of the time.* We test that on **held-out reviews** and report a **reliability
curve + Brier score + log loss** (and Expected Calibration Error).

What the "memory model" predicts. Memory here is FSRS retrievability: the chance a
card is recalled now. FSRS uses a fixed forgetting curve

    R(t) = (1 + FACTOR * t / S) ** DECAY,   FACTOR = 19/81, DECAY = -0.5

where `t` is days since the last review and `S` (stability) is the interval that
was scheduled at the previous review (by construction the time at which R = 0.9).
So for every real review in the log we can reconstruct the model's predicted
recall at that moment from the *previous* review's interval and the actual elapsed
time -- no parameters are fit on these outcomes, so this is a genuine held-out
check of the model's predictions against what the student actually did.

    predicted R = curve(elapsed_days, S = previous interval)
    outcome     = 1 if the review was graded pass (ease >= 2), else 0 ("Again")

Design constraints (same as the other speedrun checks):
* standard library only -- no numpy/matplotlib; the reliability diagram is written
  as a plain SVG;
* the Anki collection is opened READ-ONLY, never disturbing a running Anki, and is
  never required -- with no usable revlog we fall back to a synthetic, correctly
  specified review stream so the pipeline (and its metrics) still runs and can be
  validated for correctness.

Usage (from repo root):
    python -m speedrun.calibration.calibrate [--collection PATH]
    python -m speedrun.calibration.calibrate selftest
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
ARTIFACTS = HERE / "artifacts"

# FSRS-4.5+ forgetting curve constants.
FACTOR = 19.0 / 81.0
DECAY = -0.5
N_BINS = 10
_EPS = 1e-6
DEFAULT_SEED = 20260703

# A (predicted_recall, outcome) sample. outcome is 1 for pass, 0 for "Again".
Sample = Tuple[float, int]


# --------------------------------------------------------------------------
# The forgetting curve (the model's prediction)
# --------------------------------------------------------------------------
def predicted_recall(elapsed_days: float, stability_days: float) -> float:
    if stability_days <= 0:
        return 0.0
    r = (1.0 + FACTOR * elapsed_days / stability_days) ** DECAY
    return min(1.0 - _EPS, max(_EPS, r))


# --------------------------------------------------------------------------
# Collection discovery + read-only revlog extraction
# --------------------------------------------------------------------------
def _collection_candidates() -> List[Path]:
    out: List[Path] = []
    roots: List[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        roots.append(Path(appdata) / "Anki2")
    home = Path.home()
    roots.append(home / ".local" / "share" / "Anki2")
    roots.append(home / "Library" / "Application Support" / "Anki2")
    for root in roots:
        try:
            if not root.exists():
                continue
            for profile in sorted(root.iterdir()):
                col = profile / "collection.anki2"
                if col.is_file():
                    out.append(col)
        except OSError:
            continue
    return out


def _resolve_collection(explicit: Optional[str]) -> Optional[Path]:
    if explicit:
        p = Path(explicit)
        return p if p.is_file() else None
    cands = _collection_candidates()
    return cands[0] if cands else None


def _open_ro(col_path: Path) -> sqlite3.Connection:
    uri = "file:{}?mode=ro&immutable=1".format(col_path.as_posix())
    return sqlite3.connect(uri, uri=True)


def samples_from_collection(col_path: Path) -> List[Sample]:
    """Reconstruct (predicted recall, outcome) for each real review by walking the
    revlog per card: stability = the previous review's interval, elapsed = wall
    time between the two reviews. Learning steps (sub-day / no prior interval) are
    skipped so we only score genuine memory predictions."""
    con = _open_ro(col_path)
    samples: List[Sample] = []
    try:
        rows = con.execute(
            "select cid, id, ease, ivl, lastIvl, type from revlog order by cid, id"
        ).fetchall()
    except sqlite3.Error:
        return samples
    finally:
        con.close()

    prev_id: Optional[int] = None
    prev_ivl: Optional[int] = None
    prev_cid: Optional[int] = None
    for cid, rid, ease, ivl, _last_ivl, rtype in rows:
        if cid != prev_cid:
            prev_id = None
            prev_ivl = None
            prev_cid = cid
        # Score this review against the state the PREVIOUS review left behind.
        if (
            prev_id is not None
            and prev_ivl is not None
            and prev_ivl >= 1  # previous interval was a real (>=1 day) schedule
            and ease in (1, 2, 3, 4)
            and rtype in (0, 1, 2)  # learn / review / relearn (exclude cram/manual)
        ):
            elapsed_days = (rid - prev_id) / 86_400_000.0
            if elapsed_days > 0:
                pr = predicted_recall(elapsed_days, float(prev_ivl))
                outcome = 1 if ease >= 2 else 0
                samples.append((pr, outcome))
        prev_id = rid
        # A positive ivl means the review left a >=1 day schedule to test next time.
        prev_ivl = ivl if ivl and ivl >= 1 else None
    return samples


def synthetic_samples(n: int = 4000, seed: int = DEFAULT_SEED) -> List[Sample]:
    """Correctly-specified synthetic reviews: draw a stability and an elapsed time,
    compute the model's predicted recall, then draw the outcome from exactly that
    probability. A calibrated pipeline must recover low ECE / a diagonal curve on
    this stream -- it validates the metrics, not the app."""
    rng = random.Random(seed)
    out: List[Sample] = []
    for _ in range(n):
        stability = math.exp(rng.uniform(math.log(1.0), math.log(120.0)))  # 1..120d
        # elapsed spans well before to long after the schedule, so predicted recall
        # covers the full [~0.3, ~0.99] range and exercises every reliability bin.
        multiple = math.exp(rng.uniform(math.log(0.1), math.log(40.0)))
        elapsed = stability * multiple
        pr = predicted_recall(elapsed, stability)
        outcome = 1 if rng.random() < pr else 0
        out.append((pr, outcome))
    return out


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------
def brier_score(samples: List[Sample]) -> float:
    return sum((p - y) ** 2 for p, y in samples) / len(samples)


def log_loss(samples: List[Sample]) -> float:
    total = 0.0
    for p, y in samples:
        p = min(1.0 - _EPS, max(_EPS, p))
        total += -(y * math.log(p) + (1 - y) * math.log(1.0 - p))
    return total / len(samples)


def reliability_bins(samples: List[Sample], n_bins: int = N_BINS) -> List[Dict[str, float]]:
    bins: List[Dict[str, float]] = []
    for b in range(n_bins):
        lo = b / n_bins
        hi = (b + 1) / n_bins
        chosen = [
            (p, y)
            for p, y in samples
            if (p >= lo and (p < hi or (b == n_bins - 1 and p <= hi)))
        ]
        n = len(chosen)
        bins.append(
            {
                "lo": lo,
                "hi": hi,
                "n": n,
                "confidence": (sum(p for p, _ in chosen) / n) if n else 0.0,
                "observed": (sum(y for _, y in chosen) / n) if n else 0.0,
            }
        )
    return bins


def expected_calibration_error(bins: List[Dict[str, float]], total: int) -> float:
    if total == 0:
        return 0.0
    return sum(
        (b["n"] / total) * abs(b["observed"] - b["confidence"]) for b in bins if b["n"]
    )


# --------------------------------------------------------------------------
# SVG reliability diagram (no third-party deps)
# --------------------------------------------------------------------------
def _svg_reliability(bins: List[Dict[str, float]], out_path: Path) -> None:
    W = H = 320
    pad = 40
    plot = W - 2 * pad

    def X(v: float) -> float:
        return pad + v * plot

    def Y(v: float) -> float:
        return H - pad - v * plot

    parts: List[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="{}" height="{}" '
        'font-family="sans-serif" font-size="11">'.format(W, H),
        '<rect width="{}" height="{}" fill="white"/>'.format(W, H),
        # axes
        '<line x1="{}" y1="{}" x2="{}" y2="{}" stroke="#333"/>'.format(
            pad, H - pad, W - pad, H - pad
        ),
        '<line x1="{}" y1="{}" x2="{}" y2="{}" stroke="#333"/>'.format(
            pad, H - pad, pad, pad
        ),
        # perfect-calibration diagonal
        '<line x1="{}" y1="{}" x2="{}" y2="{}" stroke="#bbb" '
        'stroke-dasharray="4 3"/>'.format(X(0), Y(0), X(1), Y(1)),
        '<text x="{}" y="{}" text-anchor="middle">predicted recall</text>'.format(
            W / 2, H - 8
        ),
        '<text x="14" y="{}" transform="rotate(-90 14 {})" '
        'text-anchor="middle">observed recall</text>'.format(H / 2, H / 2),
    ]
    # the reliability polyline over non-empty bins
    pts = [(b["confidence"], b["observed"]) for b in bins if b["n"]]
    if len(pts) >= 2:
        poly = " ".join("{:.1f},{:.1f}".format(X(px), Y(py)) for px, py in pts)
        parts.append(
            '<polyline points="{}" fill="none" stroke="#1a7f37" '
            'stroke-width="2"/>'.format(poly)
        )
    for px, py in pts:
        parts.append(
            '<circle cx="{:.1f}" cy="{:.1f}" r="3" fill="#1a7f37"/>'.format(X(px), Y(py))
        )
    parts.append("</svg>")
    out_path.write_text("\n".join(parts), encoding="utf-8")


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------
def _grade(brier: float, ece: float) -> str:
    if brier <= 0.18 and ece <= 0.06:
        return "WELL CALIBRATED"
    if brier <= 0.25 and ece <= 0.12:
        return "REASONABLY CALIBRATED"
    return "MISCALIBRATED (reported honestly)"


def build_report(samples: List[Sample], source: str, synthetic: bool) -> Dict[str, object]:
    bins = reliability_bins(samples)
    total = len(samples)
    result = {
        "source": source,
        "synthetic": synthetic,
        "n_reviews": total,
        "brier": brier_score(samples),
        "log_loss": log_loss(samples),
        "ece": expected_calibration_error(bins, total),
        "base_rate": sum(y for _, y in samples) / total,
        "mean_predicted": sum(p for p, _ in samples) / total,
        "bins": bins,
    }
    result["verdict"] = _grade(float(result["brier"]), float(result["ece"]))
    return result


def _write_reports(res: Dict[str, object]) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "calibration.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    _svg_reliability(res["bins"], ARTIFACTS / "reliability.svg")  # type: ignore[arg-type]

    if res["synthetic"]:
        found = res.get("real_reviews_found")
        why = ""
        if found is not None:
            why = (
                " The harness scanned the real collection and found only **{}** "
                "genuine cross-day review predictions (the deck has been studied "
                "same-day only, with no multi-day recall history yet), so there is "
                "nothing real to calibrate on. This is a data limitation, reported "
                "honestly — the number below comes from a synthetic stream.".format(found)
            )
        note = (
            "**SYNTHETIC fallback.**" + why + " This validates the calibration "
            "*pipeline* on a correctly-specified review stream; the moment the deck "
            "has multi-day review history, `--collection PATH` yields a real-data "
            "result with no code change."
        )
    else:
        note = "Real reviews from the collection's `revlog`, opened read-only."

    lines = [
        "# Memory-model calibration (section 9, step 1)",
        "",
        "**Claim:** when the memory model says X%, the student recalls ~X%.",
        "",
        "Source: " + note,
        "",
        "Predicted recall is the FSRS forgetting curve "
        "`R = (1 + (19/81)·t/S)^(-1/2)` with `S` = the previous review's scheduled "
        "interval and `t` = actual elapsed time. No parameters are fit on these "
        "outcomes, so this is a held-out check of the model's predictions.",
        "",
        "## Scores (held-out reviews)",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        "| Reviews scored | {} |".format(res["n_reviews"]),
        "| **Brier score** (lower is better; 0 = perfect) | **{:.4f}** |".format(res["brier"]),
        "| **Log loss** (lower is better) | **{:.4f}** |".format(res["log_loss"]),
        "| Expected Calibration Error (ECE) | {:.4f} |".format(res["ece"]),
        "| Observed base recall rate | {:.1%} |".format(res["base_rate"]),
        "| Mean predicted recall | {:.1%} |".format(res["mean_predicted"]),
        "",
        "**Verdict: {}.**".format(res["verdict"]),
        "",
        "Reference points: predicting the base rate for every card gives a Brier of "
        "{:.4f}; a coin flip (0.5) gives 0.25. Lower than the base-rate line means the "
        "per-card predictions carry real information.".format(
            float(res["base_rate"]) * (1 - float(res["base_rate"]))
        ),
        "",
        "## Reliability table",
        "",
        "| predicted bin | n | mean predicted | observed recall | gap |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for b in res["bins"]:  # type: ignore[assignment]
        if not b["n"]:
            continue
        lines.append(
            "| {:.1f}–{:.1f} | {} | {:.1%} | {:.1%} | {:+.1%} |".format(
                b["lo"], b["hi"], int(b["n"]), b["confidence"], b["observed"],
                b["observed"] - b["confidence"],
            )
        )
    lines += [
        "",
        "Reliability diagram: [`reliability.svg`](reliability.svg) — points on the "
        "dashed diagonal mean predicted = observed (perfect calibration).",
        "",
        "## Honesty",
        "",
        "- Because memory recall comes straight from FSRS, this is a check of **FSRS "
        "calibration on this deck**, reported as-is — we don't tune the curve to make "
        "it look better.",
        "- The forgetting curve assumes the scheduled interval targeted 90% retention "
        "(Anki's default). Cards reviewed far off schedule and relearns are the main "
        "sources of residual error; they are kept, not filtered, so the numbers are "
        "honest.",
        "",
        "## Reproduce",
        "",
        "```bash",
        "python -m speedrun.calibration.calibrate                 # auto-detects a collection",
        "python -m speedrun.calibration.calibrate --collection PATH\\collection.anki2",
        "python -m speedrun.calibration.calibrate selftest",
        "```",
    ]
    (ARTIFACTS / "report_calibration.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# Selftest
# --------------------------------------------------------------------------
def _selftest() -> bool:
    ok = True

    # Perfect predictions -> Brier 0, log loss ~0.
    perfect: List[Sample] = [(1.0 - _EPS, 1), (_EPS, 0)] * 50
    b0 = brier_score(perfect)
    perfect_ok = b0 < 1e-4
    print("  perfect predictions -> Brier~0: {} ({:.5f})".format(
        "PASS" if perfect_ok else "FAIL", b0))
    ok = ok and perfect_ok

    # Correctly-specified synthetic stream -> low ECE (pipeline is calibrated).
    res = build_report(synthetic_samples(6000), "synthetic-selftest", True)
    ece_ok = float(res["ece"]) < 0.05
    print("  synthetic stream -> ECE < 0.05: {} ({:.4f})".format(
        "PASS" if ece_ok else "FAIL", res["ece"]))
    ok = ok and ece_ok

    # A biased model (always predict 0.99) must score WORSE (higher Brier) than the
    # calibrated one on the same outcomes -- the metric rewards honesty.
    base = synthetic_samples(4000)
    honest_b = brier_score(base)
    biased_b = brier_score([(0.99, y) for _, y in base])
    bias_ok = biased_b > honest_b
    print("  overconfident model scores worse: {} ({:.4f} > {:.4f})".format(
        "PASS" if bias_ok else "FAIL", biased_b, honest_b))
    ok = ok and bias_ok

    # Curve monotonicity: recall drops as elapsed grows.
    mono = predicted_recall(1, 10) > predicted_recall(20, 10)
    print("  forgetting curve is decreasing: {}".format("PASS" if mono else "FAIL"))
    ok = ok and mono

    print("calibration selftest: {}".format("ALL PASS" if ok else "FAIL"))
    return ok


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="MCAT memory-model calibration (section 9.1)")
    ap.add_argument("cmd", nargs="?", default="run", choices=["run", "selftest"])
    ap.add_argument("--collection", default=None)
    ap.add_argument("--min-reviews", type=int, default=50,
                    help="fall back to synthetic if fewer real reviews than this")
    args = ap.parse_args(argv)

    if args.cmd == "selftest":
        return 0 if _selftest() else 1

    col = _resolve_collection(args.collection)
    samples: List[Sample] = []
    source = "synthetic"
    synthetic = True
    real_found: Optional[int] = None
    if col is not None:
        samples = samples_from_collection(col)
        real_found = len(samples)
        if len(samples) >= args.min_reviews:
            source = str(col)
            synthetic = False
    if synthetic:
        samples = synthetic_samples()

    res = build_report(samples, source, synthetic)
    if synthetic and real_found is not None:
        res["real_reviews_found"] = real_found
    _write_reports(res)
    print("Calibration ({}{})".format(
        "SYNTHETIC " if synthetic else "", source))
    print("  n={}  Brier={:.4f}  log_loss={:.4f}  ECE={:.4f}  -> {}".format(
        res["n_reviews"], res["brier"], res["log_loss"], res["ece"], res["verdict"]))
    print("  reports -> {}".format(ARTIFACTS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
