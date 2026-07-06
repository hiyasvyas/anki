# Latency benchmark (section 10 speed targets / challenge 7h)

Measured with `speedrun/bench/latency.py` against the shared Rust engine (the backend embedded by both the desktop app and the phone build), on a synthetic throwaway collection. Re-runnable by anyone:

```powershell
$env:PYTHONPATH = "$PWD\out\pylib"
out\pyenv\Scripts\python.exe speedrun\bench\latency.py
```

## Reference machine

- Platform: `Windows-11-10.0.26200-SP0`
- CPU: `Intel64 Family 6 Model 142 Stepping 12, GenuineIntel` x8
- RAM: 7.8 GB
- Python: 3.13.13
- Deck: **50,000 cards** across 8 MCAT topic decks
- FSRS enabled: False
- Git commit: `92ddeb630`  ·  generated 2026-07-04T21:21:53.861127+00:00

## Results (p50 / p95 / worst-case)

| Action | p50 | p95 | worst | target p95 | verdict |
| --- | --- | --- | --- | --- | --- |
| Button press acknowledged | 3.8 ms | 13.7 ms | 150.4 ms | < 50 ms | PASS |
| Next card after grading | 0.9 ms | 2.3 ms | 73.3 ms | < 100 ms | PASS |
| Dashboard first load (mcat_dashboard) | 776.1 ms | 776.1 ms | 776.1 ms | < 1000 ms | PASS |
| Dashboard refresh (mcat_dashboard) | 778.0 ms | 1138.4 ms | 1209.1 ms | < 500 ms | OVER |
| Dashboard refresh (5-RPC baseline) | 2932.9 ms | 5315.4 ms | 6695.9 ms | < 500 ms | OVER |

**Memory footprint:** 75.3 MiB resident on 50,000 cards (Python process incl. the Rust backend).

## Per-RPC breakdown of the 5-RPC baseline bundle (warm)

| RPC | p50 | p95 | worst |
| --- | --- | --- | --- |
| `mcat_mastery` | 407.0 ms | 790.3 ms | 1049.3 ms |
| `mcat_deck_score` | 379.1 ms | 777.1 ms | 881.5 ms |
| `mcat_performance` | 797.4 ms | 1407.7 ms | 2043.3 ms |
| `mcat_readiness` | 883.2 ms | 1733.7 ms | 1954.0 ms |
| `mcat_pace` | 493.8 ms | 851.3 ms | 1102.5 ms |

**One shared scan vs five separate scans:** the baseline bundle (five RPCs, ~2961 ms summed) runs at p50 **2933 ms**; the combined `mcat_dashboard` runs at p50 **778 ms** (**3.77x** faster) with identical output. The desktop deck browser now issues the single call.

## Honesty notes

- Readiness produced a score this run: **False** (graded reviews 396, topic coverage 0.0).
- Dashboard optimization: the five score RPCs each ran their own full-collection search_cards_into_table + revlog scan, and mcat_readiness re-ran mcat_performance internally (~nine scans to draw one panel). The new mcat_dashboard RPC computes all five from ONE shared card+revlog scan; every field is identical to the individual RPCs (Rust parity test). Baseline bundle p50 ~2933 ms vs combined p50 ~778 ms (3.77x). The desktop deck browser now issues the single call.
- NOTE: even the combined single-scan refresh is above the 500 ms target on this machine — a single scan of the whole card+revlog table at this deck size is the floor. The interactive review hot-path (button press, next card) is unaffected and well within target.
- Readiness abstained in this synthetic single-session run: the give-up rule counts only cross-day Review-kind revlog entries, which a same-day bench does not generate. The RPC does the same work either way, so the latency is representative.
- The 5-RPC baseline times the five score RPCs (`mcat_mastery`, `mcat_deck_score`, `mcat_performance`, `mcat_readiness`, `mcat_pace`) separately — the way the dashboard used to draw the panel. The desktop deck browser now issues the single `mcat_dashboard` call instead, so the `mcat_dashboard` rows are the load the UI actually pays.
