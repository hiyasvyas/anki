# Crash-recovery test (challenge 7g)

**Claim:** killing the app mid-review must never corrupt the collection or lose already-committed reviews.

Run against the **real shared Anki engine** (the backend the desktop app and the phone build embed) on a throwaway collection: a worker reviews cards in a loop and is **hard-killed** (TerminateProcess/SIGKILL) mid-review, repeatedly. After each kill the collection is reopened with the backend and checked.

## Result

| Check | Value |
| --- | ---: |
| Kills (mid-review) | 20 |
| **Corrupted collections** | **0** |
| Collections that failed to reopen | 0 |
| Previously-committed reviews lost | 0 |
| Committed-review count monotonic non-decreasing | True |
| Final integrity_check | ok |
| Final committed reviews | 1748 |

**Verdict: PASS — 0 corrupted collections.**

Per-kill committed-review counts (never decreases — committed reviews are durable; only the uncommitted tail of an interrupted session is rolled back):

`[466, 868, 1068, 1146, 1322, 1416, 1446, 1516, 1551, 1591, 1618, 1626, 1637, 1651, 1655, 1673, 1694, 1721, 1743, 1748]`

## Why it holds

- Anki stores the collection in **SQLite with a write-ahead log**; commits are atomic and durable, and an in-flight write is rolled back cleanly on the next open. A hard kill can drop the *uncommitted* tail of a session but never corrupts the file.
- Because the engine is shared, the same durability guarantee ships to the phone build.

## Reproduce

```bash
$env:PYTHONPATH = "$PWD\out\pylib"
python -m speedrun.crash.crash_test           # 20 kills (the spec number)
python -m speedrun.crash.crash_test selftest   # fast smoke + detector check
```
