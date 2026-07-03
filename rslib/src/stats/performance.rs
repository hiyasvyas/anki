// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

//! Speedrun: the memory -> performance bridge.
//!
//! Memory (how well you can *recall* a card) is not the same as performance
//! (how well you *answer a new exam-style question* on that material). We model
//! performance as memory recall discounted by a single, **measured** transfer
//! factor rather than an invented curve:
//!
//! - `performance = memory_score * transfer_factor`
//!
//! The transfer factor is read from the collection config key
//! `mcatTransferFactor` (with optional `mcatTransferFactorLower` /
//! `mcatTransferFactorUpper` bounds), exactly like [`pace`] reads `examDate`.
//! Until a factor has actually been measured against graded practice questions
//! it is left unset: in that honest default the factor is `1.0` and
//! `transfer_measured` is `false`, so performance is shown *equal* to memory
//! rather than pretending we know a discount we have not measured.
//!
//! All numbers are derived from [`Collection::mcat_deck_score`] and
//! [`Collection::mcat_mastery`], so performance can never drift from the memory
//! model. This is a read-only pass and touches no undo-tracked state, so it is
//! inherently undo-safe.
//!
//! [`pace`]: super::pace

use anki_proto::stats::mcat_performance_response::TopicPerformance;
use anki_proto::stats::McatPerformanceResponse;

use crate::prelude::*;

/// Config key holding the measured memory->performance transfer factor.
pub(crate) const TRANSFER_FACTOR_KEY: &str = "mcatTransferFactor";
/// Config keys holding the optional lower/upper bounds of the transfer factor.
pub(crate) const TRANSFER_FACTOR_LOWER_KEY: &str = "mcatTransferFactorLower";
pub(crate) const TRANSFER_FACTOR_UPPER_KEY: &str = "mcatTransferFactorUpper";

/// The measured transfer factor and its bounds. `measured` is false when no
/// factor has been configured yet, in which case `factor == lower == upper ==
/// 1.0` (performance equals memory, the honest default).
#[derive(Clone, Copy, Debug)]
pub(crate) struct TransferFactor {
    pub factor: f64,
    pub lower: f64,
    pub upper: f64,
    pub measured: bool,
}

fn clamp01(x: f64) -> f64 {
    x.clamp(0.0, 1.0)
}

impl Collection {
    /// Read the measured transfer factor from config. Unset => an honest 1.0
    /// with `measured = false`; when set, the lower/upper bounds default to the
    /// factor itself if their own keys are unset.
    pub(crate) fn mcat_transfer_factor(&self) -> TransferFactor {
        match self.get_config_optional::<f64, _>(TRANSFER_FACTOR_KEY) {
            Some(factor) => {
                let lower = self
                    .get_config_optional::<f64, _>(TRANSFER_FACTOR_LOWER_KEY)
                    .unwrap_or(factor);
                let upper = self
                    .get_config_optional::<f64, _>(TRANSFER_FACTOR_UPPER_KEY)
                    .unwrap_or(factor);
                TransferFactor {
                    factor,
                    lower,
                    upper,
                    measured: true,
                }
            }
            None => TransferFactor {
                factor: 1.0,
                lower: 1.0,
                upper: 1.0,
                measured: false,
            },
        }
    }

    /// Expected exam performance for all cards matching `search` (empty = whole
    /// collection). See the module docs for the model.
    pub fn mcat_performance(&mut self, search: &str) -> Result<McatPerformanceResponse> {
        let tf = self.mcat_transfer_factor();
        let memory = self.mcat_deck_score(search)?;
        let mastery = self.mcat_mastery(search)?;

        let performance = clamp01(memory.score as f64 * tf.factor);
        let perf_lower = clamp01(memory.score_lower as f64 * tf.lower);
        let perf_upper = clamp01(memory.score_upper as f64 * tf.upper);

        let topics = mastery
            .topics
            .into_iter()
            .map(|t| {
                let recall = t.average_recall as f64;
                TopicPerformance {
                    deck_id: t.deck_id,
                    topic: t.topic,
                    memory_recall: t.average_recall,
                    performance: clamp01(recall * tf.factor) as f32,
                    perf_lower: clamp01(recall * tf.lower) as f32,
                    perf_upper: clamp01(recall * tf.upper) as f32,
                    rated_cards: t.rated_cards,
                    total_cards: t.total_cards,
                }
            })
            .collect();

        Ok(McatPerformanceResponse {
            topics,
            performance: performance as f32,
            perf_lower: perf_lower as f32,
            perf_upper: perf_upper as f32,
            transfer_factor: tf.factor as f32,
            transfer_factor_lower: tf.lower as f32,
            transfer_factor_upper: tf.upper as f32,
            transfer_measured: tf.measured,
            rated_cards: memory.rated_cards,
            scorable_cards: memory.scorable_cards,
        })
    }
}

