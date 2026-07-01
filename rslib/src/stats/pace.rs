// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

//! Speedrun: a first-class pace model built on the answer time Anki already
//! records.
//!
//! Every review already stores how long the student took to answer
//! (`revlog.time`, in ms, capped per preset). We turn that free, already-synced
//! signal into a per-topic pace model:
//!
//! - **accuracy** = fraction of recent graded reviews answered better than
//!   "Again" (button >= Hard),
//! - **mean answer time** over the same recent window,
//! - a **pace ladder** target (unlimited -> 300s -> 180s -> 120s -> 90s goal).
//!
//! The exam date only sets the *starting* rung. A topic then drops to the next
//! shorter rung only when it has earned it: at least [`PACE_MIN_REVIEWS`]
//! recent graded reviews, accuracy at or above [`PACE_MIN_ACCURACY`], AND a
//! mean answer time already inside the next rung. That is the "only speed up
//! when you are both faster and more accurate" rule, and it is evidence-gated
//! just like the readiness give-up rule.
//!
//! The same per-topic numbers feed the `PaceWeakness` review order (see the
//! queue builder), which surfaces weak/slow topics first. This query is a
//! read-only pass over revlog and touches no undo-tracked state, so it is
//! inherently undo-safe. Nothing here changes FSRS intervals.

use std::collections::HashMap;

use anki_proto::stats::mcat_pace_response::TopicPace;
use anki_proto::stats::McatPaceResponse;

use crate::prelude::*;
use crate::search::SortMode;

/// Pace-ladder rung targets, in ms. Index 0 is "unlimited" (no timer); the last
/// entry is the 90s goal. A topic climbs from a start rung toward the goal only
/// as it proves it is faster and more accurate.
pub(crate) const PACE_RUNGS_MS: [u32; 5] = [0, 300_000, 180_000, 120_000, 90_000];
/// Goal target at the top of the ladder (90 seconds).
pub(crate) const PACE_GOAL_MS: u32 = 90_000;
/// Minimum graded reviews in the window before a rung is allowed to advance.
pub(crate) const PACE_MIN_REVIEWS: u32 = 20;
/// Minimum accuracy before a rung is allowed to advance.
pub(crate) const PACE_MIN_ACCURACY: f32 = 0.85;
/// Recent-window length: only reviews from the last this-many days count, so
/// the pace reflects current ability rather than ancient struggles.
pub(crate) const PACE_WINDOW_DAYS: i64 = 90;

/// Aggregated recent pace for one topic (deck).
#[derive(Default, Clone, Copy, Debug)]
pub(crate) struct DeckPace {
    pub reviews: u32,
    pub correct: u32,
    pub sum_ms: i64,
}

impl DeckPace {
    pub(crate) fn accuracy(&self) -> f32 {
        if self.reviews == 0 {
            0.0
        } else {
            self.correct as f32 / self.reviews as f32
        }
    }

    pub(crate) fn mean_ms(&self) -> f64 {
        if self.reviews == 0 {
            0.0
        } else {
            self.sum_ms as f64 / self.reviews as f64
        }
    }
}

/// Rung implied purely by how long until the exam. `None` (no exam date) or
/// more than six months out starts unlimited; the ladder floor rises as test
/// day approaches so a last-minute learner is not stuck at "unlimited".
pub(crate) fn starting_rung(months_remaining: Option<f64>) -> usize {
    match months_remaining {
        Some(m) if m <= 1.0 => 4,
        Some(m) if m <= 2.0 => 3,
        Some(m) if m <= 4.0 => 2,
        Some(m) if m <= 6.0 => 1,
        _ => 0,
    }
}

