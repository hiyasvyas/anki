# Coverage map (challenge 7c)

Lists every MCAT content category, checks which the study deck actually covers,
and reports percent covered per section + overall. Below the declared line
(**50%**, matching the readiness engine's give-up rule) the dashboard abstains —
a deck that skips a whole high-weight section cannot claim "ready".

## Run (from repo root)

```powershell
python speedrun/coverage/coverage_map.py            # auto-discovers your Anki collection
python speedrun/coverage/coverage_map.py --collection "C:\path\to\collection.anki2"
python speedrun/coverage/coverage_map.py --threshold 0.5
```

- **Standard library only** (sqlite3/json) — no dependencies, no build.
- The collection is opened **read-only** (`?mode=ro&immutable=1`); a running Anki
  is never disturbed, and a collection is never required. With none present it
  falls back to the AI harness gold-set topics as a documented proxy so the
  report still runs.

## Outputs
- `coverage_report.md` — human-readable: overall %, per-section table, covered
  categories (with the matched keyword), and the missing categories as the
  highest-value study gaps.
- `coverage.json` — machine-readable, incl. `show_score` (the abstain decision).

## How coverage is decided
Topic strings come from the names of **decks that have cards** plus note **tags**
(so empty placeholder decks don't count). Each content category in
`mcat_outline.json` has keywords; a category is *covered* if a keyword matches a
topic string on a word boundary (short keywords require a whole-word match so
`ph` can't match inside `phospholipid`). CARS is skills-based — tracked as
passage-practice presence, excluded from the content-coverage denominator.

Outline categories are the AAMC Foundational Concepts / Content Categories;
verify wording against the official AAMC "What's on the MCAT Exam?" outline.
