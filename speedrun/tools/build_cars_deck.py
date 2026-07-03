#!/usr/bin/env python3
"""Build an importable MCAT CARS deck for the Speedrun fork.

Why this exists / honesty note
------------------------------
The Khan Academy MCAT CARS practice page

    https://www.khanacademy.org/test-prep/mcat/critical-analysis-and-reasoning-skills-practice-questions

is bot-blocked to automated fetches (it returns a Cloudflare "Client Challenge"
to any script), and reproducing its passages verbatim would be a copyright
problem for an AGPL repo. CARS, uniquely among MCAT sections, tests *content-
independent* reasoning: there are no facts to memorize, only comprehension and
reasoning about an unfamiliar humanities / social-science passage. So this deck
ships **original passages written in the Khan Academy CARS style** -- same
disciplines (humanities + social sciences), same three AAMC skill categories,
same "answer only from the text" discipline -- with **no Khan text reproduced**.
Every card is cited to the Khan CARS page as its pedagogical model.

If you have real Khan passages you are licensed to use, paste them into
``speedrun/ai/sources/khan_cars_example.txt`` (or extend ``PASSAGES`` below) and
re-run; the builder is content-agnostic.

CARS is graded qualitatively (interpretive answers), so these cards are NOT part
of the auto-checked science gold set (7f) -- consistent with the note in
``khan_cars_example.txt``.

What it produces (under ``speedrun/decks/``)
--------------------------------------------
* ``mcat_cars_khan_style.apkg`` -- double-click / File > Import into Anki. Safe
  to import while Anki is running; it never touches the live collection.
* ``mcat_cars_khan_style.txt`` -- a plain-text fallback (tab-separated, HTML on)
  that imports the same notes via File > Import if the .apkg ever fails.

Run (from repo root ``C:\\dev\\speedrun\\anki``):

    $env:PYTHONPATH="C:\\dev\\speedrun\\anki\\out\\pylib"; `
      & "C:\\dev\\speedrun\\anki\\out\\pyenv\\Scripts\\python.exe" `
      speedrun\\tools\\build_cars_deck.py
"""

from __future__ import annotations

import html
import os
import sys
import tempfile

KHAN_URL = (
    "https://www.khanacademy.org/test-prep/mcat/"
    "critical-analysis-and-reasoning-skills-practice-questions"
)
DECK_NAME = "MCAT::CARS (Khan-style)"

# AAMC CARS skill categories (the three things CARS questions test).
SKILL_FOUND = "Foundations of Comprehension"
SKILL_WITHIN = "Reasoning Within the Text"
SKILL_BEYOND = "Reasoning Beyond the Text"

_SKILL_TAG = {
    SKILL_FOUND: "CARS::Foundations_of_Comprehension",
    SKILL_WITHIN: "CARS::Reasoning_Within_the_Text",
    SKILL_BEYOND: "CARS::Reasoning_Beyond_the_Text",
}

