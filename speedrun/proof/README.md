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

# 4) Study-feature ablation (interleaving on/off/plain, 3-way, equal study time):
out\pyenv\Scripts\python.exe -m speedrun.ablation.run   # -> speedrun/ablation/artifacts/report_ablation.md

# 5) Memory-model calibration (reliability curve + Brier/log-loss on held-out reviews):
out\pyenv\Scripts\python.exe -m speedrun.calibration.calibrate  # -> speedrun/calibration/artifacts/report_calibration.md

# 6) Performance model: held-out accuracy on reworded exam-style questions (2-fold CV):
out\pyenv\Scripts\python.exe -m speedrun.performance.eval_performance  # -> speedrun/performance/artifacts/report_performance.md

# 7) Crash test: 20 mid-review hard-kills against the real engine, 0 corruption:
out\pyenv\Scripts\python.exe -m speedrun.crash.crash_test  # -> speedrun/crash/artifacts/report_crash.md

# 8) Live two-way sync + conflict (7b): 10+10 offline -> merge, same-card winner:
out\pyenv\Scripts\python.exe -m speedrun.sync.live_sync_test  # -> speedrun/sync/artifacts/report_sync_live.md

# 9) Corrupt deck / broken images can't crash or corrupt the app (real engine):
out\pyenv\Scripts\python.exe -m speedrun.imports.deck_resilience  # -> speedrun/imports/artifacts/report_imports.md

# 10) Garbled / broken AI output never reaches a student (control still passes):
out\pyenv\Scripts\python.exe -m speedrun.ai.garbled_test  # -> speedrun/ai/artifacts/report_garbled.md

# 11) Phone-side latency (cold start + memory + engine hot-path), needs emulator/device:
powershell -File speedrun\bench\phone_latency.ps1 -Iters 7  # -> speedrun/proof/phone-latency.md
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
| Two-way sync, no lost/double-counted | **Re-runnable harness:** [`../sync/artifacts/report_sync_live.md`](../sync/artifacts/report_sync_live.md) — 10+10 offline → **20 rows, 20 distinct, 0 dup**; live GUI/emulator run in [`../sync-test.md`](../sync-test.md) | DONE (automated + live) + USER (recording) |
| Offline review then sync | [`../sync/artifacts/report_sync_live.md`](../sync/artifacts/report_sync_live.md) (offline divergent reviews → merge on reconnect) + [`../sync-test.md`](../sync-test.md) | DONE (automated + live) |
| Phone shows 3 scores + give-up rule | **Verified on-device:** [`phone-engine.md`](phone-engine.md) + [`phone-scores.png`](phone-scores.png) — DeckPicker over `mcat_performance`/`mcat_readiness`, logcat `[phone/Rust] perf=0.63 readiness=507 hasScore=false`, give-up rule shown | DONE (emulator) + USER (record) |
| Three scores with ranges (desktop) | `qt/aqt/deckbrowser.py`; model pages in [`../models/`](../models/) | DONE |

## Feedback items (Wednesday MVP → Friday) → evidence

| Feedback area | Artifact | Status |
| --- | --- | --- |
| **Latency evidence (desktop)** | [`latency.md`](latency.md) / [`latency.json`](latency.json) — p50/p95/worst on 50k cards + memory footprint + reference machine | DONE |
| **Latency evidence (phone)** | [`phone-latency.md`](phone-latency.md) / [`phone-latency.json`](phone-latency.json) — cold start + PSS memory on the signed release build, engine hot-path (button 1.4 ms / next-card 0.3 ms) via shared binary; honest emulator (software-GPU) caveat on cold-start/frames | DONE (emulator) |
| **Build & test output** | [`rust-tests.log`](rust-tests.log) — **24 Rust tests passed, 0 failed** (stats module, incl. dashboard parity) · [`python-tests.log`](python-tests.log) — **11 Python tests passed** (`test_mcat_*` end-to-end + undo-safety) | DONE |
| **Mobile proof** | **Engine + 3 scores verified on emulator:** [`phone-engine.md`](phone-engine.md), [`phone-scores.png`](phone-scores.png) | DONE (emulator) + USER (record) |
| **Installer** | **Built:** `out/installer/dist/anki-26.05-win-x64.msi` (607 MB, SHA-256 `A288FDFA…013FC`); log [`installer-build.log`](installer-build.log); steps + hash in [`../packaging.md`](../packaging.md) | DONE (artifact) + USER (clean-device recording) |

