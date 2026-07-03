"""In-app AI Transfer-Question generator (Speedrun MCAT).

This wires the standalone ``speedrun/ai`` pipeline into the desktop app as a real
feature: the user picks an existing deck, and the app generates NEW, reworded
exam-style questions grounded in that deck's cards -- the memory -> performance
bridge -- runs them through the same pre-ship gate, and adds only the cards that
PASS into a new practice deck they can study immediately.

Honesty / safety carried over from the pipeline:
* Every generated card cites the source card it came from.
* A card is added only if it is well-formed, grounded in its source, and a
  genuine rewording (not a copy) -- the gate blocks the rest.
* Live generation needs ANTHROPIC_API_KEY. With the key/SDK absent it degrades
  cleanly: it offers to add the committed, gate-passed sample AI deck instead, so
  the feature still demos with the AI "off".
* Adding the cards is a single undo entry, so undo works and the collection is
  never left half-written.
"""

from __future__ import annotations

import html as _html
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

import aqt
from anki.collection import OpChanges
from aqt.operations import CollectionOp, QueryOp
from aqt.qt import *
from aqt.utils import chooseList, getOnlyText, showInfo, showWarning

_LETTERS = ["A", "B", "C", "D", "E", "F"]
_TAG_RE = re.compile(r"<[^>]+>")

# Collection-config flag toggled from Tools -> "AI Practice Generator".
AI_ENABLED_KEY = "mcatAiEnabled"


def ai_enabled(col) -> bool:
    """Whether the in-app AI feature is switched on (default True)."""
    try:
        return bool(col.get_config(AI_ENABLED_KEY, True))
    except Exception:
        return True


# --------------------------------------------------------------------------
# speedrun.ai bootstrap (source/dev runs put the package at the repo root)
# --------------------------------------------------------------------------
def _ensure_speedrun_on_path() -> bool:
    try:
        import speedrun.ai  # noqa: F401

        return True
    except Exception:
        pass
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        import speedrun.ai  # noqa: F401

        return True
    except Exception:
        return False


def _plain(text: str) -> str:
    """Strip HTML/markup from a note field into plain source text."""
    no_tags = _TAG_RE.sub(" ", text or "")
    unescaped = _html.unescape(no_tags)
    return re.sub(r"\s+", " ", unescaped).strip()


def _card_html_front(item) -> str:
    parts: List[str] = [_html.escape(item.stem, quote=False), ""]
    for i, choice in enumerate(item.choices):
        letter = _LETTERS[i] if i < len(_LETTERS) else str(i)
        parts.append("{}. {}".format(letter, _html.escape(choice, quote=False)))
    return "<br>".join(parts)


def _card_html_back(item) -> str:
    idx = item.answer_index
    letter = _LETTERS[idx] if 0 <= idx < len(_LETTERS) else str(idx)
    blocks: List[str] = ["<b>Answer: {}. {}</b>".format(letter, _html.escape(item.correct_choice, quote=False))]
    if item.rationale:
        blocks.append(_html.escape(item.rationale, quote=False))
    blocks.append(
        "<i>Source: {}</i> &middot; "
        "<span style='opacity:.6'>AI transfer question (gate-passed)</span>".format(
            _html.escape(item.citation, quote=False)
        )
    )
    return "<br><br>".join(blocks)


def _to_card(item, source_tag: str) -> Dict[str, object]:
    return {
        "front": _card_html_front(item),
        "back": _card_html_back(item),
        "tags": ["ai-generated", "mcat-transfer", source_tag],
    }


