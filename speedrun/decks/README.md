# MCAT CARS deck (Khan Academy style)

Files here are built by `speedrun/tools/build_cars_deck.py`:

- **`mcat_cars_khan_style.apkg`** — the deck. 16 cards / 6 passages, deck name
  `MCAT::CARS (Khan-style)`.
- `mcat_cars_khan_style.txt` — plain-text (tab-separated, HTML on) fallback with
  the identical notes, in case `.apkg` import ever fails.

## How to add it in

Importing is **safe while Anki is running** and never touches your live
collection directly:

1. Open Anki (the Speedrun fork, `just run`).
2. **File → Import…**
3. Select `speedrun/decks/mcat_cars_khan_style.apkg` (or the `.txt`).
4. The cards land in the **`MCAT::CARS (Khan-style)`** deck.

To rebuild after editing content:

```powershell
$env:PYTHONPATH="C:\dev\speedrun\anki\out\pylib"
& "C:\dev\speedrun\anki\out\pyenv\Scripts\python.exe" speedrun\tools\build_cars_deck.py
```

## Card format

Each card is self-contained (CARS style): a short humanities / social-science
**passage**, one **question**, four choices (A–D), and on the back the **answer**,
a **rationale** (why right / why the traps are wrong), the **AAMC CARS skill**
tested, and a **source line**. Cards are tagged `MCAT`, `CARS`, the skill
(`CARS::Foundations_of_Comprehension` / `::Reasoning_Within_the_Text` /
`::Reasoning_Beyond_the_Text`), `source::khan-cars-style`, and `passage::<id>`.

## Provenance & honesty (important)

The [Khan Academy MCAT CARS practice page](https://www.khanacademy.org/test-prep/mcat/critical-analysis-and-reasoning-skills-practice-questions)
is **bot-blocked** to automated fetches (it returns a Cloudflare "Client
Challenge"), and reproducing its passages verbatim would be a copyright problem
for an AGPL repo. CARS is unique among MCAT sections in testing **content-
independent reasoning** — there are no facts to memorize, only comprehension and
reasoning about an unfamiliar passage. So this deck ships **original passages
written in the Khan CARS style** (same disciplines, same three AAMC skill
categories, same "answer only from the text" discipline) with **no Khan text
reproduced**. Each card cites the Khan CARS page as its pedagogical model.

Because CARS answers are interpretive rather than objectively verifiable, these
cards are **not** part of the auto-checked science gold set (challenge 7f) — this
matches the note in `speedrun/ai/sources/khan_cars_example.txt`. If you have Khan
passages you are licensed to use, paste them into that file or extend `PASSAGES`
in the builder and re-run.