#[cfg(test)]
mod test {
    use super::*;
    use crate::card::CardType;
    use crate::card::FsrsMemoryState;
    use fsrs::FSRS5_DEFAULT_DECAY;

    /// Give the note's card an FSRS memory state so it reads as reviewed, with
    /// the supplied `stability` and `days_ago` since its last review (a high
    /// stability reviewed today reads as ~mastered).
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

    fn add_basic_note(col: &mut Collection, deck_id: DeckId) -> NoteId {
        let nt = col.get_notetype_by_name("Basic").unwrap().unwrap();
        let mut note = nt.new_note();
        col.add_note(&mut note, deck_id).unwrap();
        note.id
    }

    /// A fully-reviewed deck so the memory score has no unseen-card uncertainty:
    /// its point estimate and bounds all coincide, making the transfer maths
    /// easy to assert exactly.
    fn fully_reviewed_deck(col: &mut Collection) {
        let deck = col.get_or_create_normal_deck("MCAT::Biochem").unwrap().id;
        for _ in 0..3 {
            let n = add_basic_note(col, deck);
            set_card_state(col, n, deck, 1000.0, 0);
        }
        let n = add_basic_note(col, deck);
        set_card_state(col, n, deck, 0.5, 120);
    }

    #[test]
    fn empty_collection_has_zero_performance() -> Result<()> {
        let mut col = Collection::new();
        let r = col.mcat_performance("")?;
        assert_eq!(r.scorable_cards, 0);
        assert_eq!(r.rated_cards, 0);
        assert_eq!(r.performance, 0.0);
        assert_eq!(r.perf_lower, 0.0);
        assert_eq!(r.perf_upper, 0.0);
        assert!(r.topics.is_empty());
        // No config set => honest default: factor 1.0 and not yet measured.
        assert!(!r.transfer_measured);
        assert!((r.transfer_factor - 1.0).abs() < 1e-6);
        Ok(())
    }

    #[test]
    fn unmeasured_transfer_factor_makes_performance_equal_memory() -> Result<()> {
        let mut col = Collection::new();
        fully_reviewed_deck(&mut col);

        let memory = col.mcat_deck_score("")?;
        let perf = col.mcat_performance("")?;

        // With no measured bridge, performance is shown equal to memory.
        assert!(!perf.transfer_measured);
        assert!((perf.transfer_factor - 1.0).abs() < 1e-6);
        assert!((perf.performance - memory.score).abs() < 1e-6);
        assert!((perf.perf_lower - memory.score_lower).abs() < 1e-6);
        assert!((perf.perf_upper - memory.score_upper).abs() < 1e-6);
        // Per-topic performance also equals the topic's memory recall.
        assert_eq!(perf.topics.len(), 1);
        let topic = &perf.topics[0];
        assert!((topic.performance - topic.memory_recall).abs() < 1e-6);
        Ok(())
    }

    #[test]
    fn measured_transfer_factor_discounts_performance() -> Result<()> {
        let mut col = Collection::new();
        fully_reviewed_deck(&mut col);
        // Measure a 0.5 bridge: half of what you can recall transfers to new
        // exam-style questions.
        col.set_config(TRANSFER_FACTOR_KEY, &0.5f64)?;

        let memory = col.mcat_deck_score("")?;
        let perf = col.mcat_performance("")?;

        assert!(perf.transfer_measured);
        assert!((perf.transfer_factor - 0.5).abs() < 1e-6);
        // Bounds default to the factor when unset.
        assert!((perf.transfer_factor_lower - 0.5).abs() < 1e-6);
        assert!((perf.transfer_factor_upper - 0.5).abs() < 1e-6);
        assert!((perf.performance - 0.5 * memory.score).abs() < 1e-6);
        let topic = &perf.topics[0];
        assert!((topic.performance - 0.5 * topic.memory_recall).abs() < 1e-6);
        Ok(())
    }

    #[test]
    fn transfer_factor_bounds_widen_the_range() -> Result<()> {
        let mut col = Collection::new();
        fully_reviewed_deck(&mut col);
        col.set_config(TRANSFER_FACTOR_KEY, &0.6f64)?;
        col.set_config(TRANSFER_FACTOR_LOWER_KEY, &0.4f64)?;
        col.set_config(TRANSFER_FACTOR_UPPER_KEY, &0.8f64)?;

        let perf = col.mcat_performance("")?;
        assert!(perf.transfer_measured);
        assert!((perf.transfer_factor_lower - 0.4).abs() < 1e-6);
        assert!((perf.transfer_factor_upper - 0.8).abs() < 1e-6);
        // A real band opens up around the point estimate.
        assert!(perf.perf_lower < perf.performance);
        assert!(perf.performance < perf.perf_upper);
        Ok(())
    }
}
