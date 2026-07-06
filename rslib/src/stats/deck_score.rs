// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

//! Speedrun: a single, honest deck score.
//!
//! Reduces a search to one number you can defend, with a **confidence range,
//! not a false point.** The score projects the observed mastery rate
//! (mastered / reviewed) onto cards you have not reviewed yet, and reports a
//! 95% Wilson interval around it. The more of the deck is still unseen, the
//! wider the range; once every card has been reviewed the range collapses to a
//! single exact value. A deck where you have reviewed 5 of 500 cards cannot
//! honestly claim a precise score.
//!
//! Like the mastery query, this is a read-only pass over the matched cards and
//! touches no undo-tracked state, so it is inherently undo-safe.

use anki_proto::stats::McatDeckScoreResponse;
use fsrs::FSRS;
use fsrs::FSRS5_DEFAULT_DECAY;

use super::mastery::MASTERED_RETRIEVABILITY;
use crate::prelude::*;
use crate::scheduler::timing::SchedTimingToday;

/// z-score for a two-sided 95% confidence interval.
const WILSON_Z: f64 = 1.96;

/// Wilson score interval for `successes` out of `trials`. With no trials we
/// know nothing, so the interval is the whole `[0, 1]` range.
fn wilson_bounds(successes: u32, trials: u32) -> (f64, f64) {
    if trials == 0 {
        return (0.0, 1.0);
    }
    let n = trials as f64;
    let p = successes as f64 / n;
    let z2 = WILSON_Z * WILSON_Z;
    let denom = 1.0 + z2 / n;
    let center = (p + z2 / (2.0 * n)) / denom;
    let margin = (WILSON_Z / denom) * (p * (1.0 - p) / n + z2 / (4.0 * n * n)).sqrt();
    ((center - margin).max(0.0), (center + margin).min(1.0))
}

/// Build a deck-score response from already-counted totals, so the score is
/// computed exactly one way. Every matched card is scorable (`scorable ==
/// total`), and a card is unseen precisely when it has no memory state
/// (`unseen == total - rated`). Shared by [`Collection::mcat_deck_score`] and
/// the combined [`super::dashboard`] pass.
pub(crate) fn deck_score_from_counts(
    total_cards: u32,
    rated_cards: u32,
    mastered_cards: u32,
) -> McatDeckScoreResponse {
    let scorable_cards = total_cards;
    let unseen_cards = total_cards.saturating_sub(rated_cards);

    let (point, lower, upper) = if scorable_cards == 0 {
        (0.0, 0.0, 0.0)
    } else {
        let scorable = scorable_cards as f64;
        let unseen = unseen_cards as f64;
        let proven = mastered_cards as f64;
        let p_hat = if rated_cards > 0 {
            proven / rated_cards as f64
        } else {
            0.0
        };
        let (w_lower, w_upper) = wilson_bounds(mastered_cards, rated_cards);
        (
            (proven + p_hat * unseen) / scorable,
            (proven + w_lower * unseen) / scorable,
            (proven + w_upper * unseen) / scorable,
        )
    };

    McatDeckScoreResponse {
        score: point as f32,
        score_lower: lower as f32,
        score_upper: upper as f32,
        total_cards,
        scorable_cards,
        rated_cards,
        mastered_cards,
        unseen_cards,
        mastered_threshold: MASTERED_RETRIEVABILITY,
    }
}

impl Collection {
    /// Honest deck score for all cards matching `search` (empty = whole
    /// collection). See the module docs for the scoring model.
    pub fn mcat_deck_score(&mut self, search: &str) -> Result<McatDeckScoreResponse> {
        let timing = self.timing_today()?;
        let sched_timing = SchedTimingToday {
            days_elapsed: timing.days_elapsed,
            now: TimestampSecs::now(),
            next_day_at: timing.next_day_at,
        };
        let fsrs = FSRS::new(None)?;
        let cards = self.all_cards_for_search(search)?;

        let total_cards = cards.len() as u32;
        let mut rated_cards: u32 = 0;
        let mut mastered_cards: u32 = 0;

        for card in &cards {
            let recall = card.memory_state.map(|state| {
                let elapsed = card.seconds_since_last_review(&sched_timing).unwrap_or(0);
                fsrs.current_retrievability_seconds(
                    state.into(),
                    elapsed,
                    card.decay.unwrap_or(FSRS5_DEFAULT_DECAY),
                )
            });
            if let Some(r) = recall {
                rated_cards += 1;
                if r >= MASTERED_RETRIEVABILITY {
                    mastered_cards += 1;
                }
            }
        }

        // Project the observed mastery rate over the unseen cards. The interval
        // width is driven entirely by how much of the deck is still unreviewed.
        Ok(deck_score_from_counts(total_cards, rated_cards, mastered_cards))
    }
}