/// The rung a topic has actually earned: start at `start`, then advance one
/// rung at a time while the evidence gate (enough reviews, accurate enough, and
/// already fast enough for the next rung) keeps passing.
pub(crate) fn current_rung(start: usize, pace: &DeckPace) -> usize {
    let mut rung = start;
    let acc = pace.accuracy();
    let mean = pace.mean_ms();
    while rung < PACE_RUNGS_MS.len() - 1 {
        let next = rung + 1;
        let fast_enough = mean <= PACE_RUNGS_MS[next] as f64;
        if pace.reviews >= PACE_MIN_REVIEWS && acc >= PACE_MIN_ACCURACY && fast_enough {
            rung = next;
        } else {
            break;
        }
    }
    rung
}

/// True when a topic's accuracy and speed already clear the next rung, but the
/// window does not yet hold enough reviews to lock the advance in. Used purely
/// to nudge the learner ("keep going, almost there").
pub(crate) fn ready_for_next(start: usize, pace: &DeckPace) -> bool {
    let rung = current_rung(start, pace);
    if rung >= PACE_RUNGS_MS.len() - 1 {
        return false;
    }
    pace.reviews > 0
        && pace.reviews < PACE_MIN_REVIEWS
        && pace.accuracy() >= PACE_MIN_ACCURACY
        && pace.mean_ms() <= PACE_RUNGS_MS[rung + 1] as f64
}

/// Weakness score used to order study; higher is surfaced sooner. The accuracy
/// gap dominates (a topic you get wrong needs work most), and being slow
/// relative to the current target adds to it. A topic with no recent reviews
/// scores as fully weak so neglected topics resurface.
pub(crate) fn weakness(pace: &DeckPace, target_ms: u32) -> f64 {
    let acc_gap = (1.0 - pace.accuracy() as f64).clamp(0.0, 1.0);
    let speed_pen = if target_ms > 0 && pace.reviews > 0 {
        (pace.mean_ms() / target_ms as f64 - 1.0).clamp(0.0, 1.0)
    } else {
        0.0
    };
    acc_gap + speed_pen
}

/// Human-readable label for a rung.
fn phase_label(rung: usize) -> String {
    match rung {
        0 => "Unlimited (build accuracy first)".to_string(),
        r if r == PACE_RUNGS_MS.len() - 1 => "90s goal".to_string(),
        r => format!("{}s target", PACE_RUNGS_MS[r] / 1000),
    }
}

impl Collection {
    /// Months until the stored exam date (config key `examDate`, epoch
    /// seconds), or `None` when no exam date is set.
    pub(crate) fn pace_exam_months_remaining(&self, now: TimestampSecs) -> Option<f64> {
        let exam: i64 = self.get_config_optional("examDate")?;
        let secs = (exam - now.0) as f64;
        // Average month length in seconds.
        Some(secs / (30.4375 * 86_400.0))
    }

    /// Recent pace, grouped by topic (deck), for the whole collection. Shared
    /// by the RPC and the pace-weakness review order.
    pub(crate) fn pace_by_deck(&mut self, now: TimestampSecs) -> Result<HashMap<DeckId, DeckPace>> {
        let cutoff_ms = (now.0 - PACE_WINDOW_DAYS * 86_400) * 1000;
        let rows = self.storage.pace_stats_by_deck(cutoff_ms)?;
        Ok(rows
            .into_iter()
            .map(|(did, reviews, correct, sum_ms)| {
                (
                    did,
                    DeckPace {
                        reviews,
                        correct,
                        sum_ms,
                    },
                )
            })
            .collect())
    }

