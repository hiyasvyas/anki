# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

import os
import tempfile

from anki.collection import CardStats
from tests.shared import getEmptyCol


def test_stats():
    col = getEmptyCol()
    note = col.newNote()
    note["Front"] = "foo"
    col.addNote(note)
    c = note.cards()[0]
    # card stats
    card_stats = col.card_stats_data(c.id)
    assert card_stats.note_id == note.id
    c = col.sched.getCard()
    col.sched.answerCard(c, 3)
    col.sched.answerCard(c, 2)
    card_stats = col.card_stats_data(c.id)
    assert len(card_stats.revlog) == 2


def test_graphs_empty():
    col = getEmptyCol()
    assert col.stats().report()


def test_graphs():
    dir = tempfile.gettempdir()
    col = getEmptyCol()
    g = col.stats()
    rep = g.report()
    with open(os.path.join(dir, "test.html"), "w", encoding="UTF-8") as note:
        note.write(rep)
    return


def test_mcat_engine_status():
    # Speedrun: proves a new Rust RPC reaches Python end to end.
    col = getEmptyCol()
    status = col._backend.mcat_engine_status()
    assert status.engine_tag == "speedrun-ok"
    assert status.total_cards == 0
    note = col.newNote()
    note["Front"] = "foo"
    col.addNote(note)
    status = col._backend.mcat_engine_status()
    assert status.total_cards == 1


def test_mcat_mastery():
    # Speedrun: per-topic mastery breakdown over the shared Rust engine.
    col = getEmptyCol()
    assert col._backend.mcat_mastery(search="").total_cards == 0

    note = col.newNote()
    note["Front"] = "foo"
    col.addNote(note)

    report = col._backend.mcat_mastery(search="")
    assert report.total_cards == 1
    # A brand-new, unreviewed card has no memory state, so it can't be mastered.
    assert report.mastered_cards == 0
    assert len(report.topics) == 1
    topic = report.topics[0]
    assert topic.total_cards == 1
    assert topic.rated_cards == 0
    assert topic.mastered_cards == 0
    assert 0.0 < report.mastered_threshold <= 1.0


def test_mcat_deck_score():
    # Speedrun: honest deck score (point estimate + confidence range) over the
    # Rust engine.
    col = getEmptyCol()
    empty = col._backend.mcat_deck_score(search="")
    assert empty.total_cards == 0
    assert empty.score == 0.0

    # A single brand-new card is unseen: it counts but stays unproven, so the
    # confidence range must be wide (lower clearly below upper).
    note = col.newNote()
    note["Front"] = "foo"
    col.addNote(note)

    report = col._backend.mcat_deck_score(search="")
    assert report.total_cards == 1
    assert report.scorable_cards == 1
    assert report.rated_cards == 0
    assert report.unseen_cards == 1
    assert report.mastered_cards == 0
    assert report.score_lower <= report.score <= report.score_upper
    assert report.score_lower < report.score_upper
    assert 0.0 < report.mastered_threshold <= 1.0


def test_mcat_queries_are_undo_safe():
    # Speedrun: the mastery/score RPCs are strictly read-only, so calling them
    # must not create or clear an undo entry, undo of a real action must still
    # work afterwards, and the collection must pass an integrity check.
    col = getEmptyCol()
    note = col.newNote()
    note["Front"] = "foo"
    col.addNote(note)
    c = col.sched.getCard()
    col.sched.answerCard(c, 3)  # a normal, undoable action

    undo_before = col.undo_status().undo
    assert undo_before  # there is an action available to undo

    # Call the Rust engine changes; these must not touch undo-tracked state.
    col._backend.mcat_mastery(search="")
    col._backend.mcat_deck_score(search="")

    # The queries neither created nor cleared an undo entry.
    assert col.undo_status().undo == undo_before
    # Undo of the prior review still succeeds (no exception).
    col.undo()

    # Collection passes an integrity check: no corruption introduced.
    _, ok = col.fix_integrity()
    assert ok
