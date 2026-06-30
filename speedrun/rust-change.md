# Rust Engine Change — Mastery Query (Challenge 7a)

**Exam:** MCAT · **Change chosen:** *Mastery query* — a backend call that returns,
per topic, how many cards are mastered and the average recall, fast enough to
power a dashboard on 50,000 cards.

## What it does

A new RPC `McatMastery(search)` returns, for every deck ("topic") whose cards
match a search:

- `total_cards` — cards in the topic
- `rated_cards` — cards with an FSRS memory state (reviewed at least once)
- `mastered_cards` — cards whose current FSRS recall ≥ `0.9`
- `average_recall` — mean FSRS retrievability (0–1) over the rated cards

plus collection-wide totals and the `mastered_threshold` used. "Recall" is the
card's current FSRS retrievability, computed from its memory state, decay, and
time since last review — the same engine path Anki's own graphs use, so the
dashboard can never disagree with Anki's stats.

### Definitions (stated, not hidden)

- **Mastered** = current recall ≥ `0.9` (`MASTERED_RETRIEVABILITY`).
- **Average recall** is taken over *rated* cards only. New/unseen cards have no
  memory state, so they are counted in `total_cards` but excluded from the
  average — averaging them against a default would flatter the number and lie
  about how well the deck is actually known.

## Why this belongs in Rust, not Python

1. **One engine, two apps.** The brief requires the desktop app and the phone
   companion to *share* the engine, not reimplement it. Logic placed in `rslib`
   ships to the desktop (through `pylib/rsbridge`) **and** to AnkiDroid (through
   the same Rust backend) for free. The same RPC written in the `aqt` Python
   layer would run on desktop only and would have to be rewritten for the phone
   — exactly the "rewriting the scheduler in JS/Swift" anti-pattern the brief
   forbids.
2. **Performance on 50k cards.** The dashboard target is p95 < 1 s. Computing
   FSRS retrievability per card is a tight numeric loop that lives best next to
   the data. In Rust it is a single pass over the collection using the native
   `fsrs` crate. In Python it would mean pulling every card row across the
   protobuf/IPC boundary (50k×) and there is no native FSRS in the Python layer
   — orders of magnitude more overhead.
3. **Correctness / no drift.** Retrievability is *already* computed in Rust
   (`fsrs::FSRS::current_retrievability_seconds`, used by the stats graphs).
   Reusing that path guarantees the mastery numbers match Anki's existing stats
   instead of forking a second, slightly-different implementation in Python.
4. **Data locality.** The inputs (cards, `memory_state`, `decay`,
   `last_review_time`) are owned by the Rust SQLite layer. The query belongs
   where the data is.

## Undo safety & no corruption

The change is **strictly read-only**:

- It runs `SELECT`s only (search into the temp `search_cids` table, read cards,
  read deck names) and aggregates in memory.
- It opens **no write transaction**, mutates **no** card/note/deck/revlog rows,
  and creates **no undo entry** — so there is literally nothing to undo and no
  path to collection corruption.
- Unlike the pre-existing `card_stats` (which lazily writes `last_review_time`),
  the mastery query deliberately stays side-effect-free: elapsed time is derived
  read-only via `Card::seconds_since_last_review`.

Evidence: all 123 `pylib` tests pass (including the undo tests) with the rebuilt
engine; the 3 Rust unit tests for this change pass. Full proof command:
`just test-rust` (Rust suite, incl. undo) + `just test-py`.

## Tests

- **3 Rust unit tests** — `rslib/src/stats/mastery.rs`:
  - `empty_collection_reports_nothing`
  - `groups_by_topic_and_counts_mastery`
  - `search_filters_topics`
  - Run: `cargo test -p anki stats::mastery` → **3 passed**
- **1 Python test (calls the change end-to-end)** —
  `pylib/tests/test_stats.py::test_mcat_mastery`
  - Run: `tools\ninja check:pytest:pylib` → **123 passed** (incl. this test)

## Files touched (upstream) & future-merge difficulty

| File | Change | Merge risk |
|------|--------|-----------|
| `rslib/src/stats/mastery.rs` | **New file** — implementation + tests | **None** (no upstream file to conflict) |
| `rslib/src/stats/deck_score.rs` | **New file** — honest deck score + tests | **None** (no upstream file to conflict) |
| `rslib/src/stats/mod.rs` | +1 line: `mod mastery;` | **Very low** |
| `rslib/src/stats/service.rs` | +2 trait methods appended to `StatsService impl` | **Low** (additive; only conflicts if upstream edits the same impl tail) |
| `rslib/src/storage/card/mod.rs` | +`all_cards_count()` helper | **Low** (additive method) |
| `proto/anki/stats.proto` | +1 RPC on `StatsService`, +3 messages appended | **Low–medium** (one shared service block; resolve by re-adding our RPC line) |
| `pylib/tests/test_stats.py` | +2 tests appended | **Low** |

**Design choice that minimizes merge pain:** all logic lives in a *new* module
(`mastery.rs`); upstream files only receive small additive hooks. No generated
files were hand-edited — the proto change regenerates the Rust (`anki_proto`),
Python (`stats_pb2`, `_backend_generated.py`), and TS bindings automatically.

