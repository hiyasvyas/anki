// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

//! Speedrun: a projected MCAT score, with the give-up rule in the engine.
//!
//! This maps expected [`performance`](super::performance) linearly onto the
//! real MCAT scale (`472`-`528`):
//!
//! - `projected = SCALE_MIN + performance * (SCALE_MAX - SCALE_MIN)`
//!
//! The lower/upper bounds map the performance range the same way, so the
//! reported band is exactly as wide as the underlying memory + transfer
//! uncertainty.
//!
//! **The give-up rule lives here, in the engine, so every client (including the
//! phone) obeys the same rule.** A projected score is only shown when there is
//! enough evidence to defend it: BOTH at least [`MIN_GRADED_REVIEWS`] real
//! review-kind revlog entries for the searched cards AND topic coverage of at
//! least [`MIN_TOPIC_COVERAGE`] (the fraction of topics that have at least one
//! rated card). When either gate fails, `has_score` is false and the response
//! still carries the evidence counts, the thresholds, and human-readable
//! `reasons` for what is missing, so the UI can explain the abstention instead
//! of inventing a number.
//!
//! Like the other Mcat* queries this is a strictly read-only pass: it performs
//! no writes and creates no undo entry, so it is inherently undo-safe.

use anki_proto::stats::McatPerformanceResponse;
use anki_proto::stats::McatReadinessResponse;

use crate::prelude::*;
use crate::revlog::RevlogReviewKind;
use crate::search::SortMode;

/// Bottom of the real MCAT total-score scale.
pub(crate) const SCALE_MIN: f32 = 472.0;
/// Top of the real MCAT total-score scale.
pub(crate) const SCALE_MAX: f32 = 528.0;
/// Minimum real review-kind revlog entries before a score is shown.
pub(crate) const MIN_GRADED_REVIEWS: u32 = 230;
/// Minimum topic coverage (fraction of topics with a rated card) before a
/// score is shown.
pub(crate) const MIN_TOPIC_COVERAGE: f32 = 0.5;

/// Confidence label derived purely from topic coverage.
fn confidence_label(coverage: f32) -> &'static str {
    if coverage < 0.60 {
        "Low"
    } else if coverage < 0.85 {
        "Medium"
    } else {
        "High"
    }
}

impl Collection {
    /// Count real review-kind revlog entries for all cards matching `search`.
    /// Read-only: searches into the temp table, reads revlog, and drops the
    /// guard without touching undo-tracked state.
    fn mcat_graded_reviews(&mut self, search: &str) -> Result<u32> {
        let guard = self.search_cards_into_table(search, SortMode::NoOrder)?;
        let revlog = guard.col.storage.get_revlog_entries_for_searched_cards()?;
        drop(guard);
        Ok(revlog
            .iter()
            .filter(|e| e.review_kind == RevlogReviewKind::Review)
            .count() as u32)
    }

    /// Projected MCAT score for all cards matching `search` (empty = whole
    /// collection). See the module docs for the model and the give-up rule.
    pub fn mcat_readiness(&mut self, search: &str) -> Result<McatReadinessResponse> {
        let perf = self.mcat_performance(search)?;
        let graded_reviews = self.mcat_graded_reviews(search)?;
        Ok(self.readiness_from(&perf, graded_reviews))
    }

