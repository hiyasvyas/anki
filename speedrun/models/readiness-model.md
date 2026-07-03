# Readiness Model — one page

**Question it answers:** *What MCAT score would the student get today, and how sure
are we?*

**Engine call:** `mcat_readiness` (Rust, `rslib/src/stats/readiness.rs`).
Read-only. The give-up rule lives **in the engine** so desktop and phone follow
the identical rule.

## Scale and mapping
- MCAT total scale: **472–528** (`SCALE_MIN`/`SCALE_MAX`).
- `projected = 472 + performance · (528 − 472)`, with `score_lower`/`score_upper`
  mapped the same way from the performance range. Method is written down and
  intentionally simple: it turns the performance estimate into the real scale and
  carries the range through — it does **not** pretend to be calibrated against
  real test-taker outcomes (we don't have those; see below).

## The give-up rule (write it down)
A score is shown **only when BOTH** hold:
1. **≥ 230 graded reviews** — tied to the size of one full-length MCAT (~230
   scored questions), so we won't project readiness until the student has worked
   through at least a practice-test's worth of material; and
2. **≥ 50% topic coverage** — fraction of topics (decks with cards) that have at
   least one reviewed card, so a deck that drilled one subject can't claim
   readiness for the whole exam (challenge 7c).

When either fails, the engine returns `has_score = false` with `reasons`
describing exactly what's missing. **A good system knows when it does not know.**

## What ships with every shown score (honesty rule)
- point estimate + **likely range**, not one number;
- **confidence** label (Low < 60% topic coverage, Medium < 85%, else High);
- **coverage** (% of exam topics touched);
- **last updated** timestamp;
- **main reasons** behind the number;
- the **give-up rule** itself.

## Honest scope (Sunday Step 3/4)
We prove the *steps of the bridge* — calibrated memory, a measured
memory→performance transfer factor, and a stated performance→scale mapping — and
we explicitly do **not** claim a calibrated final score against real practice-test
outcomes, because we do not have paired study-history + practice-test data in the
sprint window. Saying so scores higher than a polished number we can't back up.

**Outputs:** `has_score`, `projected_score`, `score_lower/upper`, `scale_min/max`,
`performance`, `topic_coverage`, `graded_reviews`, `min_graded_reviews`,
`min_topic_coverage`, `confidence`, `reasons`, `updated_at`.
