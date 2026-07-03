# Speedrun MCAT AI subsystem

The **Transfer-Question generator** (memory → performance bridge) plus its
safety gates. See `../ai-note.md` for the what/why/skipped write-up.

## One command

```powershell
# from the repo root (c:\dev\speedrun\anki)
python -m speedrun.ai.run all
```

`all` runs **check → eval → baselines → leakage → paraphrase** on the committed
**sample cached artifacts** and writes reports to `artifacts/` (including
`SUMMARY.md`). It needs **no API key** and works with the AI fully off — this is
the "eval runs before any student sees a card" proof.

Individual steps: `generate | check | eval | baselines | leakage | paraphrase`.

## Running the real (live) generator

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."     # only step that needs a key
python -m speedrun.ai.run generate         # writes artifacts/generated.json
python -m speedrun.ai.run all              # real numbers over the live cards
```

- Model: `claude-3-5-sonnet-latest` (override with `SPEEDRUN_AI_MODEL`).
- On a missing key / SDK / API error / unparseable output, `generate` logs a
  clear message and falls back to the cached artifacts — the rest of the
  pipeline still runs.

## Dependencies

The offline pipeline runs on the **Python standard library alone**. `numpy` /
`scikit-learn` (and optionally `sentence-transformers`) are accelerators; if
absent, `textsim.py` falls back to a documented pure-Python implementation and
each report records which backend it used. Install accelerators with:

```powershell
pip install -r speedrun/ai/requirements.txt
```

## Sources (traceability)

Drop named source material into `sources/` as `*.json` / `*.txt` / `*.md`
(see `sources/README.md`). Each unit gets a `source_id` + `citation`; every
generated card cites the source it came from. The Khan Academy CARS page is a
supported source — paste its passage+question text into a file here because the
site is bot-blocked to automated fetches. The generator also best-effort samples
your Anki collection notes read-only (never required).

## Declared cutoffs

All thresholds live in `config.py` and were **declared before looking at any
results** (grounding ≥ 0.60, transfer-copy < 0.55, gold pass-rate ≥ 0.80, eval
accuracy ≥ 0.80, wrong-answer ceiling ≤ 0.10, leakage as re-declared in that
file). Do not tune them to results; if you change one, re-declare and say so.

## Files

| File | Role |
| --- | --- |
| `config.py` | model + all declared cutoffs |
| `sources.py` | source ingestion (drop-folder + read-only collection) |
| `generator.py` | Claude call → transfer questions (key-gated, cached fallback) |
| `checker.py` | pre-ship gate + 7f three counts |
| `eval.py` | held-out accuracy + wrong-answer rate |
| `baselines.py` | TF-IDF + vector baselines, same checker |
| `leakage.py` | 7e leakage scan (see the re-declared definition in `config.py`) |
| `paraphrase_test.py` | 7d transfer factor → `artifacts/transfer_factor.json` |
| `textsim.py` | deterministic similarity helpers (stdlib fallback) |
| `run.py` | CLI + report/`SUMMARY.md` writer |
| `gold/gold_set.json` | 50 known-correct MCAT science Q&A |
| `artifacts/` | cached sample items + generated reports |
