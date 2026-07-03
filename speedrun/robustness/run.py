"""One-command runner for the adversarial-robustness checks (spec section 10).

    python -m speedrun.robustness.run all         # run all three, write reports
    python -m speedrun.robustness.run selftest    # deterministic correctness
    python -m speedrun.robustness.run contradictions|rushed|sync [--collection P]

Each check reads any Anki collection READ-ONLY and falls back to a synthetic
self-test dataset, so this always produces real, deterministic output.
"""

from __future__ import annotations

import argparse
from typing import List, Optional

from . import _common as C
from . import contradictions as contra
from . import rushed_reviews as rushed
from . import sync_robustness as sync


def _all(collection: Optional[str]) -> int:
    c = contra.run(collection)
    r = rushed.run(collection)
    s = sync.run()
    print("contradictions: {} flagged (scanned {})".format(
        c["contradictions"], c["scanned"]))
    print("rushed: {}/{} graded reviews too fast; honest={}".format(
        r["rushed_reviews"], r["graded_reviews"], r["honest_graded_reviews"]))
    print("sync: {} distinct reviews, no loss/dup under skew+interrupt = {}".format(
        s["distinct_reviews"], s["no_lost_or_double_counted"]))
    print("reports -> {}".format(C.ARTIFACTS))
    return 0


def _selftest() -> int:
    ok = contra._selftest() and rushed._selftest() and sync._selftest()
    print("robustness selftest: {}".format("ALL PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="MCAT robustness checks (section 10)")
    ap.add_argument("cmd", nargs="?", default="all",
                    choices=["all", "selftest", "contradictions", "rushed", "sync"])
    ap.add_argument("--collection", default=None)
    args = ap.parse_args(argv)

    if args.cmd == "all":
        return _all(args.collection)
    if args.cmd == "selftest":
        return _selftest()
    if args.cmd == "contradictions":
        return contra.main(["--collection", args.collection] if args.collection else [])
    if args.cmd == "rushed":
        return rushed.main(["--collection", args.collection] if args.collection else [])
    if args.cmd == "sync":
        return sync.main([])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