    /// Derive readiness from an already-computed performance result and graded
    /// review count (no scan). Shared by [`Self::mcat_readiness`] and the
    /// combined [`super::dashboard`] pass so the give-up rule lives one place.
    pub(crate) fn readiness_from(
        &self,
        perf: &McatPerformanceResponse,
        graded_reviews: u32,
    ) -> McatReadinessResponse {
        // Topic coverage: fraction of topics (decks with cards) that have at
        // least one rated card.
        let topic_count = perf.topics.len();
        let covered = perf.topics.iter().filter(|t| t.rated_cards >= 1).count();
        let topic_coverage = if topic_count == 0 {
            0.0
        } else {
            covered as f32 / topic_count as f32
        };

        let span = SCALE_MAX - SCALE_MIN;
        let projected_score = SCALE_MIN + perf.performance * span;
        let score_lower = SCALE_MIN + perf.perf_lower * span;
        let score_upper = SCALE_MIN + perf.perf_upper * span;

        // The give-up rule: only surface a score with enough evidence behind it.
        let has_score =
            graded_reviews >= MIN_GRADED_REVIEWS && topic_coverage >= MIN_TOPIC_COVERAGE;

        let mut reasons: Vec<String> = Vec::new();
        if graded_reviews < MIN_GRADED_REVIEWS {
            reasons.push(format!(
                "only {} of {} graded reviews",
                graded_reviews, MIN_GRADED_REVIEWS
            ));
        }
        if topic_coverage < MIN_TOPIC_COVERAGE {
            reasons.push(format!(
                "topic coverage {:.0}% (need {:.0}%)",
                topic_coverage * 100.0,
                MIN_TOPIC_COVERAGE * 100.0
            ));
        }
        if !perf.transfer_measured {
            reasons.push("transfer factor not yet measured".to_string());
        }
        // Name the weakest rated topic as the clearest driver to work on.
        if let Some(weakest) = perf
            .topics
            .iter()
            .filter(|t| t.rated_cards >= 1)
            .min_by(|a, b| a.performance.total_cmp(&b.performance))
        {
            reasons.push(format!("weakest topic: {}", weakest.topic));
        }

        McatReadinessResponse {
            has_score,
            projected_score,
            score_lower,
            score_upper,
            scale_min: SCALE_MIN,
            scale_max: SCALE_MAX,
            performance: perf.performance,
            topic_coverage,
            graded_reviews,
            min_graded_reviews: MIN_GRADED_REVIEWS,
            min_topic_coverage: MIN_TOPIC_COVERAGE,
            confidence: confidence_label(topic_coverage).to_string(),
            reasons,
            updated_at: TimestampSecs::now().0,
        }
    }
}

#[cfg(test)]
mod test {
    use super::*;
    use crate::card::CardType;
    use crate::card::FsrsMemoryState;
    use fsrs::FSRS5_DEFAULT_DECAY;

    fn add_basic_note(col: &mut Collection, deck_id: DeckId) -> NoteId {
        let nt = col.get_notetype_by_name("Basic").unwrap().unwrap();
        let mut note = nt.new_note();
        col.add_note(&mut note, deck_id).unwrap();
        note.id
    }

    /// Give the note's card an FSRS memory state so it counts as rated (and, at
    /// high stability reviewed today, as mastered).
    fn set_card_state(
        col: &mut Collection,
        nid: NoteId,
        deck_id: DeckId,
        stability: f32,
        days_ago: i64,
    ) {
        let mut card = col
            .storage
            .all_cards_of_note(nid)
            .unwrap()
            .into_iter()
            .next()
            .unwrap();
        card.deck_id = deck_id;
        card.ctype = CardType::Review;
        card.interval = 100;
        card.decay = Some(FSRS5_DEFAULT_DECAY);
        card.memory_state = Some(FsrsMemoryState {
            stability,
            difficulty: 5.0,
        });
        card.last_review_time = Some(TimestampSecs::now().adding_secs(-days_ago * 86_400));
        col.storage.update_card(&card).unwrap();
    }

