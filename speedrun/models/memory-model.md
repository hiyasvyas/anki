# Memory Model — one page

**Question it answers:** *Can the student recall this fact right now?*

**Engine call:** `mcat_deck_score` (Rust, `rslib/src/stats/deck_score.rs`) with per-topic
detail from `mcat_mastery` (`rslib/src/stats/mastery.rs`). Both are read-only passes;
no writes, no undo entry.

## How it works
- Memory of a single card = its **current FSRS retrievability**, computed with the
  native `fsrs` crate (`current_retrievability_seconds`) from the card's memory
  state, decay, and time since last review — the *same* path Anki's own stats
  graphs use, so the number can never disagree with Anki.
- A card is **mastered** when current recall ≥ `MASTERED_RETRIEVABILITY` (0.9).
- **Deck score** (0–1) = the observed mastery rate on reviewed cards, *projected*
  over the cards not yet reviewed:
  `score = (mastered + p̂ · unseen) / scorable`, where `p̂ = mastered / reviewed`.
  Once every card is reviewed it equals `mastered / scorable` exactly.

## The range (honest uncertainty)
- A **95% Wilson interval** on the reviewed sample, projected across the unseen
  cards. Width is driven entirely by how much of the deck is still unreviewed:
  review 5 of 500 cards and the band is wide; review everything and it
  **collapses to a single value**. The score never claims precision it hasn't
  earned.

## Calibration plan (Sunday Step 1)
- Hold back a slice of reviews, and check that when the model says 80% the
  student actually recalls ≈80%. Report a **calibration chart + Brier/log-loss**
  on the held-out reviews. (Because recall comes straight from FSRS, this is a
  check of FSRS calibration on this deck, reported honestly.)

## Give-up behaviour
- The raw RPC always returns honest numbers. The **readiness** layer (not this
  one) decides when to abstain — see `readiness-model.md`.

**Inputs:** cards, FSRS `memory_state`, `decay`, `last_review_time`.
**Outputs:** `score`, `score_lower`, `score_upper`, `total/scorable/rated/mastered/unseen_cards`, `mastered_threshold`.
