"""Central configuration for the Speedrun MCAT AI subsystem.

============================================================================
CUTOFFS DECLARED BEFORE LOOKING AT ANY RESULTS
============================================================================
Every threshold below was chosen and committed BEFORE running the checker,
eval, or gold-set counts on any generated data. They encode the grading rule
"a wrong fact is worse than no card": we would rather block a good card than
ship a wrong one. Do not tune these against results after the fact -- if you
change them, say so and re-declare.

The metrics they gate are defined in ``textsim.py``:

* grounding_score   -- overlap coefficient of the correct answer+rationale
                       content tokens against the cited source text (0..1).
                       "Is the answer actually supported by the named source?"
* transfer_sim      -- Jaccard similarity of the generated stem against the
                       source's own wording (0..1). LOW = reworded (transfer),
                       HIGH = near-copy (just memorized phrasing).
* leakage overlap   -- normalized n-gram overlap of an input/output item vs a
                       held-out test item (0..1).
============================================================================
"""

from __future__ import annotations

import os
from pathlib import Path

# --------------------------------------------------------------------------
# Provider / model
# --------------------------------------------------------------------------
# Current Claude model. Override with env var SPEEDRUN_AI_MODEL if a newer
# model is available. We never read or print the API key here; the generator
# reads ANTHROPIC_API_KEY from the environment only when it actually calls out.
DEFAULT_MODEL: str = os.environ.get("SPEEDRUN_AI_MODEL", "claude-3-5-sonnet-latest")
API_KEY_ENV: str = "ANTHROPIC_API_KEY"

# Optional free-tier provider: Google Gemini (https://aistudio.google.com/apikey).
# Used automatically when ANTHROPIC_API_KEY is absent but a Gemini key is set.
GEMINI_API_KEY_ENV: str = "GEMINI_API_KEY"
GEMINI_MODEL: str = os.environ.get("SPEEDRUN_GEMINI_MODEL", "gemini-2.0-flash")

# Optional free-tier provider: Groq (https://console.groq.com/keys). Fast, and
# used automatically when no Anthropic/Gemini key is set but GROQ_API_KEY is.
GROQ_API_KEY_ENV: str = "GROQ_API_KEY"
GROQ_MODEL: str = os.environ.get("SPEEDRUN_GROQ_MODEL", "llama-3.3-70b-versatile")

# Generation robustness
GENERATE_MAX_RETRIES: int = 3
GENERATE_BACKOFF_SECONDS: float = 2.0
GENERATE_TIMEOUT_SECONDS: float = 60.0
GENERATE_MAX_TOKENS: int = 2000

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
PKG_DIR: Path = Path(__file__).resolve().parent
SOURCES_DIR: Path = PKG_DIR / "sources"
GOLD_DIR: Path = PKG_DIR / "gold"
GOLD_SET_PATH: Path = GOLD_DIR / "gold_set.json"
ARTIFACTS_DIR: Path = PKG_DIR / "artifacts"

GENERATED_PATH: Path = ARTIFACTS_DIR / "generated.json"
QUESTION_BANK_PATH: Path = ARTIFACTS_DIR / "question_bank.json"
TRANSFER_FACTOR_PATH: Path = ARTIFACTS_DIR / "transfer_factor.json"
SUMMARY_PATH: Path = ARTIFACTS_DIR / "SUMMARY.md"

# --------------------------------------------------------------------------
# DECLARED CUTOFFS -- well-formedness
# --------------------------------------------------------------------------
# A defensible MCAT MCQ has exactly four distinct, non-empty choices and one
# correct answer. We require exactly four (the MCAT uses four-option items).
MIN_CHOICES: int = 4
MAX_CHOICES: int = 4

# --------------------------------------------------------------------------
# DECLARED CUTOFFS -- source grounding
# --------------------------------------------------------------------------
# The correct answer + rationale must reuse enough of the cited source's
# content words to be considered supported by that source. Below this, the
# card is not traceable to its named source and is blocked.
MIN_GROUNDING_SCORE: float = 0.60

# --------------------------------------------------------------------------
# DECLARED CUTOFFS -- transfer, not copy (the whole point of 7d)
# --------------------------------------------------------------------------
# The generated stem must be a REWORDING of the source idea, not a copy of the
# source's own question wording. If stem-vs-source similarity is at or above
# this, we treat it as a near-duplicate (memorized phrasing) and block it.
MAX_TRANSFER_SIMILARITY: float = 0.55

