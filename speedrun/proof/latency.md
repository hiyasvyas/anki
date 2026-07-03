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
- Git commit: `300448a6b`  ·  generated 2026-07-03T17:45:03.449159+00:00

## Results (p50 / p95 / worst-case)

| Action | p50 | p95 | worst | target p95 | verdict |
| --- | --- | --- | --- | --- | --- |
| Button press acknowledged | 1.4 ms | 2.0 ms | 11.7 ms | < 50 ms | PASS |
| Next card after grading | 0.3 ms | 0.4 ms | 39.2 ms | < 100 ms | PASS |
| Dashboard first load | 1173.5 ms | 1173.5 ms | 1173.5 ms | < 1000 ms | OVER |
| Dashboard refresh | 1600.8 ms | 1775.6 ms | 2620.2 ms | < 500 ms | OVER |

**Memory footprint:** 69.4 MiB resident on 50,000 cards (Python process incl. the Rust backend).

## Per-RPC breakdown of the dashboard bundle (warm)

| RPC | p50 | p95 | worst |
| --- | --- | --- | --- |
| `mcat_mastery` | 223.0 ms | 263.5 ms | 356.1 ms |
| `mcat_deck_score` | 207.5 ms | 270.7 ms | 395.1 ms |
| `mcat_performance` | 432.4 ms | 494.7 ms | 814.6 ms |
| `mcat_readiness` | 461.8 ms | 558.2 ms | 718.1 ms |
| `mcat_pace` | 250.5 ms | 308.8 ms | 439.1 ms |

## Honesty notes

- Readiness produced a score this run: **False** (graded reviews 406, topic coverage 0.0).
- OVER TARGET: the dashboard bundle exceeds the section-10 target. Root cause: the five score RPCs each run their own full-collection search_cards_into_table + revlog scan, and mcat_readiness re-runs mcat_performance internally. Individual RPCs are ~208-462 ms. Optimization (tracked): compute one shared card/revlog pass and reuse the performance result inside readiness, and cache between refreshes. The interactive review hot-path (button press, next card) is unaffected and well within target.
- Readiness abstained in this synthetic single-session run: the give-up rule counts only cross-day Review-kind revlog entries, which a same-day bench does not generate. The RPC does the same work either way, so the latency is representative.
- The dashboard bundle times all five score RPCs (`mcat_mastery`, `mcat_deck_score`, `mcat_performance`, `mcat_readiness`, `mcat_pace`) together, because that is what the UI issues to draw the panel.