# ---------------------------------------------------------------------------
# Content: original CARS-style passages (humanities + social sciences).
# Each question has exactly one defensible best answer supported by the text.
# ---------------------------------------------------------------------------
PASSAGES: list[dict] = [
    {
        "id": "cars01",
        "title": "The Uses of Difficulty",
        "discipline": "Philosophy of Art (Humanities)",
        "paras": [
            "It has become fashionable to defend difficult art on the grounds that "
            "the effort it demands is itself rewarding \u2014 that a poem which yields "
            "its meaning only after a struggle trains the mind as exercise trains the "
            "body. There is something to this, but the analogy flatters the artwork "
            "more than it deserves. Exercise is difficult in a way that is transparent: "
            "we know why lifting a heavy weight is hard, and the difficulty is the whole "
            "point. Much difficult art, by contrast, is obscure rather than demanding. "
            "Its resistance comes not from the depth of what it says but from the "
            "author\u2019s refusal, or inability, to say it clearly.",
            "The distinction matters because it changes who bears responsibility for a "
            "failure of understanding. When a difficulty is genuine, the reader who does "
            "not understand has more work to do. When a difficulty is merely obscure, it "
            "is the writer who has failed, and the reader who blames herself has been "
            "quietly conscripted into flattering the work. The most cunning obscurity is "
            "the kind that cannot be distinguished from depth without patient labor \u2014 "
            "for by the time the labor is done, one is reluctant to conclude that it was "
            "wasted.",
        ],
        "questions": [
            {
                "stem": "The author\u2019s central claim is that difficult art:",
                "choices": [
                    "is always less valuable than art that is easy to understand.",
                    "should be defended because the effort it requires improves the mind.",
                    "can be worthwhile, but is often obscure in a way that misplaces blame for not understanding it.",
                    "is impossible to distinguish from obscure art under any circumstances.",
                ],
                "answer": 2,
                "skill": SKILL_FOUND,
                "why": (
                    "The passage grants that difficulty \u201ccan be worthwhile\u201d (\u201cThere is "
                    "something to this\u201d) but argues its real target: obscurity that makes the "
                    "reader wrongly blame herself. <b>A</b> and <b>B</b> are too absolute (B is the "
                    "view the author critiques). <b>D</b> overstates: the author says the two are "
                    "hard to tell apart <i>without patient labor</i>, not never."
                ),
            },
            {
                "stem": (
                    "The author draws the analogy between difficult art and physical "
                    "exercise primarily in order to:"
                ),
                "choices": [
                    "endorse the popular defense of difficult art.",
                    "introduce a comparison and then show where it breaks down.",
                    "prove that art has measurable benefits like exercise does.",
                    "argue that reading should be as strenuous as possible.",
                ],
                "answer": 1,
                "skill": SKILL_WITHIN,
                "why": (
                    "The author raises the exercise analogy only to say it \u201cflatters the artwork "
                    "more than it deserves,\u201d then distinguishes transparent difficulty from "
                    "obscurity. The analogy is set up to be undercut. <b>A</b> reverses the author\u2019s "
                    "stance; <b>C</b> and <b>D</b> are not claims the author makes."
                ),
            },
            {
                "stem": (
                    "Suppose a critic praises a notoriously murky novel, saying \u201cIf you "
                    "don\u2019t get it, read it again \u2014 the fault is yours.\u201d The author would "
                    "most likely respond that this critic:"
                ),
                "choices": [
                    "is correct, since understanding difficult work is the reader\u2019s job.",
                    "may be mistaking obscurity for depth and shifting blame onto the reader.",
                    "has proven the novel is a masterpiece.",
                    "should never have attempted to read a difficult novel.",
                ],
                "answer": 1,
                "skill": SKILL_BEYOND,
                "why": (
                    "This applies the passage\u2019s key worry \u2014 readers \u201cquietly conscripted into "
                    "flattering the work\u201d \u2014 to a new case. <b>A</b> is the very move the author warns "
                    "against; <b>C</b> and <b>D</b> don\u2019t follow from the text."
                ),
            },
        ],
    },
    {
        "id": "cars02",
        "title": "Moral Panics",
        "discipline": "Sociology (Social Sciences)",
        "paras": [
            "A moral panic occurs when a condition, episode, or group comes to be "
            "defined as a threat to a society\u2019s values, and the reaction to it is out of "
            "proportion to the actual danger. Sociologists have noted that such panics "
            "tend to follow a pattern: a triggering incident is amplified by media "
            "coverage, experts and officials issue warnings, the threat is symbolized by "
            "a recognizable figure \u2014 the delinquent, the addict, the hacker \u2014 and "
            "measures are demanded that often outlast the panic that produced them.",
            "It would be a mistake, however, to conclude that because a reaction is "
            "disproportionate the underlying concern is imaginary. Panics frequently "
            "attach themselves to real problems; what is distorted is the scale, the "
            "cause, or the remedy, not necessarily the existence of the thing feared. "
            "The analytic value of the concept lies precisely here: it directs attention "
            "away from the question \u201cIs this threat real?\u201d and toward the more revealing "
            "question \u201cWhy is it being framed in this way, now, by these people?\u201d",
        ],
        "questions": [
            {
                "stem": "According to the passage, the concept of a \u201cmoral panic\u201d is most useful because it:",
                "choices": [
                    "proves that the public\u2019s fears are usually groundless.",
                    "redirects analysis from whether a threat is real to how and why it is being framed.",
                    "identifies which social groups are genuinely dangerous.",
                    "shows that media coverage always creates threats where none exist.",
                ],
                "answer": 1,
                "skill": SKILL_FOUND,
                "why": (
                    "The final sentence states the concept\u2019s value: it shifts attention to \u201cWhy is "
                    "it being framed in this way, now, by these people?\u201d <b>A</b> and <b>D</b> contradict "
                    "the second paragraph (panics often attach to real problems); <b>C</b> is not the "
                    "concept\u2019s purpose."
                ),
            },
            {
                "stem": (
                    "The author includes the second paragraph mainly to:"
                ),
                "choices": [
                    "qualify the first paragraph so \u201cdisproportionate\u201d is not read as \u201cbaseless.\u201d",
                    "abandon the definition of moral panic offered earlier.",
                    "argue that experts and officials are usually correct.",
                    "provide statistical evidence for a specific panic.",
                ],
                "answer": 0,
                "skill": SKILL_WITHIN,
                "why": (
                    "Paragraph two guards against a misreading: \u201cIt would be a mistake\u2026 to conclude "
                    "that because a reaction is disproportionate the underlying concern is imaginary.\u201d "
                    "It refines, not abandons, the definition. <b>C</b> and <b>D</b> aren\u2019t supported."
                ),
            },
            {
                "stem": (
                    "A public-health scholar shows that fear of a new drug led to harsh laws, "
                    "even though the drug does cause real harm at lower rates than claimed. This "
                    "case best supports the passage\u2019s point that panics:"
                ),
                "choices": [
                    "always target nonexistent dangers.",
                    "can distort the scale or remedy of a genuine problem rather than invent it.",
                    "are indistinguishable from rational policy.",
                    "disappear as soon as the media loses interest.",
                ],
                "answer": 1,
                "skill": SKILL_BEYOND,
                "why": (
                    "The drug \u201cdoes cause real harm\u201d but the scale is exaggerated and the remedy harsh "
                    "\u2014 exactly \u201cwhat is distorted is the scale\u2026 the remedy, not necessarily the "
                    "existence of the thing feared.\u201d <b>A</b> is contradicted; <b>D</b> conflicts with "
                    "\u201cmeasures\u2026 often outlast the panic.\u201d"
                ),
            },
        ],
    },
    {
        "id": "cars03",
        "title": "Great Men and Slow Forces",
        "discipline": "Historiography (Humanities)",
        "paras": [
            "For a long time history was written as biography on a grand scale: the "
            "story of kings, generals, and founders whose decisions bent the course of "
            "events. Against this, a later generation of historians insisted that the "
            "true engines of change were impersonal and slow \u2014 climate, trade routes, "
            "demography, the price of grain \u2014 and that the famous individual was less a "
            "cause than a symptom, carried by currents he mistook for his own will.",
            "Both schools capture something and miss something. The first is right that "
            "particular choices, made at particular moments, sometimes foreclose futures "
            "that were genuinely possible; the second is right that those choices are made "
            "within constraints no individual authored. The unsatisfying but honest "
            "conclusion is that structure sets the range of the possible while agency "
            "selects within it \u2014 and that the proportion between them is not fixed, but "
            "varies from one episode to the next.",
        ],
        "questions": [
            {
                "stem": "The passage as a whole is best described as:",
                "choices": [
                    "a defense of the \u2018great man\u2019 theory of history.",
                    "a rejection of both schools in favor of a third, unrelated approach.",
                    "an attempt to reconcile two views by assigning each a partial role.",
                    "a claim that history has no discernible causes at all.",
                ],
                "answer": 2,
                "skill": SKILL_FOUND,
                "why": (
                    "The author says \u201cBoth schools capture something and miss something\u201d and "
                    "concludes structure sets the range while agency selects within it \u2014 a "
                    "reconciliation. <b>A</b> and <b>D</b> are one-sided; <b>B</b> is wrong because the "
                    "synthesis is built from the two schools, not unrelated to them."
                ),
            },
            {
                "stem": (
                    "The phrase describing the famous individual as \u201cless a cause than a "
                    "symptom\u201d is used to convey the second school\u2019s view that:"
                ),
                "choices": [
                    "individuals are ill and require diagnosis.",
                    "prominent figures reflect underlying forces more than they direct them.",
                    "biography is the best way to understand history.",
                    "impersonal forces are irrelevant to historical change.",
                ],
                "answer": 1,
                "skill": SKILL_WITHIN,
                "why": (
                    "\u201cSymptom\u201d is metaphorical: the individual is an outward sign of deeper currents "
                    "(\u201ccarried by currents he mistook for his own will\u201d). <b>A</b> takes the metaphor "
                    "literally; <b>C</b>/<b>D</b> state views the second school opposes."
                ),
            },
        ],
    },
    {
        "id": "cars04",
        "title": "The Author\u2019s Intentions",
        "discipline": "Literary Theory (Humanities)",
        "paras": [
            "A durable idea in criticism holds that what an author meant to do is "
            "irrelevant to judging what the work does; the poem, once written, belongs to "
            "its readers, and appeals to private intention are both unavailable and beside "
            "the point. This position rightly frees interpretation from fruitless "
            "speculation about a writer\u2019s inner life. Yet it purchases that freedom at a "
            "cost that is rarely acknowledged.",
            "For meaning is not a property that texts possess in isolation; it depends on "
            "recognizing a text as the kind of thing it is \u2014 a sonnet, a satire, a legal "
            "brief \u2014 and such recognition already imports assumptions about a maker\u2019s "
            "purpose. To read a passage as ironic, for instance, is to attribute to someone "
            "the intention to be ironic; strip away every notion of intent and irony "
            "becomes indistinguishable from error. The critic who banishes intention at the "
            "front door tends to readmit it, unnamed, through the back.",
        ],
        "questions": [
            {
                "stem": "The author\u2019s attitude toward the view that authorial intention is irrelevant can best be described as:",
                "choices": [
                    "wholehearted agreement.",
                    "partial acceptance combined with a significant objection.",
                    "complete dismissal as nonsense.",
                    "indifference to the debate.",
                ],
                "answer": 1,
                "skill": SKILL_FOUND,
                "why": (
                    "The author credits the view (\u201crightly frees interpretation\u2026\u201d) but argues it "
                    "smuggles intention back in via irony and genre. That is partial acceptance plus a "
                    "serious objection \u2014 not full agreement (<b>A</b>), dismissal (<b>C</b>), or "
                    "indifference (<b>D</b>)."
                ),
            },
            {
                "stem": (
                    "The claim that the critic \u201creadmits\u201d intention \u201cthrough the back\u201d most "
                    "directly implies that:"
                ),
                "choices": [
                    "critics are dishonest about their methods.",
                    "interpreting a text (e.g., as ironic) unavoidably relies on assumptions about purpose.",
                    "irony is impossible to detect in any text.",
                    "authors should explain their intentions in prefaces.",
                ],
                "answer": 1,
                "skill": SKILL_WITHIN,
                "why": (
                    "The \u2018back door\u2019 image restates the paragraph\u2019s argument: recognizing irony "
                    "\u201cis to attribute to someone the intention to be ironic.\u201d It is about a logical "
                    "dependence, not dishonesty (<b>A</b>). <b>C</b> and <b>D</b> aren\u2019t implied."
                ),
            },
            {
                "stem": (
                    "Which finding, if true, would most WEAKEN the author\u2019s argument?"
                ),
                "choices": [
                    "Readers routinely infer an author\u2019s purpose when identifying a text\u2019s genre.",
                    "Skilled readers can reliably tell irony from error using only textual features, with no assumption about a maker\u2019s intent.",
                    "Some authors deliberately conceal their intentions.",
                    "Genres such as satire have existed for centuries.",
                ],
                "answer": 1,
                "skill": SKILL_BEYOND,
                "why": (
                    "The author\u2019s case rests on irony being unrecognizable without attributing intent. "
                    "If readers could distinguish irony from error <i>without</i> any assumption of intent "
                    "(<b>B</b>), the central example collapses. <b>A</b> and <b>D</b> support the author; "
                    "<b>C</b> is irrelevant to whether intent is needed to interpret."
                ),
            },
        ],
    },
    {
        "id": "cars05",
        "title": "The Circle of Obligation",
        "discipline": "Political Philosophy (Humanities)",
        "paras": [
            "Cosmopolitans argue that a human being\u2019s moral worth does not depend on "
            "where a border happens to fall, and that we therefore owe strangers abroad "
            "the same fundamental consideration we grant compatriots. Critics reply that "
            "obligations are not free-floating but grow out of relationships \u2014 family, "
            "community, nation \u2014 and that a duty owed to everyone equally is, in practice, "
            "a duty owed to no one in particular.",
            "The disagreement is often framed as a contest between principle and "
            "sentiment, as though the cosmopolitan reasons while the critic merely feels. "
            "But this is unfair to the critic, whose claim is itself a principled one: that "
            "the special ties which generate partial duties are not lapses from morality "
            "but part of its substance. The cosmopolitan need not deny this. He can concede "
            "that we may permissibly do more for our own while insisting there is a floor "
            "\u2014 a minimum owed to anyone \u2014 beneath which partiality may not sink.",
        ],
        "questions": [
            {
                "stem": "The passage suggests that the strongest version of the cosmopolitan position:",
                "choices": [
                    "denies that we have any special duties to family or community.",
                    "accepts special duties but insists on a minimum owed to everyone.",
                    "holds that sentiment should override principle.",
                    "concludes that borders determine moral worth.",
                ],
                "answer": 1,
                "skill": SKILL_FOUND,
                "why": (
                    "The last sentence has the cosmopolitan <i>concede</i> partial duties while insisting "
                    "on \u201ca floor \u2014 a minimum owed to anyone.\u201d <b>A</b> is the crude version the author "
                    "moves past; <b>C</b> and <b>D</b> reverse positions in the text."
                ),
            },
            {
                "stem": (
                    "The author objects to framing the debate as \u201cprinciple versus sentiment\u201d "
                    "because that framing:"
                ),
                "choices": [
                    "makes the cosmopolitan look unreasonable.",
                    "wrongly treats the critic\u2019s view as mere feeling rather than a principled claim.",
                    "ignores the role of borders in ethics.",
                    "proves the critic is correct.",
                ],
                "answer": 1,
                "skill": SKILL_WITHIN,
                "why": (
                    "The author says the framing \u201cis unfair to the critic, whose claim is itself a "
                    "principled one.\u201d The objection defends the critic\u2019s reasoning, without declaring "
                    "the critic correct (<b>D</b>). <b>A</b> and <b>C</b> aren\u2019t the stated reason."
                ),
            },
        ],
    },
    {
        "id": "cars06",
        "title": "The Logic of the Gift",
        "discipline": "Cultural Anthropology (Social Sciences)",
        "paras": [
            "In many societies the exchange of gifts is not a quaint alternative to the "
            "market but the very framework of social life. A gift, unlike a purchase, is "
            "never quite free: it creates a debt, and the debt creates a bond. To give is "
            "to place another under a gentle obligation to reciprocate, not immediately "
            "\u2014 an instant return would insult the gesture by treating it as a transaction "
            "\u2014 but eventually, and in a form that keeps the relationship alive.",
            "Modern readers sometimes romanticize such systems as generous where markets "
            "are cold. This misses their point. Gift economies are not less interested than "
            "markets; they are interested differently. What circulates is not merely goods "
            "but standing, allegiance, and memory. A society that runs on gifts can be as "
            "calculating as one that runs on prices \u2014 the calculation is simply about "
            "relationships rather than about goods, and it is the more binding for being "
            "unspoken.",
        ],
        "questions": [
            {
                "stem": "The main point of the passage is that gift economies:",
                "choices": [
                    "are morally superior to market economies because they are generous.",
                    "involve their own form of calculation, aimed at relationships rather than goods.",
                    "are inefficient survivals that markets have rightly replaced.",
                    "require immediate repayment to maintain social bonds.",
                ],
                "answer": 1,
                "skill": SKILL_FOUND,
                "why": (
                    "The passage explicitly rejects romanticizing gifts as simply generous: they are "
                    "\u201cinterested differently\u201d and \u201cas calculating\u201d as markets, but about relationships. "
                    "<b>A</b>/<b>C</b> are the romantic or dismissive views the author rejects; <b>D</b> "
                    "contradicts \u201can instant return would insult the gesture.\u201d"
                ),
            },
            {
                "stem": (
                    "The statement that a gift is \u201cnever quite free\u201d functions in the argument to:"
                ),
                "choices": [
                    "condemn gift-giving as secretly selfish.",
                    "establish that gifts create obligations, which is the basis of the social bonds discussed.",
                    "suggest that gifts should be replaced by purchases.",
                    "prove that markets are dishonest.",
                ],
                "answer": 1,
                "skill": SKILL_WITHIN,
                "why": (
                    "\u201cNever quite free\u201d launches the point that a gift \u201ccreates a debt, and the debt "
                    "creates a bond.\u201d It sets up the mechanism of social ties, not a condemnation "
                    "(<b>A</b>) or a claim about markets (<b>C</b>/<b>D</b>)."
                ),
            },
            {
                "stem": (
                    "A tech company gives lavish free services to users, cultivating loyalty and "
                    "future spending. The author would most likely see this as:"
                ),
                "choices": [
                    "a pure gift with no expectation of return.",
                    "consistent with the passage: an \u2018interested\u2019 gift that builds a binding relationship.",
                    "proof that gift economies cannot exist in modern life.",
                    "an insult, since the return is not immediate.",
                ],
                "answer": 1,
                "skill": SKILL_BEYOND,
                "why": (
                    "The scenario matches the passage\u2019s thesis that gifts are \u201cinterested differently,\u201d "
                    "circulating \u201callegiance\u201d and building bonds that bind. <b>A</b> ignores the cultivated "
                    "loyalty; <b>C</b> and <b>D</b> misapply the text."
                ),
            },
        ],
    },
]