    /// Per-topic pace for all cards matching `search` (empty = whole
    /// collection).
    pub fn mcat_pace(&mut self, search: &str) -> Result<McatPaceResponse> {
        let now = TimestampSecs::now();
        let months = self.pace_exam_months_remaining(now);
        let start = starting_rung(months);
        let cutoff_ms = (now.0 - PACE_WINDOW_DAYS * 86_400) * 1000;

        let guard = self.search_cards_into_table(search, SortMode::NoOrder)?;
        let cards = guard.col.storage.all_searched_cards()?;
        let revlog = guard.col.storage.get_revlog_entries_for_searched_cards()?;
        drop(guard);

        let deck_of: HashMap<CardId, DeckId> = cards.iter().map(|c| (c.id, c.deck_id)).collect();
        // Seed every matched topic so topics with cards but no recent reviews
        // still appear (as unlimited, awaiting data).
        let mut by_deck: HashMap<DeckId, DeckPace> = HashMap::new();
        for c in &cards {
            by_deck.entry(c.deck_id).or_default();
        }
        for e in &revlog {
            if e.id.0 < cutoff_ms || !(1..=4).contains(&e.button_chosen) {
                continue;
            }
            if let Some(&did) = deck_of.get(&e.cid) {
                let p = by_deck.entry(did).or_default();
                p.reviews += 1;
                if e.button_chosen >= 2 {
                    p.correct += 1;
                }
                p.sum_ms += e.taken_millis as i64;
            }
        }

        let mut topics: Vec<TopicPace> = Vec::with_capacity(by_deck.len());
        for (deck_id, pace) in by_deck {
            let topic = self
                .storage
                .get_deck(deck_id)?
                .map(|d| d.human_name())
                .unwrap_or_else(|| format!("[deck {}]", deck_id.0));
            let rung = current_rung(start, &pace);
            let target_ms = PACE_RUNGS_MS[rung];
            topics.push(TopicPace {
                deck_id: deck_id.0,
                topic,
                window_reviews: pace.reviews,
                accuracy: pace.accuracy(),
                mean_answer_ms: pace.mean_ms() as f32,
                target_ms,
                rung: rung as u32,
                phase: phase_label(rung),
                ready_for_next_rung: ready_for_next(start, &pace),
                weakness: weakness(&pace, target_ms) as f32,
            });
        }
        topics.sort_by(|a, b| a.topic.cmp(&b.topic));

        Ok(McatPaceResponse {
            topics,
            goal_ms: PACE_GOAL_MS,
            min_window_reviews: PACE_MIN_REVIEWS,
            min_accuracy: PACE_MIN_ACCURACY,
            exam_months_remaining: months.map(|m| m as f32).unwrap_or(-1.0),
            start_rung: start as u32,
            window_days: PACE_WINDOW_DAYS as u32,
        })
    }
}

#[cfg(test)]
mod test {
    use super::*;
    use crate::card::CardType;

    fn add_basic_note(col: &mut Collection, deck_id: DeckId) -> NoteId {
        let nt = col.get_notetype_by_name("Basic").unwrap().unwrap();
        let mut note = nt.new_note();
        col.add_note(&mut note, deck_id).unwrap();
        note.id
    }

    /// Log `n` reviews for the note's card with the given button (1-4) and
    /// answer time, timestamped `secs_ago` in the past so they fall
    /// inside/outside the recent window as needed. Writes revlog rows
    /// directly (no scheduling).
    fn log_reviews(
        col: &mut Collection,
        nid: NoteId,
        deck_id: DeckId,
        n: u32,
        button: u8,
        taken_ms: u32,
        secs_ago: i64,
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
        col.storage.update_card(&card).unwrap();
        let base = TimestampSecs::now().0 - secs_ago;
        for i in 0..n {
            let entry = crate::revlog::RevlogEntry {
                id: crate::revlog::RevlogId(base * 1000 + i as i64),
                cid: card.id,
                usn: Usn(-1),
                button_chosen: button,
                interval: 100,
                last_interval: 50,
                ease_factor: 2500,
                taken_millis: taken_ms,
                review_kind: crate::revlog::RevlogReviewKind::Review,
            };
            col.storage.add_revlog_entry(&entry, true).unwrap();
        }
    }

    #[test]
    fn starting_rung_tracks_exam_distance() {
        assert_eq!(starting_rung(None), 0);
        assert_eq!(starting_rung(Some(12.0)), 0);
        assert_eq!(starting_rung(Some(5.0)), 1);
        assert_eq!(starting_rung(Some(3.0)), 2);
        assert_eq!(starting_rung(Some(1.5)), 3);
        assert_eq!(starting_rung(Some(0.5)), 4);
    }