## Honest deck score — range + give-up rule (Challenge: memory model)

Building on the same recall path, a second RPC `McatDeckScore(search)` reduces a
deck to **one number you can defend**, with two pieces of honesty baked in so it
can neither be gamed nor mistaken for false precision.

- **Score** (0–1): the point estimate of true mastery over the *scorable* cards.
  It projects the observed mastery rate (mastered ÷ reviewed) onto cards not yet
  reviewed, so it equals `mastered/scorable` exactly once the deck is fully
  reviewed.
- **Range** (`score_lower`/`score_upper`): a 95% **Wilson** interval on the
  reviewed sample, projected over the unseen cards. The width is driven entirely
  by how much of the deck is still unreviewed — review 5 of 500 cards and the
  band is wide; review everything and it **collapses to a single value**. The
  score refuses to claim precision it hasn't earned.
- **Give-up rule**: a card that has lapsed `GIVE_UP_LAPSES` (= 8) times and is
  still not mastered is **excluded** from the score and reported separately as
  `give_up_cards`. Without this, a few un-learnable leeches would permanently
  cap the score, tempting you to quietly suspend them (gaming it) or give up on
  the whole deck. Excluding them *and showing the count* keeps the score both
  reachable and honest.

Like the mastery query it is a strictly read-only pass (no write transaction, no
undo entry, no mutation), so it is inherently undo-safe.

**Tests** — `rslib/src/stats/deck_score.rs` (4 Rust unit tests):
`empty_collection_scores_zero_with_no_range`,
`fully_reviewed_deck_has_exact_score_and_zero_range`,
`unseen_cards_widen_the_range`, `give_up_cards_are_excluded_but_counted`; plus
`pylib/tests/test_stats.py::test_mcat_deck_score` end-to-end.
Run: `cargo test -p anki stats::deck_score` → **4 passed**;
`tools\ninja check:pytest:pylib` → **124 passed**.

## Ships to the phone too — built and proven on the AnkiDroid build

Because the change lives in `rslib`, the same RPC ships to AnkiDroid through the
shared Rust backend (`rsdroid` / `librsdroid.so`) with **no mobile-specific
engine code**. This was not just asserted — it was built and run on a phone
(emulator) build:

1. **Built the backend from this fork.** In `Anki-Android-Backend`, the `anki`
   submodule (26.05b1, the version that repo targets) was overlaid with the six
   changed files above and built with `cargo run -p build_rust`
   (NDK r29, Rust 1.92.0, `cargo-ndk`, `x86_64-linux-android`). The `anki` crate
   and `rsdroid` compiled cleanly for Android, and proto codegen produced the
   Java/Kotlin bindings (`McatDeckScoreRequest/Response`,
   `GeneratedBackend.mcatDeckScore(search)`) → `rsdroid-release.aar`.
2. **Linked it into AnkiDroid.** Set `local_backend=true` in
   `AnkiDroid/local.properties` so the app consumes the locally-built AAR instead
   of the published one, then built `:AnkiDroid:assemblePlayDebug` (x86_64).
3. **Ran it on the device.** Installed on the emulator with the full 2887-card
   MCAT deck loaded. A debug-only hook in `DeckPicker.updateDeckList()` calls
   `CollectionManager.getBackend().mcatDeckScore("")`. Logcat proof:

   ```
   I DeckPicker$updateDeckList: MCAT-SPEEDRUN McatDeckScore[phone/Rust]
     score=0.0 range=[0.0,1.0] scorable=2887 rated=0 mastered=0 unseen=2887 giveUp=0
   ```

   i.e. the honest-deck-score model executed inside `librsdroid.so` on the phone:
   2887 scorable cards, all unseen → score 0.0 with the maximum `[0.0, 1.0]`
   confidence band (the model correctly abstains with no review data).

### Files touched outside `rslib` for the phone build (merge difficulty)

| File / repo | Change | Merge risk |
|------|--------|-----------|
| `Anki-Android-Backend/anki` (submodule) | Overlaid the 6 `rslib`/proto files above | **None** — same additive change; regenerate, don't hand-merge |
| `Anki-Android/AnkiDroid/local.properties` | `local_backend=true` (local-only, gitignored) | **None** — not committed |
| `Anki-Android/AnkiDroid/build.gradle` | Restrict ABI split to `x86_64` (build-time, emulator-only) | **None** — local convenience, revert for release |
| `Anki-Android/.../libanki/Deck.kt` | +1 `when` branch for the new `Order.RELATIVE_OVERDUENESS` variant | **Low** — only needed because this AnkiDroid checkout predates the 26.05 backend; upstream's matching checkout already handles it |
| `Anki-Android/.../DeckPicker.kt` | Debug-only logcat hook calling the new RPC | **None** — verification scaffold, not part of the engine change |

The only *non-trivial* mobile-side edit (`Deck.kt`) is a symptom of pairing a
newer engine with an older app checkout, not of the change itself — on a matched
AnkiDroid/backend pair it disappears entirely.