# --------------------------------------------------------------------------
# Generation (runs in a background thread via QueryOp)
# --------------------------------------------------------------------------
def _build_source_units(col, deck_name: str, limit: int) -> List:
    from speedrun.ai.sources import SourceUnit

    query = 'deck:"{}"'.format(deck_name.replace('"', ""))
    nids = list(col.find_notes(query))[: max(1, limit)]
    units: List = []
    for nid in nids:
        note = col.get_note(nid)
        text = _plain(" \u2014 ".join(f for f in note.fields if f))
        if len(text) < 8:
            continue
        units.append(
            SourceUnit(
                source_id="deck-note-{}".format(nid),
                citation="{} \u00b7 card {}".format(deck_name, nid),
                text=text,
                topic=deck_name,
            )
        )
    return units


def _cached_passed_items() -> List:
    """The committed, gate-passed sample cards (offline / AI-off fallback)."""
    from speedrun.ai import checker as checker_mod
    from speedrun.ai import items as items_mod
    from speedrun.ai.sources import index_by_id, load_sources

    units = load_sources()
    by_id = index_by_id(units)
    gold = items_mod.load_gold()
    generated = items_mod.load_generated()
    report = checker_mod.gold_set_report(generated, by_id, gold)
    passed_ids = {r["item_id"] for r in report.rows if r["category"] == "correct_useful"}
    item_by_id = {it.id: it for it in generated}
    return [item_by_id[i] for i in passed_ids if i in item_by_id]


def _generate(col, deck_name: str, limit: int, n_per: int) -> Dict[str, object]:
    from speedrun.ai import config as ai_config
    from speedrun.ai import generator as gen_mod
    from speedrun.ai.checker import check_item

    source_tag = "src-" + re.sub(r"[^A-Za-z0-9]+", "-", deck_name).strip("-").lower()

    client = gen_mod._load_client(ai_config.DEFAULT_MODEL)
    if client is None:
        cards = [_to_card(it, "sample-ai") for it in _cached_passed_items()]
        return {"cards": cards, "mode": "cached", "sources": 0, "passed": len(cards), "blocked": 0}

    units = _build_source_units(col, deck_name, limit)
    if not units:
        return {"cards": [], "mode": "live", "sources": 0, "passed": 0, "blocked": 0}

    cards: List[Dict[str, object]] = []
    blocked = 0
    for idx, unit in enumerate(units):
        payload = gen_mod._call_claude(client, ai_config.DEFAULT_MODEL, unit, n_per)
        if payload is None:
            # If the very first request fails, the key/model/provider is broken --
            # don't grind through every card. Abort fast with a clear signal.
            if idx == 0 and not cards:
                return {
                    "cards": [],
                    "mode": "live_failed",
                    "sources": len(units),
                    "passed": 0,
                    "blocked": 0,
                }
            continue
        for item in gen_mod._parse_items(payload, unit, start_idx=len(cards) + blocked):
            res = check_item(item, unit, [])
            if res.passed:
                cards.append(_to_card(item, source_tag))
            else:
                blocked += 1
    return {
        "cards": cards,
        "mode": "live",
        "sources": len(units),
        "passed": len(cards),
        "blocked": blocked,
    }


