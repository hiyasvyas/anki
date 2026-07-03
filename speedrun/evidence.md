# Evidence base — why each feature exists

Every non-cosmetic feature in this project is grounded in a named, checkable
source. The rubric holds AI output to that standard ("every AI output must come
from a named source"); we hold our own design decisions to the same bar. Each
row below states the design choice, the source that motivates it, and where the
choice lives in the code.

How to read this: claims are backed by peer-reviewed research, official exam
documentation, or established engineering standards. Where a source is nuanced
(e.g. contradictions can *help* learning when resolved), we say so rather than
cherry-picking.

---

## 1. AI Practice-Question Generator (`speedrun/ai/`, `qt/aqt/mcat_ai.py`)

**Claim:** Generating *new, reworded* exam-style questions from a studied card
measures a different thing than flashcard recall, and practicing retrieval on
them improves durable learning — not just memory of the original card wording.

- **Transfer of learning (near vs. far).** Barnett, S. M., & Ceci, S. J. (2002).
  *When and where do we apply what we learn? A taxonomy for far transfer.*
  Psychological Bulletin, 128(4), 612–637.
  https://doi.org/10.1037/0033-2909.128.4.612
  → Transfer depends on how far the test context sits from the learning context
  (knowledge domain, modality, etc.). Recalling a flashcard and answering a
  reworded passage question are *different points on the transfer continuum* —
  which is exactly the memory-vs-performance gap the project asks us to measure.
  A review applying this to the life sciences: *CBE—Life Sciences Education*,
  https://doi.org/10.1187/cbe.19-11-0227

- **The testing effect / retrieval practice.** Roediger, H. L., & Karpicke,
  J. D. (2006). *Test-enhanced learning.* Psychological Science, 17(3), 249–255.
  https://doi.org/10.1111/j.1467-9280.2006.01693.x — and Karpicke & Roediger
  (2008), *The critical importance of retrieval for learning*, Science, 319,
  966–968, https://doi.org/10.1126/science.1152408
  → Retrieval practice produces substantially better long-term retention than
  restudying, and this transfers to *non-tested but related* material,
  especially when items are integrated/semantically related (Chan, 2009; Pan &
  Rickard, 2018, reviewed in https://doi.org/10.3758/s13421-023-01477-5). This
  justifies generating extra retrieval opportunities that share cues with the
  source card.

**Design consequence in code:** each generated card cites the source card it
came from, and only cards that pass a grounding + well-formedness gate are
added. This keeps the generator on the "transfer" side without drifting into
untraceable content.

## 2. AI safety gate / prompt-injection defense (`speedrun/ai/checker`, gate in `mcat_ai.py`)

**Claim:** Untrusted source text (and adversarial hidden text) must not be able
to steer the generator; every card must trace to its source and pass
deterministic validation before a human ever sees it.

- **OWASP Top 10 for LLM Applications 2025 — LLM01:2025 Prompt Injection.**
  https://genai.owasp.org/llmrisk/llm01-prompt-injection/ (PDF:
  https://owasp.org/www-project-top-10-for-large-language-model-applications/assets/PDF/OWASP-Top-10-for-LLMs-v2025.pdf)
  → OWASP states prompt injection is architectural (LLMs can't reliably separate
  instructions from data), so defense must be *defense-in-depth*: constrain the
  model's role, **validate expected output formats with deterministic code**,
  **filter for groundedness** (the RAG Triad: context relevance, groundedness,
  answer relevance), segregate untrusted content, and **require human approval
  for high-risk actions.** Our pipeline mirrors this: the model proposes cards,
  but deterministic code enforces the schema + source-grounding gate, and cards
  are added as a new deck the user reviews — not silently merged.

## 3. Memory model (FSRS / DSR) (`rslib` scheduler, `speedrun/models/memory-model.md`)

**Claim:** We estimate the probability a fact is recalled *now* using Anki's
FSRS, which models memory with Difficulty/Stability/Retrievability rather than
fixed SM-2 multipliers.

- **Three-component (DSR) model of memory.** Woźniak, P. et al., SuperMemo;
  summarized at https://supermemo.guru/wiki/Three_component_model_of_memory
- **FSRS algorithm & implementation.** open-spaced-repetition project:
  https://github.com/open-spaced-repetition/free-spaced-repetition-scheduler and
  the fundamentals wiki
  https://github.com/open-spaced-repetition/fsrs4anki/wiki/The-fundamental-of-FSRS
  → FSRS fits per-user parameters by MLE/gradient descent on review history and
  is Anki's default scheduler since v23.10; benchmarks on 500M+ reviews show
  ~20–30% fewer reviews for equal retention vs SM-2. Retrievability R is a
  literal recall-probability estimate, which is what a *memory* score should be.

## 4. Honest uncertainty ranges & give-up rule (`rslib` stats, all three score models)

**Claim:** Scores are shown as a *range*, not a single number, and computed with
an interval method that behaves well on small samples — and the app abstains
when data is thin.

- **Wilson score interval.** Wilson, E. B. (1927). *Probable inference, the law
  of succession, and statistical inference.* JASA, 22, 209–212. Modern
  recommendation: Brown, Cai & DasGupta (2001), *Interval estimation for a
  binomial proportion*, Statistical Science, 16(2), 101–133,
  https://projecteuclid.org/journalArticle/Download?urlId=10.1214%2Fss%2F1009213286
  → Brown et al. and Agresti & Coull explicitly recommend the Wilson interval
  for small n; it never leaves [0,1] and its coverage stays near nominal where
  the Wald interval fails. This is why our ranges use Wilson, not point ± SE.

**Design consequence:** the give-up rule (no readiness score below N honest
graded reviews and a coverage threshold) is the "a good system knows when it
does not know" principle the rubric demands.

## 5. Calibration of the memory model (`speedrun/models/`, Sunday calibration chart)

**Claim:** "When we say 80%, it happens ~80% of the time" is a measurable,
proper-scoring-rule property, reported with a reliability diagram + a numeric
score.

- **Brier score.** Brier, G. W. (1950). *Verification of forecasts expressed in
  terms of probability.* Monthly Weather Review, 78(1), 1–3. Overview:
  https://en.wikipedia.org/wiki/Brier_score
- **Calibration / reliability diagrams.** Dimitriadis, Gneiting & Jordan (2021),
  *Stable reliability diagrams for probabilistic classifiers* (CORP), PNAS,
  https://pmc.ncbi.nlm.nih.gov/articles/PMC7923594/ ; scikit-learn calibration
  guide https://scikit-learn.org/stable/modules/calibration.html
  → Brier is a strictly proper scoring rule that decomposes into
  reliability (calibration) + resolution + uncertainty, which is exactly the
  vocabulary the rubric uses for an honest memory score.

## 6. Passage-Pace Trainer (`rslib/src/stats/pace.rs`, `speedrun/pace-trainer.md`)

**Claim:** Performance is not just accuracy — under a real time limit, pacing
changes the score, so a readiness tool must track speed against the exam's
budget.

- **Speed–accuracy tradeoff.** Heitz (2014); Luce (1986); Wickelgren (1977),
  reviewed in the UK Ofqual report *Time limits and speed of working in
  assessments*,
  https://assets.publishing.service.gov.uk/media/6925965a22424e25e6bc314c/time-limits-and-speed-of-working-in-assessments.pdf
  and PMC review https://pmc.ncbi.nlm.nih.gov/articles/PMC11562887/
- **MCAT-specific speededness.** AAMC, *The effect of speededness on MCAT
  scores*, https://doi.org/10.1037/e518632013-044
  → Extra time raised MCAT VR/PS scaled scores by ~0.7 points on average, and
  examinees adjust pacing to the clock (Harik et al., 2018) — direct evidence
  that a section time budget belongs in a readiness model. (Note the honest
  caveat: pace is *not* a proxy for ability — slow test-takers do as well given
  enough time, https://pmc.ncbi.nlm.nih.gov/articles/PMC13113617/ — so we frame
  pace as a *finishing-on-time* risk, not a competence score.)

## 7. Rushed-review filter — "taps Good without reading" (`speedrun/robustness/rushed_reviews.py`)

**Claim:** Reviews answered faster than a person could read the card are
non-effortful and should be excluded from the honest graded-review count.

- **Response Time Effort / rapid guessing.** Wise, S. L., & Kong, X. (2005).
  *Response time effort: A new measure of examinee motivation in computer-based
  tests.* Applied Measurement in Education, 18(2), 163–183.
  https://doi.org/10.1207/s15324818ame1802_2 ; Wise (2017), *Rapid-guessing
  behavior*, EM:IP, https://doi.org/10.1111/emip.12165 ; Kong, Wise & Bhola
  (2007) on thresholds, https://doi.org/10.1177/0013164406294779
  → Responses below an item threshold indicate the examinee "opted out of being
  measured" and distort scores, so they should be dropped or effort-moderated.
  The literature uses item-specific thresholds (often a % of mean RT, capped at
  ~10s) or fixed thresholds (e.g. 3s); Kong et al. show small threshold changes
  don't materially change results. Our 800 ms cutoff is deliberately
  conservative (well below any solution-behavior time), so it only removes the
  clearest non-reads.

## 8. Contradiction detector — "two cards, opposite facts" (`speedrun/robustness/contradictions.py`)

**Claim:** Near-identical questions with conflicting answers in the same deck are
a data-integrity hazard worth flagging.

- **Cognitive conflict & memory (nuanced).** Maier & Richter (2013), reviewed in
  https://www.frontiersin.org/journals/cognition/articles/10.3389/fcogn.2023.1125700/full
  and D'Mello et al., *Inducing and tracking confusion with contradictions*,
  https://files.eric.ed.gov/fulltext/EJ1190004.pdf
  → The honest finding: contradictions can *help* learning **only if the learner
  notices and resolves them**; unresolved conflicts induce confusion that
  impairs learning. In an SRS a learner grades cards in isolation and will
  never see the two conflicting cards side by side, so the "productive
  resolution" path is unavailable — which is precisely why silent contradictory
  pairs are a hazard here and worth surfacing to the deck author.

**Design note:** cloze cards and boilerplate/link-only answers are excluded to
avoid false positives; a synthetic self-test guards the detector.

## 9. Sync conflict rule — offline, mid-sync, wrong clock (`speedrun/robustness/sync_robustness.py`)

**Claim:** Reviews merge without loss or double-count via unique-id union
(idempotent), and scheduling-state conflicts resolve deterministically by
modification time with a stable tiebreaker.

- **CRDT / Last-Writer-Wins register.** Shapiro, Preguiça, Baquero & Zawirski
  (2011), *Conflict-free replicated data types*, INRIA RR-7687 — foundational.
  Practitioner references documenting the LWW-register merge (higher timestamp
  wins; **node-id tiebreaker for equal timestamps**; wall-clock skew pitfall,
  mitigated with logical/Lamport/HLC clocks):
  https://iankduncan.com/engineering/2025-11-27-crdt-dictionary/ and
  https://oneuptime.com/blog/post/2026-01-30-last-write-wins/view
  → This literature validates two of our choices directly: (1) a set union keyed
  by a unique id is idempotent and commutative, so replaying an interrupted sync
  can't lose or duplicate reviews; (2) LWW needs a deterministic tiebreaker and
  is vulnerable to clock skew — which is why we tiebreak by a stable id and
  retain *both* review log entries even when only one scheduling state "wins."

## 10. Exam scale grounding (`speedrun/models/readiness-model.md`)

**Claim:** The readiness projection uses the real MCAT scale, not an invented one.

- **AAMC — The MCAT Exam Score Scale.**
  https://students-residents.aamc.org/mcat-scores/mcat-exam-score-scale and the
  scoring chapter
  https://students-residents.aamc.org/register-mcat-exam/publication-chapters/mcat-exam-scoring
  → Four sections each 118–132 (midpoint 125); total 472–528 (midpoint 500);
  scaled + equated, no curve, no guessing penalty. Our scale endpoints and
  section structure come straight from this.

---

### Notes on honesty

- Sources are cited even where they complicate our design (pace ≠ ability;
  contradictions can help *if resolved*). Reporting the caveat is part of the
  "honest numbers over flattering ones" standard.
- Engineering choices (Wilson, LWW/CRDT, OWASP) are backed by standards and
  primary literature, not blog posts alone; blog links are included only as
  readable restatements of the primary source.