# --------------------------------------------------------------------------
# DECLARED CUTOFFS -- gold-set gate (7f) and eval (held-out)
# --------------------------------------------------------------------------
# A single card PASSES the pre-ship gate iff it is well-formed AND grounded AND
# a genuine transfer (not a copy). Anything else is blocked from students.
#
# At the batch level we also declare a minimum "correct + useful" pass rate;
# below it we do not ship the batch even if individual cards passed.
GOLD_MIN_PASS_RATE: float = 0.80

# Held-out eval: the AI's stated correct answers must agree with the known
# gold answers at least this often, and must assert an outright WRONG fact no
# more than this often. A wrong fact is worse than no card, so the wrong-answer
# ceiling is strict.
EVAL_MIN_ACCURACY: float = 0.80
EVAL_MAX_WRONG_RATE: float = 0.10

# Fraction of the gold set held out for eval (the rest is "seen"). Split is
# deterministic (fixed seed) so the eval is reproducible.
EVAL_HELDOUT_FRACTION: float = 0.40
EVAL_SPLIT_SEED: int = 7

# --------------------------------------------------------------------------
# DECLARED CUTOFFS -- leakage (7e)
# --------------------------------------------------------------------------
# What "leakage" means here (RE-DECLARED 2026-07-02, with rationale):
#   The harm 7e targets is a held-out TEST QUESTION being seen by the model
#   (in its priming) or reproduced verbatim as output, which would inflate the
#   eval. The IDENTITY of a test item is its QUESTION (stem) -- NOT its answer.
#   The correct answer to a factual MCAT question IS the fact (e.g. "lowering
#   the activation energy"), and that fact legitimately appears in any grounded
#   source passage and in the correct answer choice. Flagging that as "leakage"
#   is a false positive: it is grounding, not a leaked test. So we scan the
#   held-out test QUESTION STEMS against:
#     (a) PRIMING the model receives -- system prompt + few-shot examples, and
#     (b) GENERATED STEMS (answer choices excluded).
#   Source passages are the substrate we generate FROM; source<->fact overlap is
#   expected provenance, so a source is flagged ONLY if it reproduces a whole
#   gold item (question AND answer) near-verbatim (a pasted Q&A), not for
#   sharing a fact. (The earlier version scanned question+answer+choices+source
#   at 0.30 and produced false positives on shared facts; this re-scope fixes
#   that without weakening detection of a genuinely pre-seen/reproduced item.)
LEAKAGE_NGRAM_N: int = 5
# Near-copy threshold for a held-out test QUESTION stem vs priming / a generated
# stem: at/above this normalized n-gram containment (or an exact/substring
# match) it is flagged.
LEAKAGE_MAX_OVERLAP: float = 0.30
# A source passage is flagged only if it contains a whole gold item (its answer
# tokens AND enough of its question) at/above this level -- i.e. a verbatim
# Q&A paste, not a shared fact.
LEAKAGE_SOURCE_ITEM_OVERLAP: float = 0.85

# --------------------------------------------------------------------------
# Semantic-match cutoff used by eval to decide whether a generated correct
# choice "agrees with" the known gold answer.
# --------------------------------------------------------------------------
ANSWER_MATCH_THRESHOLD: float = 0.50

# --------------------------------------------------------------------------
# Anki collection auto-discovery (best-effort, read-only, never required)
# --------------------------------------------------------------------------
def anki_collection_candidates() -> "list[Path]":
    """Return likely paths to the user's Anki collection(s), Windows-first.

    Purely best-effort; callers must tolerate an empty list.
    """
    candidates: "list[Path]" = []
    appdata = os.environ.get("APPDATA")
    roots: "list[Path]" = []
    if appdata:
        roots.append(Path(appdata) / "Anki2")
    # Cross-platform fallbacks so the code is not Windows-only at import time.
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
                    candidates.append(col)
        except OSError:
            continue
    return candidates


# Config key the Rust performance engine reads for the measured bridge.
TRANSFER_FACTOR_CONFIG_KEY: str = "mcatTransferFactor"