    #[test]
    fn rung_advances_only_when_fast_and_accurate() {
        // Accurate and fast, with enough reviews: climbs from unlimited.
        let good = DeckPace {
            reviews: 40,
            correct: 39,
            sum_ms: 40 * 80_000,
        };
        assert!(current_rung(0, &good) >= 1);

        // Fast but inaccurate: gate blocks the advance.
        let sloppy = DeckPace {
            reviews: 40,
            correct: 20, // 50% accuracy
            sum_ms: 40 * 10_000,
        };
        assert_eq!(current_rung(0, &sloppy), 0);

        // Accurate but slow: also blocked.
        let slow = DeckPace {
            reviews: 40,
            correct: 40,
            sum_ms: 40 * 400_000, // 400s mean, slower than the 300s first rung
        };
        assert_eq!(current_rung(0, &slow), 0);

        // Not enough reviews yet: stays put but flags "ready".
        let promising = DeckPace {
            reviews: 5,
            correct: 5,
            sum_ms: 5 * 60_000,
        };
        assert_eq!(current_rung(0, &promising), 0);
        assert!(ready_for_next(0, &promising));
    }

    #[test]
    fn weaker_topic_scores_higher() {
        let strong = DeckPace {
            reviews: 30,
            correct: 29,
            sum_ms: 30 * 60_000,
        };
        let weak = DeckPace {
            reviews: 30,
            correct: 12,
            sum_ms: 30 * 200_000,
        };
        assert!(weakness(&weak, PACE_GOAL_MS) > weakness(&strong, PACE_GOAL_MS));
    }

    #[test]
    fn empty_collection_reports_nothing() -> Result<()> {
        let mut col = Collection::new();
        let r = col.mcat_pace("")?;
        assert!(r.topics.is_empty());
        assert_eq!(r.goal_ms, PACE_GOAL_MS);
        assert_eq!(r.exam_months_remaining, -1.0);
        assert_eq!(r.start_rung, 0);
        Ok(())
    }

    #[test]
    fn groups_reviews_by_topic_over_window() -> Result<()> {
        let mut col = Collection::new();
        let bio = col.get_or_create_normal_deck("MCAT::Biochem")?.id;
        let phys = col.get_or_create_normal_deck("MCAT::Physics")?.id;

        // Biochem: 30 accurate, fast reviews inside the window.
        let n1 = add_basic_note(&mut col, bio);
        log_reviews(&mut col, n1, bio, 30, 3, 60_000, 3_600);
        // Physics: 30 inaccurate, slow reviews inside the window.
        let n2 = add_basic_note(&mut col, phys);
        log_reviews(&mut col, n2, phys, 30, 1, 240_000, 3_600);
        // An ancient Biochem review well outside the window must be ignored.
        log_reviews(
            &mut col,
            n1,
            bio,
            5,
            1,
            999_000,
            PACE_WINDOW_DAYS * 86_400 * 2,
        );

        let r = col.mcat_pace("")?;
        assert_eq!(r.topics.len(), 2);
        let biochem = &r.topics[0];
        assert_eq!(biochem.topic, "MCAT::Biochem");
        // The 5 ancient failures are outside the window, so only the 30 recent
        // accurate reviews count.
        assert_eq!(biochem.window_reviews, 30);
        assert!((biochem.accuracy - 1.0).abs() < 1e-6);

        let physics = &r.topics[1];
        assert_eq!(physics.topic, "MCAT::Physics");
        assert_eq!(physics.window_reviews, 30);
        assert!(physics.accuracy < 0.01);
        // The weak, slow topic must score as more in need of study.
        assert!(physics.weakness > biochem.weakness);
        Ok(())
    }
}
