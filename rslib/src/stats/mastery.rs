// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

//! Speedrun: per-topic mastery breakdown.
//!
//! For every deck ("topic") whose cards match a search, we report how many
//! cards are mastered and the average FSRS recall. "Recall" is the card's
//! current FSRS retrievability (0-1); a card counts as mastered once its recall
//! is at or above [`MASTERED_RETRIEVABILITY`]. New/unreviewed cards have no
//! memory state, so they are counted in `total_cards` but never as mastered and
//! are excluded from the recall average (averaging over a default would lie
//! about how well the deck is actually known).
//!
//! This is a read-only query: it touches no undo-tracked state, so it is
//! inherently undo-safe.

use std::collections::HashMap;

use anki_proto::stats::mcat_mastery_response::TopicMastery;
use anki_proto::stats::McatMasteryResponse;
use fsrs::FSRS;
use fsrs::FSRS5_DEFAULT_DECAY;

use crate::prelude::*;
use crate::scheduler::timing::SchedTimingToday;

/// A card is considered "mastered" once its current recall reaches this value.
pub const MASTERED_RETRIEVABILITY: f32 = 0.9;

#[derive(Default)]
struct TopicAccumulator {
    total_cards: u32,
    rated_cards: u32,
    mastered_cards: u32,
    recall_sum: f32,
}

impl Collection {
    /// Per-topic mastery for all cards matching `search` (empty = whole
    /// collection). Topics are sorted by name for stable output.
    pub fn mcat_mastery(&mut self, search: &str) -> Result<McatMasteryResponse> {
        let timing = self.timing_today()?;
        let sched_timing = SchedTimingToday {
            days_elapsed: timing.days_elapsed,
            now: TimestampSecs::now(),
            next_day_at: timing.next_day_at,
        };
        let fsrs = FSRS::new(None)?;
        let cards = self.all_cards_for_search(search)?;

        let mut by_deck: HashMap<DeckId, TopicAccumulator> = HashMap::new();
        let mut total_cards: u32 = 0;
        let mut total_mastered: u32 = 0;
        for card in &cards {
            let acc = by_deck.entry(card.deck_id).or_default();
            acc.total_cards += 1;
            total_cards += 1;
            if let Some(state) = card.memory_state {
                let elapsed = card.seconds_since_last_review(&sched_timing).unwrap_or(0);
                let recall = fsrs.current_retrievability_seconds(
                    state.into(),
                    elapsed,
                    card.decay.unwrap_or(FSRS5_DEFAULT_DECAY),
                );
                acc.rated_cards += 1;
                acc.recall_sum += recall;
                if recall >= MASTERED_RETRIEVABILITY {
                    acc.mastered_cards += 1;
                    total_mastered += 1;
                }
            }
        }

        let mut topics: Vec<TopicMastery> = Vec::with_capacity(by_deck.len());
        for (deck_id, acc) in by_deck {
            let topic = self
                .storage
                .get_deck(deck_id)?
                .map(|d| d.human_name())
                .unwrap_or_else(|| format!("[deck {}]", deck_id.0));
            let average_recall = if acc.rated_cards > 0 {
                acc.recall_sum / acc.rated_cards as f32
            } else {
                0.0
            };
            topics.push(TopicMastery {
                deck_id: deck_id.0,
                topic,
                total_cards: acc.total_cards,
                rated_cards: acc.rated_cards,
                mastered_cards: acc.mastered_cards,
                average_recall,
            });
        }
        topics.sort_by(|a, b| a.topic.cmp(&b.topic));

        Ok(McatMasteryResponse {
            topics,
            mastered_threshold: MASTERED_RETRIEVABILITY,
            total_cards,
            mastered_cards: total_mastered,
        })
    }
}

#[cfg(test)]
mod test {
    use super::*;
    use crate::card::CardType;
    use crate::card::FsrsMemoryState;

    /// Give the note's card an FSRS memory state with the supplied stability,
    /// placing the last review `days_ago` days in the past so recall decays
    /// predictably. A high stability reviewed today reads as ~mastered; a low
    /// stability reviewed long ago reads as forgotten.
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

    #[test]
    fn empty_collection_reports_nothing() -> Result<()> {
        let mut col = Collection::new();
        let report = col.mcat_mastery("")?;
        assert_eq!(report.total_cards, 0);
        assert_eq!(report.mastered_cards, 0);
        assert!(report.topics.is_empty());
        assert_eq!(report.mastered_threshold, MASTERED_RETRIEVABILITY);
        Ok(())
    }

    #[test]
    fn groups_by_topic_and_counts_mastery() -> Result<()> {
        let mut col = Collection::new();
        let bio = col.get_or_create_normal_deck("MCAT::Biochem")?.id;
        let physics = col.get_or_create_normal_deck("MCAT::Physics")?.id;

        // Biochem: one strong card (mastered) + one unreviewed new card.
        let n1 = add_basic_note(&mut col, bio);
        set_card_state(&mut col, n1, bio, 1000.0, 0);
        add_basic_note(&mut col, bio);
        // Physics: one stale, low-stability card (recall well below threshold).
        let n3 = add_basic_note(&mut col, physics);
        set_card_state(&mut col, n3, physics, 1.0, 60);

        let report = col.mcat_mastery("")?;
        assert_eq!(report.total_cards, 3);
        assert_eq!(report.mastered_cards, 1);
        // Sorted by topic name: Biochem before Physics.
        assert_eq!(report.topics.len(), 2);

        let biochem = &report.topics[0];
        assert_eq!(biochem.topic, "MCAT::Biochem");
        assert_eq!(biochem.total_cards, 2);
        assert_eq!(biochem.rated_cards, 1);
        assert_eq!(biochem.mastered_cards, 1);
        // Average is over rated cards only, so the new card doesn't drag it down.
        assert!(biochem.average_recall >= MASTERED_RETRIEVABILITY);

        let physics_topic = &report.topics[1];
        assert_eq!(physics_topic.topic, "MCAT::Physics");
        assert_eq!(physics_topic.total_cards, 1);
        assert_eq!(physics_topic.rated_cards, 1);
        assert_eq!(physics_topic.mastered_cards, 0);
        assert!(physics_topic.average_recall < MASTERED_RETRIEVABILITY);
        Ok(())
    }

    #[test]
    fn search_filters_topics() -> Result<()> {
        let mut col = Collection::new();
        let bio = col.get_or_create_normal_deck("MCAT::Biochem")?.id;
        let physics = col.get_or_create_normal_deck("MCAT::Physics")?.id;
        let n1 = add_basic_note(&mut col, bio);
        set_card_state(&mut col, n1, bio, 1000.0, 0);
        let n2 = add_basic_note(&mut col, physics);
        set_card_state(&mut col, n2, physics, 1000.0, 0);

        let report = col.mcat_mastery("deck:MCAT::Biochem")?;
        assert_eq!(report.topics.len(), 1);
        assert_eq!(report.topics[0].topic, "MCAT::Biochem");
        assert_eq!(report.total_cards, 1);
        assert_eq!(report.mastered_cards, 1);
        Ok(())
    }
}
