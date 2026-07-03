# Sync robustness (offline mid-sync / wrong clock)

Deterministic simulation of the engine's id-keyed merge.

## Guarantee 1 -- no lost or double-counted reviews (clock-independent)

- distinct reviews after merge: **18** (expected 18)
- holds after an interrupted sync + full client retry: **True**
- phone clock skewed **+172800000 ms** (2 days) and still no dup/loss: **True**

## Guarantee 2 -- same card on both devices (bounded tradeoff)

- both review rows retained in the log: **True**
- scheduling winner by mtime (last-writer-wins) grade: **4**
- winner by revlog id (creation-order tiebreak) grade: **4**

A wrong clock can only change which review *owns the next due date* -- never the review counts. Both rows survive, so the audit trail is always correct.
