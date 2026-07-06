// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

//! Speedrun: the whole dashboard in one shared pass.
//!
//! The desktop dashboard shows five engine-computed numbers side by side:
//! per-topic mastery, the honest deck score, expected performance, projected
//! readiness, and pace. Computed the naive way each of those is its own RPC,
//! and each RPC runs its own full-collection scan -- worse, [`readiness`]
//! internally re-runs [`performance`], which itself re-runs both
//! [`deck_score`] and [`mastery`]. On a large collection that is ~nine
//! full-table scans to draw one panel, and the bundle cost is essentially the
//! sum of the parts (see `speedrun/proof/latency.md`).
//!
//! This computes all five from **one shared card scan and one shared revlog
//! scan**, then derives the dependent numbers in memory:
//!
//! - the card pass feeds mastery *and* the deck-score counts (the deck score is
//!   just the collection-wide totals of the same per-card mastery decision),
//! - performance is the pure memory->performance bridge over those two,
//! - the revlog pass yields both the readiness give-up count and the pace
//!   window aggregation,
//! - readiness is the pure give-up rule over performance + that count.
//!
//! Every field returned is identical to calling the matching single RPC for
//! the same search (there is a parity test below), so this is purely a
//! remove-the-redundant-scans optimization and changes no numbers or models.
//! Like the queries it composes, it is a strictly read-only pass and creates no
//! undo entry.
//!
//! [`readiness`]: super::readiness
//! [`performance`]: super::performance
//! [`deck_score`]: super::deck_score
//! [`mastery`]: super::mastery

use anki_proto::stats::McatDashboardResponse;
use anki_proto::stats::McatMasteryResponse;

use super::deck_score::deck_score_from_counts;
use super::mastery::MASTERED_RETRIEVABILITY;
use crate::prelude::*;
use crate::revlog::RevlogReviewKind;
use crate::search::SortMode;

impl Collection {
    /// Compute mastery, deck score, performance, readiness and pace for all
    /// cards matching `search` (empty = whole collection) from a single shared
    /// card+revlog scan. See the module docs.
    pub fn mcat_dashboard(&mut self, search: &str) -> Result<McatDashboardResponse> {
        let now = TimestampSecs::now();

        // The only two scans the whole dashboard needs.
        let guard = self.search_cards_into_table(search, SortMode::NoOrder)?;
        let cards = guard.col.storage.all_searched_cards()?;
        let revlog = guard.col.storage.get_revlog_entries_for_searched_cards()?;
        drop(guard);

        // Memory + per-topic mastery from the single card pass. The deck score
        // is exactly the collection-wide totals of that same per-card decision,
        // so it needs no second scan.
        let scan = self.mcat_mastery_from_cards(&cards)?;
        let deck_score =
            deck_score_from_counts(scan.total_cards, scan.rated_cards, scan.mastered_cards);
        let mastery = McatMasteryResponse {
            topics: scan.topics,
            mastered_threshold: MASTERED_RETRIEVABILITY,
            total_cards: scan.total_cards,
            mastered_cards: scan.mastered_cards,
        };

        // Performance is the pure bridge over memory + mastery (no scan).
        let performance = self.performance_from(&deck_score, &mastery);

        // The readiness give-up count is the real Review-kind revlog entries,
        // read straight from the shared revlog pass.
        let graded_reviews = revlog
            .iter()
            .filter(|e| e.review_kind == RevlogReviewKind::Review)
            .count() as u32;
        let readiness = self.readiness_from(&performance, graded_reviews);

        // Pace reuses the same card+revlog scan.
        let pace = self.mcat_pace_from_scan(&cards, &revlog, now)?;

        Ok(McatDashboardResponse {
            mastery: Some(mastery),
            deck_score: Some(deck_score),
            performance: Some(performance),
            readiness: Some(readiness),
            pace: Some(pace),
        })
    }
}

#[cfg(test)]
mod test {
    use super::*;
    use crate::card::CardType;
    use crate::card::FsrsMemoryState;
    use crate::revlog::RevlogEntry;
    use crate::revlog::RevlogId;
    use fsrs::FSRS5_DEFAULT_DECAY;

    fn add_basic_note(col: &mut Collection, deck_id: DeckId) -> NoteId {
        let nt = col.get_notetype_by_name("Basic").unwrap().unwrap();
        let mut note = nt.new_note();
        col.add_note(&mut note, deck_id).unwrap();
        note.id
    }

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
            let entry = RevlogEntry {
                id: RevlogId(base * 1000 + i as i64),
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

    /// A mixed collection with several topics, rated and unseen cards, a
    /// measured transfer factor and some graded reviews, so every sub-score
    /// exercises a non-trivial path.
    fn seed(col: &mut Collection) {
        let bio = col.get_or_create_normal_deck("MCAT::Biochem").unwrap().id;
        let phys = col.get_or_create_normal_deck("MCAT::Physics").unwrap().id;
        let chem = col.get_or_create_normal_deck("MCAT::Chem").unwrap().id;

        let n1 = add_basic_note(col, bio);
        set_card_state(col, n1, bio, 1000.0, 0);
        let n2 = add_basic_note(col, bio);
        set_card_state(col, n2, bio, 0.4, 200);
        add_basic_note(col, bio); // unseen

        let n3 = add_basic_note(col, phys);
        set_card_state(col, n3, phys, 1000.0, 0);
        add_basic_note(col, chem); // wholly unseen topic

        col.set_config(super::super::performance::TRANSFER_FACTOR_KEY, &0.7f64)
            .unwrap();
        log_reviews(col, n1, bio, 120, 3);
        log_reviews(col, n3, phys, 40, 4);
    }

    /// The combined dashboard must return byte-for-byte what the five single
    /// RPCs return for the same search -- it only removes redundant scans.
    #[test]
    fn dashboard_matches_individual_rpcs() -> Result<()> {
        let mut col = Collection::new();
        seed(&mut col);

        let mastery = col.mcat_mastery("")?;
        let deck_score = col.mcat_deck_score("")?;
        let performance = col.mcat_performance("")?;
        let mut readiness = col.mcat_readiness("")?;
        let pace = col.mcat_pace("")?;

        let mut dash = col.mcat_dashboard("")?;

        assert_eq!(dash.mastery.as_ref(), Some(&mastery));
        assert_eq!(dash.deck_score.as_ref(), Some(&deck_score));
        assert_eq!(dash.performance.as_ref(), Some(&performance));
        assert_eq!(dash.pace.as_ref(), Some(&pace));

        // `updated_at` is a wall-clock stamp taken independently by each call,
        // so normalise it before comparing the readiness payloads.
        let dash_ready = dash.readiness.as_mut().unwrap();
        readiness.updated_at = 0;
        dash_ready.updated_at = 0;
        assert_eq!(dash_ready, &readiness);
        Ok(())
    }

    #[test]
    fn empty_collection_dashboard_is_all_zero() -> Result<()> {
        let mut col = Collection::new();
        let dash = col.mcat_dashboard("")?;
        assert_eq!(dash.deck_score.unwrap().scorable_cards, 0);
        assert!(dash.mastery.unwrap().topics.is_empty());
        assert_eq!(dash.performance.unwrap().performance, 0.0);
        assert!(!dash.readiness.unwrap().has_score);
        assert!(dash.pace.unwrap().topics.is_empty());
        Ok(())
    }
}