    /// Write `n` real review-kind revlog rows for the note's card. Mirrors the
    /// pace tests: writes revlog directly, no scheduling.
    fn log_reviews(col: &mut Collection, nid: NoteId, deck_id: DeckId, n: u32, button: u8) {
        let mut card = col
            .storage
            .all_cards_of_note(nid)
            .unwrap()
            .into_iter()
            .next()
            .unwrap();
        card.deck_id = deck_id;
        card.ctype = CardType::Review;
        col.storage.update_card(&card).unwrap();
        let base = TimestampSecs::now().0 - 3_600;
        for i in 0..n {
            let entry = crate::revlog::RevlogEntry {
                id: crate::revlog::RevlogId(base * 1000 + i as i64),
                cid: card.id,
                usn: Usn(-1),
                button_chosen: button,
                interval: 100,
                last_interval: 50,
                ease_factor: 2500,
                taken_millis: 60_000,
                review_kind: RevlogReviewKind::Review,
            };
            col.storage.add_revlog_entry(&entry, true).unwrap();
        }
    }

    #[test]
    fn abstains_without_enough_reviews() -> Result<()> {
        let mut col = Collection::new();
        let bio = col.get_or_create_normal_deck("MCAT::Biochem")?.id;
        // Full topic coverage, but only a handful of graded reviews.
        let n = add_basic_note(&mut col, bio);
        set_card_state(&mut col, n, bio, 1000.0, 0);
        log_reviews(&mut col, n, bio, 5, 3);

        let r = col.mcat_readiness("")?;
        assert!(!r.has_score);
        assert_eq!(r.graded_reviews, 5);
        assert_eq!(r.min_graded_reviews, MIN_GRADED_REVIEWS);
        assert!(!r.reasons.is_empty());
        assert!(r.reasons.iter().any(|s| s.contains("graded reviews")));
        Ok(())
    }

    #[test]
    fn abstains_without_enough_topic_coverage() -> Result<()> {
        let mut col = Collection::new();
        let bio = col.get_or_create_normal_deck("MCAT::Biochem")?.id;
        let phys = col.get_or_create_normal_deck("MCAT::Physics")?.id;
        let chem = col.get_or_create_normal_deck("MCAT::Chem")?.id;
        // Only one of three topics has a rated card -> coverage 1/3 < 0.5.
        let n = add_basic_note(&mut col, bio);
        set_card_state(&mut col, n, bio, 1000.0, 0);
        add_basic_note(&mut col, phys);
        add_basic_note(&mut col, chem);
        // Plenty of graded reviews, so only the coverage gate can fail.
        log_reviews(&mut col, n, bio, MIN_GRADED_REVIEWS, 3);

        let r = col.mcat_readiness("")?;
        assert!(r.graded_reviews >= MIN_GRADED_REVIEWS);
        assert!(r.topic_coverage < MIN_TOPIC_COVERAGE);
        assert!(!r.has_score);
        assert!(r.reasons.iter().any(|s| s.contains("topic coverage")));
        Ok(())
    }

    #[test]
    fn projects_onto_472_528_scale_when_eligible() -> Result<()> {
        let mut col = Collection::new();
        let bio = col.get_or_create_normal_deck("MCAT::Biochem")?.id;
        let phys = col.get_or_create_normal_deck("MCAT::Physics")?.id;
        // Both topics covered by a mastered, rated card.
        let n1 = add_basic_note(&mut col, bio);
        set_card_state(&mut col, n1, bio, 1000.0, 0);
        let n2 = add_basic_note(&mut col, phys);
        set_card_state(&mut col, n2, phys, 1000.0, 0);
        // Enough graded reviews across the searched cards to clear the gate.
        log_reviews(&mut col, n1, bio, 200, 3);
        log_reviews(&mut col, n2, phys, 40, 3);

        let r = col.mcat_readiness("")?;
        assert!(r.has_score);
        assert!((r.topic_coverage - 1.0).abs() < 1e-6);
        assert_eq!(r.scale_min, SCALE_MIN);
        assert_eq!(r.scale_max, SCALE_MAX);
        assert!(r.projected_score >= SCALE_MIN);
        assert!(r.projected_score <= SCALE_MAX);
        assert!(r.score_lower <= r.projected_score);
        assert!(r.projected_score <= r.score_upper);
        assert_eq!(r.confidence, "High");
        Ok(())
    }
}