LETTERS = ["A", "B", "C", "D", "E", "F"]

CARD_STYLE = (
    "<style>"
    ".cars{font-family:Georgia,'Times New Roman',serif;font-size:17px;line-height:1.5;"
    "color:#1a1a1a;max-width:720px;margin:0 auto;text-align:left;}"
    ".cars .tag{font-family:-apple-system,Segoe UI,Arial,sans-serif;font-size:11px;"
    "letter-spacing:.06em;text-transform:uppercase;color:#8a6d3b;background:#fcf8e3;"
    "display:inline-block;padding:3px 9px;border-radius:4px;margin-bottom:12px;}"
    ".cars .passage{background:#f6f7f9;border-left:3px solid #cbd5e0;padding:10px 14px;"
    "border-radius:4px;margin-bottom:14px;}"
    ".cars .disc{font-size:12px;color:#667;font-style:italic;margin-bottom:6px;}"
    ".cars .q{font-weight:bold;margin:12px 0 8px;}"
    ".cars ol.choices{margin:0 0 4px 1.3em;padding:0;}"
    ".cars ol.choices li{margin:5px 0;}"
    "#answer{margin:16px 0;border:0;border-top:1px solid #ddd;}"
    ".cars .ans{color:#1a7f37;font-weight:bold;font-size:18px;}"
    ".cars .why{margin-top:8px;}"
    ".cars .skill{margin-top:10px;color:#553c9a;font-size:14px;}"
    ".cars .src{margin-top:10px;color:#777;font-size:12px;}"
    "</style>"
)


