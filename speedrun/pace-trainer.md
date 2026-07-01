# Rust Engine Change — Passage-Pace Trainer (first-class timing in the shared engine)

**Exam:** MCAT · **Change chosen:** _Pace model + a new review order_ — the engine
learns how fast and how accurately each topic is answered, sets a per-topic time
**target** that only tightens as the learner improves, and can **reorder the
review queue** so the weakest/slowest topics come first.

The point of the feature is that timing is **not** a cosmetic add-on bolted onto
the UI. A timer widget that just counts seconds would live in the app and would
have to be reinvented for the phone. Instead the pace signal is computed in
`rslib` from data Anki already stores, and it feeds a real scheduler decision
(what card you see next). That is what makes it "first-class".

## What it does

A new RPC `McatPace(search)` returns, per topic (deck), over a recent window:

- `window_reviews` — graded reviews in the last `PACE_WINDOW_DAYS` (30) days
- `accuracy` — fraction answered `Good`/`Easy` (button ≥ 2)
- `mean_answer_ms` — mean answer time from `revlog.taken_millis` (data Anki
  already records for every review)
- `rung` / `target_ms` — the topic's current step on the pace ladder and its
  time target (`0` = unlimited, i.e. no timer)
- `phase` — a human label ("Unlimited", "5 min", …, "Goal 90s")
- `ready_for_next_rung` — whether the advancement gate is currently satisfied
- `weakness` — a 0–1 score combining inaccuracy and slowness (used for ordering)

plus collection-wide fields: `goal_ms` (90 000), `min_window_reviews`,
`min_accuracy`, `window_days`, `start_rung`, and `exam_months_remaining`
(`-1` when no exam date is set).

### The ladder and the rule (stated, not hidden)

`PACE_RUNGS_MS = [unlimited, 300 s, 180 s, 120 s, 90 s]`. The **90 s goal** is the
last rung.

- **Starting rung** is chosen from how far away the exam is (`examDate` in the
  collection config): > 6 months → unlimited; then progressively tighter as the
  date approaches. With no exam date the ladder starts at unlimited.
- **A topic only advances to a shorter target when it has earned it** — all of:
  1. at least `PACE_MIN_REVIEWS` (20) recent reviews,
  2. accuracy ≥ `PACE_MIN_ACCURACY` (0.85), **and**
  3. mean answer time already inside the next rung.

  So the target never shrinks because a deadline is looming; it shrinks only when
  the learner is demonstrably faster **and** still accurate. If accuracy drops,
  the topic stops advancing.

### The scheduler hook

A new review order `REVIEW_CARD_ORDER_PACE_WEAKNESS` sorts the day's review queue
by descending `weakness`, so the weakest/slowest topics are studied first. This
is the "first-class" part: the pace model changes **what you review next**, not
just what a widget displays.

## Why this belongs in Rust, not Python/JS

1. **One engine, two apps.** The desktop app and the phone companion must _share_
   the engine. A pace model and review order in `rslib` ship to desktop (via
   `pylib/rsbridge`) **and** to AnkiDroid (via the same Rust backend) with no
   per-platform reimplementation. A timer written in `aqt` Python or reviewer JS
   would be desktop-only and would have to be rewritten for the phone — the exact
   "reimplement the scheduler per platform" anti-pattern the brief forbids.
2. **It's a scheduler decision, and the scheduler is in Rust.** Reordering the
   review queue happens in `rslib/src/scheduler/queue/builder`. Timing can only
   influence "what's next" if it lives where the queue is built.
3. **Data locality / correctness.** The inputs (`revlog.taken_millis`, button,
   the card→deck mapping) are owned by the Rust SQLite layer. Aggregating them in
   one pass next to the data avoids pulling every revlog row across the IPC
   boundary, and reuses the numbers Anki already trusts (no second, drifting
   definition of "answer time").

## Undo safety & no corruption

The change is **strictly read-only** on the query path:

- `McatPace` runs `SELECT`s only (aggregate `revlog` joined to `cards`, read deck
  names, read one config value) and aggregates in memory.
- It opens **no write transaction**, mutates **no** card/note/deck/revlog rows,
  and creates **no undo entry** — nothing to undo, no path to corruption.
- The review-order sort runs during queue building (already a read-only,
  rebuildable structure) and only _reorders_ the in-memory queue; it writes
  nothing.
- Setting the exam date uses the normal `set_config` path with `undoable=False`,
  which preserves existing undo history rather than clearing it.

Evidence: `pylib` undo test `test_mcat_pace_is_undo_safe` answers a card, calls
`mcat_pace`, asserts the undo entry is unchanged, undoes the review, and passes a
`fix_integrity` check.

## Tests

