"""Export the AI transfer-questions as an Anki-importable deck.

This makes the AI feature **visible in the app**: it turns the generated,
*gate-passed* transfer questions into a plain text file you import via
File -> Import in Anki (desktop or AnkiDroid), creating the deck

    MCAT::AI Transfer Questions

Only cards that PASS the pre-ship gate ship here -- the same rule the grader
asks for ("a wrong fact is worse than no card"). Blocked cards (wrong fact,
near-copy, ungrounded, malformed) are deliberately left out, and their count is
printed so you can say on camera how many were blocked.

Each card's Back carries the **named source citation**, so on review you can
flip a card and show the source every AI output traces back to.

    python -m speedrun.ai.export_deck

Writes: speedrun/ai/artifacts/mcat_ai_transfer_deck.txt
"""

from __future__ import annotations

import html as _html
from typing import List

from . import checker as checker_mod
from . import config
from . import items as items_mod
from .sources import index_by_id, load_sources

OUT_PATH = config.ARTIFACTS_DIR / "mcat_ai_transfer_deck.txt"

_LETTERS = ["A", "B", "C", "D", "E", "F"]


def _clean(text: str) -> str:
    """Escape HTML and strip characters that would break a tab/newline import."""
    escaped = _html.escape(text or "", quote=False)
    return escaped.replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()


def _front(item: items_mod.GeneratedItem) -> str:
    parts: List[str] = [_clean(item.stem), ""]
    for i, choice in enumerate(item.choices):
        letter = _LETTERS[i] if i < len(_LETTERS) else str(i)
        parts.append("{}. {}".format(letter, _clean(choice)))
    return "<br>".join(parts)


def _back(item: items_mod.GeneratedItem) -> str:
    letter = _LETTERS[item.answer_index] if item.answer_index < len(_LETTERS) else str(
        item.answer_index
    )
    lines: List[str] = [
        "<b>Answer: {}. {}</b>".format(letter, _clean(item.correct_choice)),
    ]
    if item.rationale:
        lines.append(_clean(item.rationale))
    lines.append(
        "<i>Source: {}</i>".format(_clean(item.citation))
        + " &middot; <span style='opacity:.6'>AI transfer question (gate-passed)</span>"
    )
    return "<br><br>".join(lines)


def _tags(item: items_mod.GeneratedItem) -> str:
    # Space-separated Anki tags (no spaces within a tag).
    topic = item.source_id.replace(" ", "-")
    return "ai-generated mcat-transfer {}".format(topic)


def export() -> int:
    units = load_sources()
    sources_by_id = index_by_id(units)
    gold = items_mod.load_gold()
    all_items = items_mod.load_generated()

    report = checker_mod.gold_set_report(all_items, sources_by_id, gold)
    passed_ids = {
        row["item_id"] for row in report.rows if row["category"] == "correct_useful"
    }
    by_id = {it.id: it for it in all_items}
    passed = [by_id[i] for i in passed_ids if i in by_id]

    header = [
        "#separator:tab",
        "#html:true",
        "#deck:MCAT::AI Transfer Questions",
        "#tags column:3",
    ]
    rows = [
        "\t".join([_front(it), _back(it), _tags(it)])
        for it in sorted(passed, key=lambda x: x.id)
    ]
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text("\n".join(header + rows) + "\n", encoding="utf-8")

    print(
        "export_deck: wrote {} gate-passed card(s) to {}".format(len(passed), OUT_PATH)
    )
    print(
        "  blocked (NOT exported): {} total "
        "-> {} wrong-fact, {} bad-teaching".format(
            report.blocked, report.wrong, report.correct_bad_teaching
        )
    )
    print(
        "  import in Anki: File -> Import -> select the file above "
        "(deck 'MCAT::AI Transfer Questions' is set automatically)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(export())