def _front_html(p: dict, q: dict) -> str:
    choices = "".join("<li>{}</li>".format(html.escape(c)) for c in q["choices"])
    passage = "<br><br>".join(html.escape(par) for par in p["paras"])
    return (
        CARD_STYLE
        + '<div class="cars">'
        + '<div class="tag">MCAT CARS &middot; {}</div>'.format(html.escape(q["skill"]))
        + '<div class="disc">{}</div>'.format(html.escape(p["discipline"]))
        + '<div class="passage"><b>{}</b><br><br>{}</div>'.format(
            html.escape(p["title"]), passage
        )
        + '<div class="q">{}</div>'.format(html.escape(q["stem"]))
        + '<ol type="A" class="choices">{}</ol>'.format(choices)
        + "</div>"
    )


def _back_html(p: dict, q: dict) -> str:
    letter = LETTERS[q["answer"]]
    ans_text = q["choices"][q["answer"]]
    return (
        '<div class="cars">'
        + '<div class="ans">Answer: {}. {}</div>'.format(letter, html.escape(ans_text))
        + '<div class="why"><b>Why:</b> {}</div>'.format(q["why"])
        + '<div class="skill"><b>CARS skill tested:</b> {}</div>'.format(
            html.escape(q["skill"])
        )
        + '<div class="src"><b>Source:</b> Original passage in the style of the '
        + '<a href="{}">Khan Academy MCAT CARS practice set</a>. '.format(KHAN_URL)
        + "No Khan Academy text is reproduced; CARS tests content-independent "
        + "reasoning about an unfamiliar passage.</div>"
        + "</div>"
    )