- **6 Rust unit/integration tests** (`cargo test -p anki` → all pass):
  - `rslib/src/stats/pace.rs`:
    - `empty_collection_reports_nothing`
    - `groups_reviews_by_topic_over_window`
    - `weaker_topic_scores_higher`
    - `rung_advances_only_when_fast_and_accurate`
    - `starting_rung_tracks_exam_distance`
  - `rslib/src/scheduler/queue/builder/mod.rs`:
    - `pace_weakness_order_surfaces_weak_topic_first` — builds a real queue with
      one fast/accurate topic and one slow/inaccurate topic and asserts the weak
      topic's card is scheduled **first**. This proves the timing signal actually
      drives the scheduler, not just the display.
- **2 Python tests** (`pylib/tests/test_stats.py`):
  - `test_mcat_pace` — end-to-end RPC: empty state, one graded review produces a
    topic with accuracy/target, and setting `examDate` tightens the starting rung.
  - `test_mcat_pace_is_undo_safe` — read-only / undo-safety proof (above).

Proof output saved to `proof/pace-cargo-check3.txt` (whole-workspace `cargo
check`, EXIT 0) and `proof/pace-rust-tests.txt` (6 passed, 0 failed).

## Desktop UI (presentation only — the model stays in Rust)

- **Home page** (`qt/aqt/deckbrowser.py`): a "Pace Trainer" card driven entirely
  by `mcat_pace`. It prompts for the MCAT exam date when unset, shows
  months-remaining + starting target + the 90 s goal, and lists each topic's
  recent reviews / accuracy / mean time / target / phase, sorted weakest-first
  (the same signal the review order uses). Fails safe to an empty string.
- **Reviewer** (`qt/aqt/reviewer.py`): a small per-card overlay showing
  time-to-target for the current card's topic, with a soft "move on" cue once the
  target is exceeded. Hidden when the topic's target is unlimited. Injected as
  inline JS so no web-bundle rebuild is required.

Both are strictly display; every number and threshold comes from the Rust RPC.

## Files touched & future-merge difficulty

| File                                       | Change                                                                     | Merge risk                                |
| ------------------------------------------ | -------------------------------------------------------------------------- | ----------------------------------------- |
| `rslib/src/stats/pace.rs`                  | **New file** — pace model, ladder, gate, weakness, RPC impl + tests        | **None** (no upstream file)               |
| `rslib/src/stats/mod.rs`                   | `mod pace;` → `pub(crate) mod pace;`                                       | **Very low**                              |
| `rslib/src/stats/service.rs`               | +1 trait method (`mcat_pace`) appended                                     | **Low** (additive)                        |
| `rslib/src/storage/revlog/mod.rs`          | +`pace_stats_by_deck()` read query                                         | **Low** (additive method)                 |
| `rslib/src/storage/card/mod.rs`            | `review_order_sql`: map `PaceWeakness` → gather in Day order               | **Low** (one `match`)                     |
| `rslib/src/scheduler/queue/builder/mod.rs` | post-gather `sort_review_by_pace_weakness` gated on the new order + test   | **Low–medium** (touches queue build tail) |
| `rslib/src/scheduler/fsrs/simulator.rs`    | +`PaceWeakness` arm in an existing `match` (no pace data in the simulator) | **Low**                                   |
| `proto/anki/stats.proto`                   | +1 RPC + request/response messages                                         | **Low–medium** (shared service block)     |
| `proto/anki/deck_config.proto`             | +`REVIEW_CARD_ORDER_PACE_WEAKNESS = 13` enum value                         | **Low**                                   |
| `ts/routes/deck-options/choices.ts`        | +1 dropdown entry for the new order                                        | **Low**                                   |
| `qt/aqt/deckbrowser.py`                    | Pace panel + exam-date link handlers (display)                             | **Low**                                   |
| `qt/aqt/reviewer.py`                       | Per-card target overlay (display)                                          | **Low**                                   |
| `pylib/tests/test_stats.py`                | +2 tests appended                                                          | **Low**                                   |

**Design choice that minimizes merge pain:** all engine logic lives in a _new_
module (`pace.rs`); upstream files only receive small additive hooks, and no
generated files were hand-edited — the proto change regenerates the Rust, Python,
and TS bindings automatically.

## Scope honesty

- **In scope / done:** the Rust pace model + advancement gate, the
  `PaceWeakness` review order that reorders the real queue, the `McatPace` RPC,
  exam-date-driven starting rung, desktop home + reviewer UI, and the tests above.
- **Deliberately simple:** "topic" == deck (same convention as the mastery
  change); the ladder is a fixed 5-rung table rather than a continuous curve; the
  reviewer overlay is a soft cue and never blocks answering or changes FSRS
  intervals.
- **Not yet done (Phase 3):** the AnkiDroid pace panel + reviewer target. The
  _engine_ already ships to the phone (same `rslib` path as the mastery change);
  only the mobile presentation layer remains.
