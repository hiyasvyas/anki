# `sources/` — the named-source drop folder

Every AI-generated card must trace back to a **named source**. This folder is
where those sources live. Anything you drop here becomes one or more *source
units* with a stable `source_id` and a human `citation`, and the generator is
only allowed to draw on these units.

## Supported files

Drop any of these into this folder:

### `*.json`
Structured sources. Two accepted shapes:

```jsonc
// Shape A: a file-level citation plus a list of units
{
  "citation": "OpenStax Biology 2e, Ch. 7",
  "url": "https://openstax.org/details/books/biology-2e",
  "units": [
    { "source_id": "bio-cellresp", "topic": "Biology::Respiration",
      "citation": "OpenStax Biology 2e, Ch. 7", "text": "..." }
  ]
}
```

```jsonc
// Shape B: just a list of unit objects
[ { "id": "my-unit-1", "topic": "...", "text": "...", "citation": "..." } ]
```

Per-unit fields: `source_id` (or `id`), `text` (or `content`), `topic`,
`citation`, `url`. Missing `source_id` is auto-derived from the filename +
index; missing `citation` falls back to the file-level citation, then filename.

### `*.txt` / `*.md`
Free text. Each **blank-line-separated paragraph** becomes one source unit. A
leading `URL: https://...` line is captured as the unit URL. You can also add a
sidecar `<name>.meta.json` with `{"citation": "...", "url": "..."}`.

> `README.md` itself is ignored by the ingester.

## Khan Academy CARS (a supported named source)

The Khan Academy MCAT CARS practice page is a **supported named source**:

> https://www.khanacademy.org/test-prep/mcat/critical-analysis-and-reasoning-skills-practice-questions

The site is **bot-blocked to automated fetches**, so paste the passage + question
text into a `.txt` file here (e.g. `khan_cars_passage1.txt`) with a
`URL:` first line or a `.meta.json` sidecar citing the page. CARS is scored
**qualitatively** (the auto-graded gold set is science-only, because CARS answers
are interpretive and can't be objectively auto-checked — see `../ai-note.md`).

## Auto-discovery of your Anki collection

On top of this folder, the ingester makes a **best-effort, read-only** attempt to
sample note fields from your Anki collection
(`%APPDATA%\Anki2\<profile>\collection.anki2` on Windows). Those become units
cited as `MCAT deck note <nid>`. This is wrapped in try/except and never
required — if Anki isn't installed or the DB is locked, it is silently skipped.

## The `seed_mcat_*.json` files

The `seed_mcat_biology.json`, `seed_mcat_biochem.json`, `seed_mcat_chemphys.json`,
and `seed_mcat_psychsoc.json` files are **seed placeholders**: genuinely correct,
citable MCAT science facts (cited to OpenStax / Lehninger) so the pipeline has
real, grounded material to run on today. Replace or augment them with your own
Khan Academy / AAMC content.
