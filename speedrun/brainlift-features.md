# What we built (features)

A short write-up of the features that were actually shipped in the app, to add
to the end of the brainlift. Every feature traces back to a named source above,
and every number below comes from a committed evaluation run, not an estimate.

## The three score models

The app keeps memory, performance, and readiness as three separate read-only
engine calls instead of blending them into one number, because that separation
is what makes the memory→performance gap visible instead of hidden. **Memory**
answers only "can the student recall this fact right now?" — it's the card's
current FSRS retrievability (the same path Anki's own graphs use), projected over
unseen cards with a 95% Wilson interval that narrows as more of the deck is
reviewed. It grounds out in the DSR/FSRS model of memory and, for the range, the
Wilson interval's good behavior on small samples.

**Performance** answers the harder question — "can the student answer a new,
reworded exam-style question that uses this fact?" — and models it as memory
discounted by a *measured* transfer factor, not an invented one. That factor
comes from the paraphrase test: recall on a card (90.0%) versus accuracy on
reworded questions built from it (71.7%), a measured gap of 18.3% (transfer
factor 0.796). If no factor has been measured yet, it defaults to 1.0 and the app
flags `transfer_measured = false` and shows performance equal to memory rather
than faking a discount. This is the direct build of the brainlift's core idea
that retrieval on reworded items is the bridge from memory to performance
(Barnett & Ceci on far transfer; Roediger & Karpicke on retrieval practice).

**Readiness** maps performance onto the real MCAT scale (472–528, endpoints from
AAMC) and is deliberately evidence-gated: it will only show a score once the
student has at least 230 graded reviews (one full-length test's worth) *and* at
least 50% topic coverage, otherwise it returns "no score yet" with the exact
reasons. Every shown score carries a range, a confidence label, coverage, a
timestamp, and the give-up rule itself. We explicitly do not claim a score
calibrated against real practice-test outcomes, because we don't have that paired
data in a one-week sprint — and saying so is more honest than a polished number
we can't back up.

## Source-backed AI generator + evals

The AI question generator only ships cards that trace to a named source and pass
a held-out evaluation first. On a 20-item held-out gold set it scores 100%
accuracy with a 0% wrong-answer rate (against declared cutoffs of 80% and 10%),
and on the full 50-card gold set the three-count split is 45 correct-and-useful
(ship) / 0 wrong-fact / 5 correct-but-bad-teaching (blocked) — a 90% pass rate.
It beats the simpler baselines it's compared against (AI 90% vs TF-IDF 0% vs
vector 0% on the same checker), and a leakage check comes back clean (0 flags).
This is the brainlift's "no generative features that don't trace back to named
sources and automated checks" rule, built and measured, using
Khan-Academy/AAMC-aligned material.

Alongside it is a prompt-injection and safety gate: because an LLM can't reliably
separate instructions from data, deterministic code enforces the schema and
source-grounding while the model only proposes. In the adversarial test, 17
hostile or garbled model responses were pushed through the real parse-and-gate
path and 0 reached a student (5 dropped at parse, 12 blocked) while the valid
control still passed. This follows OWASP's Top 10 for LLM Applications (prompt
injection and insecure output handling).

## Learning-science study-feature ablation

To test a learning-science claim honestly, interleaving was run as a three-build
ablation at equal study time: the full app (interleaved + weakness-targeted),
the same allocation blocked (feature off), and plain Anki. The metric was
pre-registered — accuracy on held-out mixed-topic (confusable-pair) questions —
with a failure rule set in advance. Interleaving raised accuracy from 92.7% to
97.8%, a +5.1 pp paired gain (95% CI [+4.8, +5.3]). Crucially, the same model
produces honest null results where theory says it should: +0.0 pp on a
single-topic memory-only metric and +0.0 pp when topics aren't confusable — so
interleaving is shown to help transfer, not to be a free memory boost. This is a
transparent mechanism simulation, not a human study, and it's labeled as such;
it draws on the interleaving, retrieval-practice, and spacing literature plus
Barnett & Ceci for why the metric is a transfer metric.

## Memory-model calibration

Calibration checks that when the model says 80%, the student recalls about 80%,
on held-out reviews, using predicted recall reconstructed from the FSRS
forgetting curve with no parameters fit on the scored outcomes. On 4,000 held-out
reviews it reports a Brier score of 0.1329, log-loss of 0.4087, and an expected
calibration error of 0.0106 (observed recall 76.7% vs mean predicted 75.7%) —
well calibrated, and better than the base-rate baseline. The honest limit: the
dev deck only has same-day reviews so far, so the committed run uses a
correctly-specified synthetic stream (labeled, not hidden); pointing it at a deck
with real multi-day history yields a real number with no code change. This builds
the brainlift's "calibrated on held-out reviews" requirement (Brier score and
reliability-diagram literature).

## Passage-Pace Trainer (the Rust engine change)

Timing is built as a first-class engine signal, not a UI timer. The Rust engine
learns each topic's recent accuracy and mean answer time (from data Anki already
stores) and sets a time target on a fixed ladder — unlimited → 300 s → 180 s →
120 s → 90 s, with 90 s as the goal. The target only tightens when it's earned
(at least 20 recent reviews, accuracy ≥ 0.85, and mean time already inside the
next rung), so the clock never shrinks just because test day is close; the
starting rung is chosen from how far away the exam date is. This is the direct
build of the brainlift's main spiky POV: early practice runs with no visible
timer so the learner builds comprehension first, and pacing pressure appears only
once earned, making the clock diagnostic instead of a source of panic.

It's a real scheduler decision, not a widget: a new weakness-first review order
reorders the day's queue so the slowest/weakest topics come first, proven by a
test that builds a real queue and asserts the weak topic's card is scheduled
first. The whole path is strictly read-only (no write transaction, no undo entry,
no corruption path) and is backed by 6 Rust tests plus 2 Python end-to-end and
undo-safety tests. Living in Rust rather than per-platform Python/JS is what keeps
pacing behavior identical across desktop and phone — the brainlift's shared-engine
requirement. It grounds out in the speed-accuracy/MCAT-speededness work, the
test-anxiety and working-memory sources for hiding the timer early, and the
Blueprint/visible-pacing-drill sources for the later rungs.

## Robustness ("we will try to break it")

Data integrity is treated as part of honesty. Twenty mid-review hard-kills against
the real engine produced 0 corrupted collections and 0 committed reviews lost.
Live two-way sync merges 10+10 offline reviews into 20 distinct rows with 0
duplicates, and a same-card conflict resolves deterministically (the later answer
wins) while both review-log rows are kept. Corrupt collections and broken `.apkg`
files are refused as whole transactions so the live collection is never touched,
and a broken-image deck is reported yet still renders. Reviews faster than a human
could read (≤ 800 ms) are excluded from the honest graded-review count. These draw
on CRDT/last-writer-wins for the sync merge and the response-time-effort
literature for the rushed-review cutoff.
