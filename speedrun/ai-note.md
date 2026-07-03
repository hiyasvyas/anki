# AI note — what we built, why, and what we skipped

**Exam:** MCAT · **Feature:** an AI **Transfer-Question generator** — the
memory → performance bridge.

Why this design (named sources): see [`speedrun/evidence.md`](evidence.md) §1
(transfer of learning + the testing effect) and §2 (OWASP LLM01 prompt-injection
defense — deterministic output validation, groundedness gate, human-reviewed
output).

## What the AI does
Given a **named source** (an MCAT-shaped passage — Khan Academy MCAT / AAMC-aligned
content, or the student's own deck notes), it generates new **exam-style
multiple-choice questions that test the same idea in different words**. Every
generated item carries the `source_id` + citation it came from, so nothing is
untraceable. This is the concrete implementation of challenge **7d** (the
paraphrase test): it manufactures the *novel, reworded* questions our
performance model needs, instead of re-showing the memorized card.

Pipeline (`speedrun/ai/`, one command: `python -m speedrun.ai.run all`):
1. **generate** (provider-agnostic: Anthropic Claude, Google Gemini, or Groq —
   whichever key is set) → transfer questions, each citing its source.
2. **check** — a pre-ship gate with cutoffs **declared before results**
   (`config.py`): source-grounding, well-formedness, and *transfer-not-copy*.
   Produces the 7f three counts and blocks anything that fails.
3. **eval** — held-out accuracy + wrong-answer rate against a 50-item gold set.
4. **baselines** — the same checker scores a TF-IDF/keyword baseline and a
   vector/embedding baseline; we report the side-by-side.
5. **leakage** (7e) — scans priming + generated stems against held-out test
   questions.
6. **paraphrase** (7d) — 30 cards × 2 reworded questions; measures the
   recall-vs-transfer **gap** and writes the transfer factor for the engine
   (only when real attempts are provided).

## Why this feature (tied to named sources)
- **Memory ≠ performance** is our thesis. Retrieval-practice and transfer
  research (spacing / retrieval-practice / interleaving literature in the
  Brainlift) says recalling a card is not the same as answering a new question;
  the generator exists to *measure and close that gap*, not to make more cards.
- **Khan Academy MCAT + AAMC** are the intended source base: AAMC explicitly
  points to Khan Academy as MCAT-shaped prep, so grounding generation there keeps
  cards on-outline and citable (Brainlift DOK-2 Cat 2 & 3).
- **AAMC's active-learning / self-assessment framing** motivates gating every
  card behind an automated check before a student ever sees it.

## Why it's honest / safe
- **Named source on every output** — no traceable source, no card.
- **Eval runs before students see anything**, with cutoffs fixed in advance
  (a wrong fact is worse than no card, so the wrong-answer ceiling is strict at
  10%).
- **Beats a simpler method** — TF-IDF and vector retrieval both score 0% pass on
  the same checker vs the generator's 90%, because retrieved existing questions
  aren't grounded transfers of the source.
- **Runs with the AI off** — only *generation* needs an API key, and it accepts
  any of three providers: `ANTHROPIC_API_KEY` (Claude), `GEMINI_API_KEY`
  (Google, free tier), or `GROQ_API_KEY` (Groq, free tier). check / eval /
  baselines / leakage / paraphrase run deterministically on cached artifacts
  (the committed sample proves the whole pipeline today, no key). If no key is
  set, or the API is offline, rate-limited, or returns broken output, the
  generator logs and falls back to cached artifacts; the app's three scores come
  from the Rust engine and never depend on the AI. The same fallback powers the
  in-app **✦ Generate practice deck** button: with a key it generates live, and
  with none it adds the committed, gate-passed sample cards.
- **Prompt-injection** in a source can't smuggle a card through — the checker
  requires the answer to be grounded in the cited source and blocks copied
  wording.

## What we deliberately skipped
- **No chatbot / no free-form tutor.** Scope is one checked, source-grounded
  generation task.
- **No automated CARS grading.** CARS answers are interpretive (there is no
  single objectively-correct fact), so the auto-checked gold set is
  **science-based** (objectively verifiable), which is what makes the
  "wrong-fact rate" meaningful. CARS transfer questions are supported as a source
  type but evaluated qualitatively, not auto-scored — and we say so rather than
  faking a CARS accuracy number.
- **No claim of out-of-distribution generalization from the sample.** The sample
  sources and gold share an MCAT corpus, so the offline numbers demonstrate the
  **checker + grounding + baseline gap**, not generalization to unseen facts.
  Real held-out generalization comes when the user adds their own Khan/AAMC
  sources distinct from the gold.
- **No fine-tuning / no training on our data** — a frozen API model with a
  single generic few-shot example (kept disjoint from the gold, verified by the
  leakage check).

## What the user still runs
1. Paste 1–2 Khan CARS passage+question sets (and any AAMC content) into
   `speedrun/ai/sources/` (the Khan site is bot-blocked to automated fetches).
2. Set one API key — `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, or `GROQ_API_KEY`
   (the last two have free tiers) — then `python -m speedrun.ai.run generate`
   for real (live) cards, then `python -m speedrun.ai.run all` for real numbers.
   The desktop app reads the same env var, so launching Anki with a key set
   makes the in-app generator run live too.
3. For a **measured** transfer factor (7d): answer the reworded questions in
   `speedrun/ai/paraphrase/paraphrase_set.json` and record results in
   `speedrun/ai/paraphrase/attempts.json` (same shape as `attempts_sample.json`);
   re-run `paraphrase`. Only then set the Anki config key `mcatTransferFactor`
   to the value in `speedrun/ai/artifacts/mcat_transfer_factor.json`
   (`safe_to_set_config: true`) so the engine's performance score uses the
   measured bridge instead of the honest default of 1.0. The committed sample run
   is `measured=false` and must not be used to set the config.