#[cfg(test)]
mod test {
    use super::*;
    use crate::card::CardType;
    use crate::card::FsrsMemoryState;

    /// Give the note's card an FSRS memory state with the supplied stability,
    /// `days_ago` since its last review, and `lapses` lapse count.
    fn set_card_state(
        col: &mut Collection,
        nid: NoteId,
        deck_id: DeckId,
        stability: f32,
        days_ago: i64,
        lapses: u32,
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
        card.lapses = lapses;
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

    #[test]
    fn empty_collection_scores_zero_with_no_range() -> Result<()> {
        let mut col = Collection::new();
        let r = col.mcat_deck_score("")?;
        assert_eq!(r.total_cards, 0);
        assert_eq!(r.scorable_cards, 0);
        assert_eq!(r.score, 0.0);
        assert_eq!(r.score_lower, 0.0);
        assert_eq!(r.score_upper, 0.0);
        Ok(())
    }

    #[test]
    fn fully_reviewed_deck_has_exact_score_and_zero_range() -> Result<()> {
        let mut col = Collection::new();
        let deck = col.get_or_create_normal_deck("MCAT::Biochem")?.id;
        // Two mastered, two reviewed-but-forgotten -> exactly 50% mastered, and
        // because every card is reviewed there is no uncertainty band.
        for _ in 0..2 {
            let n = add_basic_note(&mut col, deck);
            set_card_state(&mut col, n, deck, 1000.0, 0, 0);
        }
        for _ in 0..2 {
            let n = add_basic_note(&mut col, deck);
            set_card_state(&mut col, n, deck, 0.5, 120, 0);
        }

        let r = col.mcat_deck_score("")?;
        assert_eq!(r.total_cards, 4);
        assert_eq!(r.scorable_cards, 4);
        assert_eq!(r.rated_cards, 4);
        assert_eq!(r.unseen_cards, 0);
        assert_eq!(r.mastered_cards, 2);
        assert!((r.score - 0.5).abs() < 1e-6);
        // No unseen cards => the range collapses onto the point estimate.
        assert!((r.score_lower - 0.5).abs() < 1e-6);
        assert!((r.score_upper - 0.5).abs() < 1e-6);
        Ok(())
    }

    #[test]
    fn unseen_cards_widen_the_range() -> Result<()> {
        let mut col = Collection::new();
        let deck = col.get_or_create_normal_deck("MCAT::Physics")?.id;
        // One reviewed+mastered card, plus three brand-new unseen cards.
        let n = add_basic_note(&mut col, deck);
        set_card_state(&mut col, n, deck, 1000.0, 0, 0);
        for _ in 0..3 {
            add_basic_note(&mut col, deck);
        }

        let r = col.mcat_deck_score("")?;
        assert_eq!(r.scorable_cards, 4);
        assert_eq!(r.rated_cards, 1);
        assert_eq!(r.unseen_cards, 3);
        assert_eq!(r.mastered_cards, 1);
        // The proven floor is 1/4; the projection pulls the point above it and
        // the unseen cards leave a real gap between the bounds.
        assert!(r.score >= 0.25);
        assert!(r.score_lower < r.score_upper);
        assert!(r.score_lower >= 0.25 - 1e-6);
        assert!(r.score_upper <= 1.0 + 1e-6);
        Ok(())
    }

    #[test]
    fn lapsed_unmastered_cards_still_count_against_score() -> Result<()> {
        let mut col = Collection::new();
        let deck = col.get_or_create_normal_deck("MCAT::Orgo")?.id;
        // One mastered card.
        let good = add_basic_note(&mut col, deck);
        set_card_state(&mut col, good, deck, 1000.0, 0, 0);
        // One stale, heavily-lapsed card that is still not mastered. There is no
        // give-up rule: it is a scorable, reviewed, unmastered card and so it
        // honestly drags the score down.
        let leech = add_basic_note(&mut col, deck);
        set_card_state(&mut col, leech, deck, 0.1, 365, 20);

        let r = col.mcat_deck_score("")?;
        assert_eq!(r.total_cards, 2);
        assert_eq!(r.scorable_cards, 2);
        assert_eq!(r.rated_cards, 2);
        assert_eq!(r.mastered_cards, 1);
        // Every card is reviewed, so the range collapses to an exact 1/2.
        assert!((r.score - 0.5).abs() < 1e-6);
        assert!((r.score_lower - 0.5).abs() < 1e-6);
        assert!((r.score_upper - 0.5).abs() < 1e-6);
        Ok(())
    }
}