# --------------------------------------------------------------------------
# Adding the cards (single undo entry via CollectionOp)
# --------------------------------------------------------------------------
def _add_cards(mw, target_deck: str, result: Dict[str, object]) -> None:
    cards = result.get("cards") or []
    if not cards:
        if result.get("mode") == "live_failed":
            showWarning(
                "Live AI generation failed on the first request \u2014 no cards were "
                "added.\n\nThis almost always means the API key or model is wrong. "
                "For Gemini, use a key from https://aistudio.google.com/apikey "
                "(it starts with \u201cAIza\u2026\u201d) and set GEMINI_API_KEY before "
                "launching. With no valid key, the generator uses the offline "
                "gate-passed sample set instead.",
                parent=mw,
                title="AI practice deck",
            )
            return
        showWarning(
            "No practice cards were produced. "
            "(Live generation needs a valid API key; the deck may also have no "
            "usable text.)",
            parent=mw,
            title="AI practice deck",
        )
        return

    def op(col) -> OpChanges:
        # Create the deck and resolve the notetype FIRST. Creating a deck resets
        # the undo queue, so it must happen *before* we open the custom undo
        # entry -- otherwise merge_undo_entries() can't find it ("target undo op
        # not found").
        did = col.decks.id(target_deck)
        notetype = col.models.by_name("Basic") or col.models.all()[0]
        pos = col.add_custom_undo_entry("Generate AI practice deck")
        changes: Optional[OpChanges] = None
        for card in cards:
            note = col.new_note(notetype)
            fields = note.keys()
            note[fields[0]] = str(card["front"])
            if len(fields) > 1:
                note[fields[1]] = str(card["back"])
            note.tags = list(card["tags"])  # type: ignore[arg-type]
            col.add_note(note, did)
        try:
            changes = col.merge_undo_entries(pos)
        except Exception:
            # If the undo entry was reset for any reason, the notes were still
            # added correctly; fall back to a plain change signal so the UI
            # refreshes rather than surfacing an undo-bookkeeping error.
            changes = OpChanges()
        return changes

    mode = result.get("mode")
    n = len(cards)

    def on_success(_out: OpChanges) -> None:
        blocked = result.get("blocked") or 0
        if mode == "cached":
            msg = (
                "Added {} sample AI transfer cards to \u201c{}\u201d.\n\n"
                "(No ANTHROPIC_API_KEY detected, so this used the committed, "
                "gate-passed sample set. Set the key to generate live from your "
                "own deck.)".format(n, target_deck)
            )
        else:
            msg = (
                "Added {} gate-passed AI practice cards to \u201c{}\u201d "
                "(blocked {} that failed the grounding / transfer / well-formed "
                "gate).\n\nEvery card cites the source card it was generated "
                "from.".format(n, target_deck, blocked)
            )
        showInfo(msg, parent=mw, title="AI practice deck")
        mw.reset()

    CollectionOp(parent=mw, op=op).success(on_success).run_in_background()


# --------------------------------------------------------------------------
# Entry point (called from the deck browser button)
# --------------------------------------------------------------------------
def generate_practice_deck(mw) -> None:
    if not _ensure_speedrun_on_path():
        showWarning(
            "Could not load the AI subsystem (speedrun.ai). This feature is "
            "available in a source/dev run of the app.",
            parent=mw,
            title="AI practice deck",
        )
        return
    if mw.col is None:
        return
    if not ai_enabled(mw.col):
        showInfo(
            "The AI Practice Generator is turned off. Enable it under "
            "Tools \u2192 \u201cAI Practice Generator\u201d.",
            parent=mw,
            title="AI practice deck",
        )
        return

    decks = [
        d
        for d in mw.col.decks.all_names_and_ids(include_filtered=False)
        if d.name != "Default"
    ]
    if not decks:
        showInfo("No decks to generate from yet.", parent=mw, title="AI practice deck")
        return
    names = [d.name for d in decks]

    idx = chooseList(
        "Generate AI practice questions from which deck?\n\n"
        "The app will write NEW, reworded exam-style questions grounded in that "
        "deck's cards, gate-check them, and add the ones that pass to a new "
        "practice deck.",
        names,
        parent=mw,
    )
    source_name = names[idx]

    raw = getOnlyText(
        "How many cards from this deck to use as sources? (1\u201350)",
        parent=mw,
        default="10",
    )
    if raw is None or not raw.strip():
        return
    try:
        limit = max(1, min(50, int(raw.strip())))
    except ValueError:
        showWarning("Please enter a whole number between 1 and 50.", parent=mw)
        return

    target_deck = "{} (AI Practice)".format(source_name)

    QueryOp(
        parent=mw,
        op=lambda col: _generate(col, source_name, limit, n_per=1),
        success=lambda result: _add_cards(mw, target_deck, result),
    ).with_progress(
        "Generating AI transfer questions\u2026"
    ).run_in_background()