## Sunday deliverables → evidence

| Sunday requirement | Artifact | Status |
| --- | --- | --- |
| Study feature tested with 3 builds, equal study time (§8) | [`../ablation/artifacts/report_ablation.md`](../ablation/artifacts/report_ablation.md) — interleave on/off/plain (300 sim students, equal 320-rep budget), pre-registered metric + failure rule: **interleave ON−OFF = +5.1 pp** (95% CI **[+4.8, +5.3]**) → SUPPORTED; honest nulls **+0.0 pp** on single-topic & non-confusable | DONE |
| Score mapping written down, with a range (§9 step 3) | [`../models/readiness-model.md`](../models/readiness-model.md), [`../models/performance-model.md`](../models/performance-model.md) — `projected = 472 + performance·(528−472)` with the range carried through; explicitly **not** claimed calibrated to real test-taker outcomes | DONE |
| Both apps run with AI off and still score | scoring path never calls AI; `run all` needs no key | DONE |
| Sync conflict merge correct + documented | **Live end-to-end:** [`../sync/artifacts/report_sync_live.md`](../sync/artifacts/report_sync_live.md) (same card both offline → phone's later `Easy` wins, both revlog rows kept); + [`../sync-test.md`](../sync-test.md) + [`../robustness/artifacts/report_sync_robustness.md`](../robustness/artifacts/report_sync_robustness.md) | DONE |
| Honest reporting incl. results that didn't work | dashboard first-load now **under target** after the one-scan `mcat_dashboard` optimization (3.8× faster), but the stricter <500 ms *refresh* target is still over on 50k cards and named as the single-scan floor in [`latency.md`](latency.md); `transfer_measured=false`; ablation null conditions | DONE |
| Memory model calibrated: chart + Brier/log-loss on held-out reviews (§9 step 1) | [`../calibration/artifacts/report_calibration.md`](../calibration/artifacts/report_calibration.md) + [`reliability.svg`](../calibration/artifacts/reliability.svg) — **Brier 0.1329 · log-loss 0.4087 · ECE 0.0106**, observed recall **76.7%** vs predicted **75.7%** on **4,000** held-out reviews (beats the 0.1788 base-rate Brier); reliability curve; honest synthetic fallback (deck has no multi-day review history yet) | DONE (harness) |
| Performance model: accuracy on held-out exam-style questions (§9 step 2) | [`../performance/artifacts/report_performance.md`](../performance/artifacts/report_performance.md) — 2-fold CV on the 30-card paraphrase set, transfer factor **0.801** (paraphrase 0.796), **78.3% held-out accuracy**, bridge beats memory-only on Brier (**0.2090 vs 0.2167**) and log-loss | DONE |
| Crash test (§7g): kill mid-review 20×, zero corruption | [`../crash/artifacts/report_crash.md`](../crash/artifacts/report_crash.md) — **20 mid-review hard-kills, 0 corrupted collections, 0 committed reviews lost** (real engine); shared engine ⇒ same guarantee on phone | DONE (desktop) |
| Packaged desktop installer (clean-device recording) | **Built:** `out/installer/dist/anki-26.05-win-x64.msi` (607 MB, SHA-256 `A288FDFA…013FC`); [`../packaging.md`](../packaging.md) | DONE (artifact) + USER (recording) |
| Signed phone APK (clean-device recording) | **Built + signed + runs:** `AnkiDroid-play-x86_64-release.apk` (86.3 MB, SHA-256 `9F454499…5AD02`), `apksigner` → **Verified v2**; installed on emulator + launched ([`apk-release-run.png`](apk-release-run.png)); build in [`../packaging.md`](../packaging.md) (x86_64-only, lint gate skipped, minify off — noted) | DONE (artifact) + USER (recording) |
| Demo video (3–5 min) | script prepared in chat | USER |

### Sunday models & evidence — headline numbers (at a glance)

| Model / test | Headline result | Honest caveat |
| --- | --- | --- |
| **Memory** (calibration, §9.1) | Brier **0.1329**, log-loss **0.4087**, ECE **0.0106**; observed **76.7%** vs predicted **75.7%** over **4,000** held-out reviews → **well calibrated** (beats 0.1788 base-rate). | Synthetic stream (deck has no multi-day history yet); pipeline runs on real data with `--collection PATH`, no code change. |
| **Performance** (bridge, §9.2, 7d) | Transfer factor **0.801** (2-fold CV) / **0.796** paraphrase → **78.3%** held-out accuracy; beats memory-only on Brier (**0.2090 vs 0.2167**). | Illustrative synthetic attempts (`measured=false`); does not set the engine factor. |
| **Readiness** (mapping, §9.3) | `projected = 472 + performance·(528−472)` on the real **472–528** scale, range carried through; give-up rule **≥230 graded reviews AND ≥50% coverage**. | Deliberately **not** claimed calibrated to real practice-test outcomes — we don't have paired data. |
| **Study feature** (interleaving, §8) | 3-way, equal time: interleave ON−OFF **+5.1 pp** (95% CI **[+4.8, +5.3]**) → **SUPPORTED**; nulls **+0.0 pp** where theory predicts none. | Transparent mechanism simulation, not a human study — labeled as such. |

---

## The Rust engine change (20% of the grade)

- Code: `rslib/src/stats/{deck_score,mastery,performance,readiness,pace,dashboard}.rs`
- Wiring: `proto/anki/stats.proto`, `rslib/src/stats/service.rs`, exposed to Python via `_backend`.
- Performance: the `mcat_dashboard` RPC computes all five scores from **one shared
  card+revlog scan** instead of five independent full-collection scans (readiness
  no longer re-runs performance), a **3.8× faster** dashboard with byte-identical
  output (parity test `dashboard_matches_individual_rpcs`). See [`latency.md`](latency.md).
- Tests: **24 Rust unit tests** across the stats module (incl. the dashboard
  parity test) + **11 Python** end-to-end
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
- **Corrupt deck / broken images** (real engine): [`../imports/artifacts/report_imports.md`](../imports/artifacts/report_imports.md) — corrupt collection refused, corrupt/missing `.apkg` rejected as a transaction (live collection unchanged, integrity `ok`), broken-image deck reported + still renders; valid `.apkg` control still imports. **PASS**
- **Garbled / broken AI output** (offline / rate-limited / prompt-injected model): [`../ai/artifacts/report_garbled.md`](../ai/artifacts/report_garbled.md) — 17 hostile raw responses through the real parse→gate path, **0 reach a student** (5 dropped at parse, 12 blocked), valid control still passes. **PASS**
- 50k-card deck stress: [`latency.md`](latency.md) (hot-path + memory pass; dashboard first-load under target after the one-scan optimization, refresh floor named).

---

### Honesty notes
- The dashboard was the one over-target number. It is now optimized: a single
  `mcat_dashboard` RPC does one shared card+revlog scan instead of ~nine, making
  the dashboard **~3.8× faster** and bringing **first load under the <1 s
  target**. The stricter <500 ms *refresh* target is still over on 50k cards —
  a single full scan at that size is the floor — and we report that number
  rather than hiding it. The interactive review hot-path and memory footprint
  pass. See [`latency.md`](latency.md).
- Sync correctness is documented + engine-verified; the phone→desktop
  *recording* and the phone three-score panel are the remaining USER/BUILD items.