def _tags(p: dict, q: dict) -> list[str]:
    return [
        "MCAT",
        "CARS",
        _SKILL_TAG[q["skill"]],
        "source::khan-cars-style",
        "passage::{}".format(p["id"]),
    ]


def _iter_cards():
    for p in PASSAGES:
        for qi, q in enumerate(p["questions"], start=1):
            yield p, q, qi


def _write_text_fallback(txt_path: str) -> int:
    """Tab-separated import file (notetype Basic). Imports anywhere, HTML on."""
    n = 0
    lines = [
        "#separator:tab",
        "#html:true",
        "#notetype:Basic",
        "#deck:{}".format(DECK_NAME),
        "#tags column:3",
    ]
    for p, q, _qi in _iter_cards():
        front = _front_html(p, q).replace("\t", " ").replace("\n", " ")
        back = _back_html(p, q).replace("\t", " ").replace("\n", " ")
        tags = " ".join(_tags(p, q))
        lines.append("{}\t{}\t{}".format(front, back, tags))
        n += 1
    with open(txt_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return n


def _build_apkg(apkg_path: str) -> int:
    from anki.collection import Collection

    tmpdir = tempfile.mkdtemp(prefix="cars_build_")
    col_path = os.path.join(tmpdir, "cars.anki2")
    col = Collection(col_path)
    n = 0
    try:
        basic = col.models.by_name("Basic")
        if basic is None:
            raise RuntimeError("Basic notetype missing from fresh collection")
        did = col.decks.id(DECK_NAME)
        for p, q, _qi in _iter_cards():
            note = col.new_note(basic)
            note.fields[0] = _front_html(p, q)
            note.fields[1] = _back_html(p, q)
            note.tags = _tags(p, q)
            col.add_note(note, did)
            n += 1
        col.save()

        # Export just the CARS deck as a .apkg (no scheduling, no media).
        try:
            from anki.exporting import AnkiPackageExporter

            exp = AnkiPackageExporter(col)
            exp.did = did
            exp.includeSched = False
            exp.includeMedia = False
            exp.exportInto(apkg_path)
        except Exception as legacy_err:  # pragma: no cover - fallback path
            print("legacy exporter failed ({}); trying modern API".format(legacy_err))
            from anki.collection import (
                DeckIdLimit,
                ExportAnkiPackageOptions,
            )

            opts = ExportAnkiPackageOptions()
            opts.with_scheduling = False
            opts.with_media = False
            opts.legacy = True
            col.export_anki_package(
                out_path=apkg_path,
                options=opts,
                limit=DeckIdLimit(deck_id=did),
            )
    finally:
        col.close()
    return n


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.abspath(os.path.join(here, "..", ".."))
    out_dir = os.path.join(repo, "speedrun", "decks")
    os.makedirs(out_dir, exist_ok=True)

    apkg_path = os.path.join(out_dir, "mcat_cars_khan_style.apkg")
    txt_path = os.path.join(out_dir, "mcat_cars_khan_style.txt")

    total_q = sum(len(p["questions"]) for p in PASSAGES)
    print(
        "Building MCAT CARS deck: {} passages, {} cards -> {}".format(
            len(PASSAGES), total_q, DECK_NAME
        )
    )

    n_txt = _write_text_fallback(txt_path)
    print("wrote text fallback: {} ({} notes)".format(txt_path, n_txt))

    try:
        n_apkg = _build_apkg(apkg_path)
        size_kb = os.path.getsize(apkg_path) / 1024
        print("wrote apkg        : {} ({} notes, {:.1f} KB)".format(apkg_path, n_apkg, size_kb))
    except Exception as err:
        print("APKG BUILD FAILED: {}".format(err))
        print("The .txt fallback is still usable via File > Import.")
        return 1

    print("---- DONE ----")
    print("Import: open Anki -> File > Import -> select the .apkg (safe while running).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
