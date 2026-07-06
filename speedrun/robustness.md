# Adversarial robustness (spec section 10 — "we will try to break it")

Three of the "try to break it" cases are handled by dedicated, **re-runnable,
stdlib-only** checks in `speedrun/robustness/`. Each opens any Anki collection
**read-only** and falls back to a synthetic self-test dataset, so it always
produces a deterministic report — with or without a collection.

One command:

```bash
python -m speedrun.robustness.run all        # run all three, write reports
python -m speedrun.robustness.run selftest   # deterministic correctness (CI-able)
```

Artifacts land in `speedrun/robustness/artifacts/`.

Each check's design rationale is backed by named sources — see
[`speedrun/evidence.md`](evidence.md) (§7 rushed reviews, §8 contradictions,
§9 sync conflict rule).

| Attack | Check | How it's handled |
| --- | --- | --- |
| **Two cards state opposite facts** | `contradictions.py` | Scans for near-duplicate *questions* (Jaccard ≥ 0.80) whose *answers* conflict (answer similarity ≤ 0.40 **or** an affirmative↔negative polarity flip). Flagged pairs are surfaced and excluded from mastery confidence — the deck disagrees with itself, so we don't report confident recall of that fact. Cloze notes and link/boilerplate answers are excluded to avoid false positives. Cutoffs declared before results. |
| **Taps "Good" without reading** | `rushed_reviews.py` | Reads `revlog.time` (ms on the card). Reviews under **800 ms** are too fast to have been read and are excluded. The readiness give-up rule counts the **honest** graded total (raw minus rushed), so spamming "Good" cannot unlock a readiness score. |
| **Phone offline mid-sync / wrong clock** | `sync_robustness.py` | Deterministic simulation of the engine's id-keyed merge. Proves **no lost or double-counted reviews** under a 2-day clock skew *and* an interrupted-then-retried sync (union by unique `revlog.id` is idempotent). The same-card scheduling winner is last-writer-wins by mtime — a bounded tradeoff that can only change which review owns the next due date, never the review counts; both rows are always retained. |

## Declared cutoffs (before looking at any result)

- **Contradictions:** front similarity ≥ 0.80; conflict if answer similarity ≤ 0.40 or polarity flip; answers need ≥ 2 real content tokens.
- **Rushed:** < 800 ms = not read; readiness review floor = 230 (≈ one full MCAT), counted on the honest total.
- **Sync:** invariants — distinct-review count preserved, merge idempotent after interrupt/retry, both conflict rows retained.

## Latest run (this repo's collection + self-tests)

- Self-tests: **ALL PASS** (contradiction detector catches the planted opposite pair; rushed splits 12→8 honest; sync stays 18 distinct under skew+interrupt).
- Collection (2,939 notes): **0** real contradictions among 56 basic Q→A cards (cloze cards excluded); **0/65** reviews rushed; sync invariants hold.

These join the other adversarial cases already covered elsewhere: paraphrase
test / transfer factor (memorizes wording, fails reworded — `speedrun/ai`),
coverage map (huge deck skips a high-weight topic — `speedrun/coverage`),
leakage check (test data leaked into training — `speedrun/ai`), the checker's
"correct-but-useless" count (AI cards that are useless — `speedrun/ai`), and the
generator's offline fallback (AI service down/rate-limited — `speedrun/ai`).

## Crash in the middle of a review (challenge 7g)

`python -m speedrun.crash.crash_test` hard-kills a worker process (SIGKILL /
TerminateProcess) **mid-review, 20 times in a row**, against the **real shared
Anki engine** — not a mock — then reopens the collection with the backend and
runs `PRAGMA integrity_check` after each kill. Latest run: **20 kills → 0
corrupted collections, 0 previously-committed reviews lost**, committed-review
count monotonic (466 → 1,748). Anki's SQLite write-ahead log makes commits atomic
and durable and rolls back an interrupted write cleanly, so a kill can only lose
the uncommitted tail of a session, never corrupt the file; the shared engine
carries the same guarantee to the phone build. Report:
[`speedrun/crash/artifacts/report_crash.md`](crash/artifacts/report_crash.md).
