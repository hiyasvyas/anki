# Proof index — MCAT Speedrun

Exam: **MCAT** (472–528; four sections 118–132). License: AGPL-3.0-or-later, credit to Anki.

This folder is the **single place to verify every claim**. Each row points to a
committed artifact and, where relevant, the one command that regenerates it.
Status: **DONE** (artifact committed) · **BUILD** (needs the shared build idle) ·
**USER** (needs a human recording).

---

## Fastest way to verify (no build required)

```powershell
# from repo root C:\dev\speedrun\anki
$env:PYTHONPATH = "$PWD\out\pylib"

# 1) AI is checked, beats baselines, clean of leakage (no API key needed):
out\pyenv\Scripts\python.exe -m speedrun.ai.run all      # -> speedrun/ai/artifacts/SUMMARY.md

# 2) Latency / memory on a 50k-card deck (its own throwaway collection):
out\pyenv\Scripts\python.exe speedrun\bench\latency.py   # -> speedrun/proof/latency.md

# 3) Coverage map of the real deck vs the MCAT outline:
out\pyenv\Scripts\python.exe speedrun\coverage\coverage_map.py  # -> speedrun/coverage/coverage_report.md
```

---

## Friday deliverables → evidence

| Friday requirement | Artifact | Status |
| --- | --- | --- |
| AI note: what/why/skipped | [`../ai-note.md`](../ai-note.md) | DONE |
| Every AI output traces to a named source | `../ai/artifacts/generated.json` (`source_id` + `citation`), sources in `../ai/sources/` | DONE |
| Held-out eval: accuracy + wrong-rate + declared cutoff | [`../ai/artifacts/report_eval.md`](../ai/artifacts/report_eval.md), [`SUMMARY.md`](../ai/artifacts/SUMMARY.md) — 100% acc / 0% wrong (cutoffs 80/10) | DONE |
| Beats a simpler method (keyword/vector) | [`../ai/artifacts/report_baselines.md`](../ai/artifacts/report_baselines.md) — AI 90% vs TF-IDF 0% vs vector 0% | DONE |
| Leakage check clean (7e) | [`../ai/artifacts/report_leakage.md`](../ai/artifacts/report_leakage.md) — CLEAN | DONE |
| Paraphrase / performance≠memory (7d) | [`../ai/artifacts/report_paraphrase.md`](../ai/artifacts/report_paraphrase.md) — recall 90% vs reworded 71.7% → gap 18.3% | DONE |
| Gold-set counts (7f) | [`SUMMARY.md`](../ai/artifacts/SUMMARY.md) — 45 correct / 0 wrong / 5 bad-teaching | DONE |
| App still scores with AI off | `run all` runs with no API key; scores come from the Rust engine | DONE |
| Two-way sync, no lost/double-counted | [`../sync-test.md`](../sync-test.md) — 9+9 offline → 18, 0 dup | DONE (method) + USER (recording) |
| Offline review then sync | [`../sync-test.md`](../sync-test.md) | DONE (method) + USER (recording) |
| Phone shows 3 scores + give-up rule | AnkiDroid three-score panel over `mcat_performance`/`mcat_readiness` | BUILD + USER |
| Three scores with ranges (desktop) | `qt/aqt/deckbrowser.py`; model pages in [`../models/`](../models/) | DONE |

## Feedback items (Wednesday MVP → Friday) → evidence

| Feedback area | Artifact | Status |
| --- | --- | --- |
| **Latency evidence** | [`latency.md`](latency.md) / [`latency.json`](latency.json) — p50/p95/worst on 50k cards + memory footprint + reference machine | DONE |
| **Build & test output** | [`rust-tests.log`](rust-tests.log) — **22 Rust tests passed, 0 failed** (stats module) · [`python-tests.log`](python-tests.log) — **11 Python tests passed** (`test_mcat_*` end-to-end + undo-safety) | DONE |
| **Mobile proof** | phone review + three-score screenshots/recording | USER (emulator + record) |
| **Installer** | `just installer` → `out/installer/dist/`; steps in [`../packaging.md`](../packaging.md) | BUILD |

---

## The Rust engine change (20% of the grade)

- Code: `rslib/src/stats/{deck_score,mastery,performance,readiness,pace}.rs`
- Wiring: `proto/anki/stats.proto`, `rslib/src/stats/service.rs`, exposed to Python via `_backend`.
- Tests: **22 Rust unit tests** across the stats module + **11 Python** end-to-end
  incl. undo-safety in `pylib/tests/test_stats.py` (`test_mcat_*`,
  `test_mcat_queries_are_undo_safe`). Captured in [`rust-tests.log`](rust-tests.log)
  and [`python-tests.log`](python-tests.log). Reproduce:
  ```powershell
  $env:PYTHONPATH="$PWD\out\pylib"
  # Python end-to-end (uses the built backend, no recompile):
  cd pylib; out\..\out\pyenv\Scripts\python.exe -m pytest tests\test_stats.py -v; cd ..
  # Rust (reuse ninja's warm target dir to avoid a cold rebuild):
  $env:CARGO_TARGET_DIR="$PWD\out\rust"; cargo test -p anki stats::
  ```
- One-pager on why-in-Rust + touched files: [`../rust-change.md`](../rust-change.md), [`../pace-trainer.md`](../pace-trainer.md).
- Ships to the phone too (shared engine): built into `librsdroid.so`.

## The three score models (one page each)

- Memory: [`../models/memory-model.md`](../models/memory-model.md)
- Performance: [`../models/performance-model.md`](../models/performance-model.md)
- Readiness: [`../models/readiness-model.md`](../models/readiness-model.md)
- Why each design choice exists, with sources: [`../evidence.md`](../evidence.md)

## Robustness / adversarial (section 10 "we will try to break it")

- Contradictions, rushed reviews, sync robustness: [`../robustness/artifacts/`](../robustness/artifacts/)

---

### Honesty notes
- The latency artifact reports an **over-target** dashboard aggregate on 50k
  cards and names the root cause; the interactive review hot-path and memory
  footprint pass. We report the number that did not meet target rather than
  hiding it. See [`latency.md`](latency.md).
- Sync correctness is documented + engine-verified; the phone→desktop
  *recording* and the phone three-score panel are the remaining USER/BUILD items.
