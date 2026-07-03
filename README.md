# Speedrun MCAT — a Desktop + Mobile Study App on the Anki Engine

> **Exam: MCAT** (Medical College Admission Test) · scored **472–528**, four
> sections each scored **118–132**: Bio/Biochem (BBLS), Chem/Phys (CPBS),
> Psych/Soc (P/S), and Critical Analysis & Reasoning Skills (CARS).

This is an AGPL-licensed fork of [Anki](https://apps.ankiweb.net) that turns the
shared Anki engine into an **honest MCAT readiness tool**. It runs on the
**desktop** (forked Anki) and on a **phone companion** (AnkiDroid) that share the
_same Rust engine_ — the engine change ships to both, not a rewrite.

The guiding rule of this project is **honesty over flattery**: the app refuses to
show a readiness number until it has enough evidence, and every number it shows
comes with a range, the reasons behind it, and the rule for when it gives up and
shows nothing.

---

## 1. What this app measures

The MCAT asks for more than memory, so we keep three different questions separate
and never blend them into one flattering number:

| Question        | "Can the student…"                                     | Status                                                                                                                                                                        |
| --------------- | ------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Memory**      | …recall a fact right now?                              | **Built** — FSRS recall surfaced as an honest, ranged score (`mcat_deck_score` + `mcat_mastery`), shown on desktop **and** phone                                              |
| **Performance** | …answer a new, exam-style question that uses the fact? | **Built** — memory discounted by a *measured* transfer factor (`mcat_performance`); factor comes from the paraphrase test (challenge 7d), honest default 1.0 until measured   |
| **Readiness**   | …get what score today, and how sure are we?            | **Built** — projected score on the real **472–528** scale with a range (`mcat_readiness`), plus the in-engine give-up rule; shown on desktop **and** phone                    |

All three are computed in the **shared Rust engine** (so desktop and phone can never disagree) and rendered as three *separate* numbers, each with its own range — never blended.

### Product thesis (from the Brainlift)

Beyond memory, the longer-term goal is a **passage-timing and reasoning trainer**
for MCAT CARS and science passages: train comprehension and decision-making
_first_ with the timer hidden, then layer in pacing pressure (soft checkpoints,
per-passage targets, move-on prompts, strict timed practice) as test day
approaches. The learning-science rationale (test anxiety competes with working
memory; pacing is a trainable skill best added _after_ reading fluency) is
documented in the Brainlift. The current build lays the honest-measurement
foundation that the timing trainer will sit on top of.

---

## 2. The honesty rule (give-up rule), written down

The dashboard **abstains** from a readiness score until there is enough evidence,
and is explicit about every threshold:

- **Mastered** = a card whose _current_ FSRS recall is **≥ 90%**
  (`MASTERED_RETRIEVABILITY = 0.9`).
- **Give-up rule — no score shown** until there are at least **230 graded reviews**
  (`_MCAT_MIN_REVIEWS = 230`) **and** at least **50% topic coverage**
  (`_MCAT_MIN_TOPIC_COVERAGE = 0.5`). Below either line the panel says
  _"No score yet — not enough data"_ and names exactly which axis is short.
  Rationale: **230 ≈ the number of scored questions on one full-length MCAT**, so
  the app refuses to guess at readiness until the student has worked through at
  least a practice-test's worth of material — the same "take full-lengths before
  you trust a projected score" benchmark the field uses. At n = 230 the 95%
  Wilson band is already reasonably tight (±~0.065 at p = 0.5, vs ±~0.14 at 50),
  so the first score we ever show is honest *and* precise. The topic gate stops a
  deck that only drilled one subject from claiming whole-exam readiness.
- **Range, not a false point.** The score projects the observed mastery rate
  (mastered ÷ reviewed) over not-yet-reviewed cards and reports a **95% Wilson
  interval** (z = 1.96). The more of the deck is unseen, the wider the band; once
  every card is reviewed the range collapses to a single exact value.
- **Confidence label** from topic coverage: `< 60%` → Low, `< 85%` → Medium,
  else High.
- The panel also shows **topics reviewed/total**, **coverage %**,
  **reviewed/scorable counts**, **why the range is wide**, and the **best next
  topic to study** (lowest average recall).

All of this is computed by the engine; the UI only decides how to present it and
when to abstain.

---

## 3. The Rust engine change (Challenge 7a — Mastery query)

The required "real change inside Anki's Rust code" is a **mastery query**: a new
backend RPC that returns, per topic (deck), how many cards are mastered and the
average recall, computed in a single pass so it can power the dashboard on large
decks. A companion RPC reduces a deck to one **honest, ranged score**.

**New backend RPCs** (in `proto/anki/stats.proto`, on `StatsService`):

- `McatMastery(search)` → per-topic `total / rated / mastered / average_recall`,
  plus collection-wide totals and the mastered threshold.
- `McatDeckScore(search)` → `score` + `score_lower` / `score_upper` (Wilson),
  `scorable / rated / mastered / unseen` counts, and the mastered threshold used.
- `McatEngineStatus()` → a tiny end-to-end pipeline smoke check.

"Recall" reuses Anki's own FSRS path (`current_retrievability_seconds`), the same
code its stats graphs use, so the dashboard can never disagree with Anki's stats.
The queries are **strictly read-only** (no write transaction, no undo entry, no
mutation), so they are inherently undo-safe and cannot corrupt the collection.

Full rationale, undo-safety argument, and merge-risk analysis:
[`speedrun/rust-change.md`](speedrun/rust-change.md).

### Files touched (for future-merge tracking)

| File                            | Change                                     | Merge risk                        |
| ------------------------------- | ------------------------------------------ | --------------------------------- |
| `rslib/src/stats/mastery.rs`    | **New** — mastery query + 3 unit tests     | None (new file)                   |
| `rslib/src/stats/deck_score.rs` | **New** — honest deck score + 4 unit tests | None (new file)                   |
| `rslib/src/stats/mod.rs`        | `+mod mastery; +mod deck_score;`           | Very low                          |
| `rslib/src/stats/service.rs`    | `+` trait methods on `StatsService`        | Low (additive)                    |
| `rslib/src/storage/card/mod.rs` | `+ all_cards_count()` helper               | Low (additive)                    |
| `proto/anki/stats.proto`        | `+` 1 RPC group + messages                 | Low–medium (shared service block) |
| `qt/aqt/deckbrowser.py`         | `+ _render_mcat_panel()` dashboard card    | Low (additive method)             |
| `pylib/tests/test_stats.py`     | `+` 4 tests (incl. undo-safety)            | Low                               |

No generated files are hand-edited; the proto change regenerates the Rust,
Python, and TypeScript bindings automatically.

---

## 4. Architecture overview (two apps, one engine)

```
               ┌─────────────────────────────┐
               │   Core engine — Rust (rslib) │
               │  FSRS · scheduler · storage  │
               │  + McatMastery / McatDeckScore│
               └──────────────┬──────────────┘
                 protobuf RPC over both bridges
       ┌──────────────────────┴───────────────────────┐
       │                                               │
┌──────▼─────── Desktop ───────┐            ┌──────────▼──── Mobile ───────┐
│ pylib/rsbridge (PyO3)        │            │ Anki-Android-Backend         │
│   → Python (_backend)        │            │   → librsdroid.so (JNI)      │
│ qt/aqt  (PyQt GUI)           │            │ AnkiDroid (Kotlin UI)        │
│   → MCAT readiness dashboard │            │   → reviews on shared engine │
│ ts/     (Svelte web views)   │            │                              │
└──────────────────────────────┘            └──────────────────────────────┘
```

- The **same Rust crate** (`rslib`) is compiled into the desktop (`pylib/rsbridge`,
  PyO3) and into the Android build (`librsdroid.so`, JNI). The engine change is
  written once and available on both.
- The desktop dashboard (`qt/aqt/deckbrowser.py`) calls the new RPCs through the
  Python `_backend`; the phone reviews the same deck through the same engine.

### Repositories

| Repo                   | Path                                   | Role                                                 |
| ---------------------- | -------------------------------------- | ---------------------------------------------------- |
| `anki` (this fork)     | `C:\dev\speedrun\anki`                 | Desktop app + the Rust engine change                 |
| `Anki-Android-Backend` | `C:\dev\speedrun\Anki-Android-Backend` | Builds `librsdroid.so` from the shared `anki` engine |
| `Anki-Android`         | `C:\dev\speedrun\Anki-Android`         | AnkiDroid Kotlin UI (phone companion)                |

---

## 5. Building & running

All desktop tasks go through the project `justfile` (run `just --list` to see all
recipes). Do **not** call `./ninja` / `./run` directly.

### Desktop

```bash
just run            # build pylib + qt and launch Anki (debug)
just run-optimized  # release-optimized build
just check          # format + full build + checks (run before marking done)
```

Web views are served at `http://localhost:40000/_anki/pages/`. For live web
reloads during development, run `just web-watch` in a second terminal.

The MCAT readiness panel renders on the deck-browser home page once a deck is
loaded. Import an MCAT deck (`File → Import`) and review a few cards to see the
score appear (or the abstain message until the give-up thresholds are met).

### Mobile (Android companion)

The phone build reuses the shared Rust engine via the Android backend.

```powershell
# 1) Build the shared Rust backend (librsdroid) from the anki submodule
cd C:\dev\speedrun\Anki-Android-Backend
$env:ANDROID_NDK_HOME = "$env:LOCALAPPDATA\Android\Sdk\ndk\<version>"
$env:ANDROID_HOME      = "$env:LOCALAPPDATA\Android\Sdk"
$env:JAVA_HOME         = "C:\Program Files\Android\Android Studio\jbr"
cargo run -p build_rust

# 2) Build & install the AnkiDroid debug APK on a device/emulator
cd C:\dev\speedrun\Anki-Android
.\gradlew.bat :AnkiDroid:assemblePlayDebug
```

Then load the same MCAT deck and run a review session on the device/emulator.

> **Disk note:** a clean desktop + Android + Rust build needs several GB of free
> space and downloads toolchains (Gradle, Android SDK, NDK) on first run.

---

## 6. Tests

This change ships **7 Rust unit tests** and **4 Python integration tests**
(including an explicit undo-safety + integrity test).

```bash
# Rust unit tests for the engine change
cargo test -p anki stats::mastery      # 3 tests
cargo test -p anki stats::deck_score   # 4 tests
just test-rust                         # full Rust suite (incl. undo paths)

# Python integration tests (call the change end-to-end through the backend)
just test-py                           # full Python suite (includes test_stats.py)
```

> The Python tests exercise the new RPCs through the real backend, so they
> require the wheels to be built first — `just test-py` handles that for you.
> If the generated bindings are stale after a `.proto` change, run `just check`
> once to regenerate them, then re-run the tests.

Key tests:

- `rslib/src/stats/mastery.rs`: `empty_collection_reports_nothing`,
  `groups_by_topic_and_counts_mastery`, `search_filters_topics`.
- `rslib/src/stats/deck_score.rs`: `empty_collection_scores_zero_with_no_range`,
  `fully_reviewed_deck_has_exact_score_and_zero_range`,
  `unseen_cards_widen_the_range`, `lapsed_unmastered_cards_still_count_against_score`.
- `pylib/tests/test_stats.py`: `test_mcat_engine_status`, `test_mcat_mastery`,
  `test_mcat_deck_score`, `test_mcat_queries_are_undo_safe` (proves the RPCs
  create/clear no undo entry, undo of a real action still works, and
  `fix_integrity()` passes — no corruption).

---

## 7. Status (Wednesday milestone — core works, no AI)

**Done**

- Fork builds and runs from source (desktop) on the MCAT deck.
- Real Rust engine change (mastery query + honest deck score) with 7 Rust + 4
  Python tests, undo-safe and integrity-checked.
- Honest, ranged memory/readiness score with a written give-up rule.
- AnkiDroid companion builds and reviews the same deck on the shared engine.

**Not yet (later milestones)**

- AI features (card generation, provenance, evals) — intentionally **off** for
  this milestone.
- Two-way desktop⇄phone sync and offline conflict handling.
- Performance model (memory→novel-question bridge), section→scale mapping, and
  the passage-timing trainer.

No readiness number is shown unless the evidence thresholds above are met. Where
we cannot yet back a number, we say so rather than inventing one.

---

## License & credit

This project is a fork of **[Anki](https://github.com/ankitects/anki)** by
Ankitects Pty Ltd and contributors, and the Android companion builds on
**[AnkiDroid](https://github.com/ankidroid/Anki-Android)**.

Licensed under **AGPL-3.0-or-later** ([LICENSE](LICENSE)); some upstream Anki
components are under BSD-3-Clause. All original Anki/AnkiDroid copyright and
license notices are retained. Contributors: see [CONTRIBUTORS](CONTRIBUTORS).

Upstream Anki resources: [website](https://apps.ankiweb.net) ·
[dev docs](https://dev-docs.ankiweb.net) ·
[contributing guidelines](./docs/contributing.md) ·
[development guide](./docs/development.md).
