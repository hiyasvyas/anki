# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from __future__ import annotations

import html
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import aqt
import aqt.operations
from anki.collection import Collection, OpChanges
from anki.decks import DeckCollapseScope, DeckId, DeckTreeNode
from aqt import AnkiQt, gui_hooks
from aqt.deckoptions import display_options_for_deck_id
from aqt.operations import QueryOp
from aqt.operations.deck import (
    add_deck_dialog,
    remove_decks,
    rename_deck,
    reparent_decks,
    set_current_deck,
    set_deck_collapsed,
)
from aqt.qt import *
from aqt.sound import av_player
from aqt.toolbar import BottomBar
from aqt.utils import getOnlyText, openLink, shortcut, showInfo, tr


class DeckBrowserBottomBar:
    def __init__(self, deck_browser: DeckBrowser) -> None:
        self.deck_browser = deck_browser


@dataclass
class RenderData:
    """Data from collection that is required to show the page."""

    tree: DeckTreeNode
    current_deck_id: DeckId
    studied_today: str
    sched_upgrade_required: bool


@dataclass
class DeckBrowserContent:
    """Stores sections of HTML content that the deck browser will be
    populated with.

    Attributes:
        tree {str} -- HTML of the deck tree section
        stats {str} -- HTML of the stats section
    """

    tree: str
    stats: str


@dataclass
class RenderDeckNodeContext:
    current_deck_id: DeckId


class DeckBrowser:
    _render_data: RenderData

    def __init__(self, mw: AnkiQt) -> None:
        self.mw = mw
        self.web = mw.web
        self.bottom = BottomBar(mw, mw.bottomWeb)
        self.scrollPos = QPoint(0, 0)
        self._refresh_needed = False

    def show(self) -> None:
        av_player.stop_and_clear_queue()
        self.web.set_bridge_command(self._linkHandler, self)
        # redraw top bar for theme change
        self.mw.toolbar.redraw()
        self.refresh()

    def refresh(self) -> None:
        self._renderPage()
        self._refresh_needed = False

    def refresh_if_needed(self) -> None:
        if self._refresh_needed:
            self.refresh()

    def op_executed(
        self, changes: OpChanges, handler: object | None, focused: bool
    ) -> bool:
        if changes.study_queues and handler is not self:
            self._refresh_needed = True

        if focused:
            self.refresh_if_needed()

        return self._refresh_needed

    # Event handlers
    ##########################################################################

    def _linkHandler(self, url: str) -> Any:
        if ":" in url:
            (cmd, arg) = url.split(":", 1)
        else:
            cmd = url
            arg = ""
        if cmd == "open":
            self.set_current_deck(DeckId(int(arg)))
        elif cmd == "opts":
            self._showOptions(arg)
        elif cmd == "shared":
            self._onShared()
        elif cmd == "import":
            self.mw.onImport()
        elif cmd == "create":
            self._on_create()
        elif cmd == "drag":
            source, target = arg.split(",")
            self._handle_drag_and_drop(DeckId(int(source)), DeckId(int(target or 0)))
        elif cmd == "collapse":
            self._collapse(DeckId(int(arg)))
        elif cmd == "v2upgrade":
            self._confirm_upgrade()
        elif cmd == "v2upgradeinfo":
            if self.mw.col.sched_ver() == 1:
                openLink("https://faqs.ankiweb.net/the-anki-2.1-scheduler.html")
            else:
                openLink("https://faqs.ankiweb.net/the-2021-scheduler.html")
        elif cmd == "select":
            set_current_deck(
                parent=self.mw, deck_id=DeckId(int(arg))
            ).run_in_background()
        return False

    def set_current_deck(self, deck_id: DeckId) -> None:
        set_current_deck(parent=self.mw, deck_id=deck_id).success(
            lambda _: self.mw.onOverview()
        ).run_in_background(initiator=self)

    # HTML generation
    ##########################################################################

    _body = """
<center>
<table cellspacing=0 cellpadding=3>
%(tree)s
</table>

<br>
%(stats)s
</center>
"""

    def _renderPage(self, reuse: bool = False) -> None:
        if not reuse:

            def get_data(col: Collection) -> RenderData:
                return RenderData(
                    tree=col.sched.deck_due_tree(),
                    current_deck_id=col.decks.get_current_id(),
                    studied_today=col.studied_today(),
                    sched_upgrade_required=not col.v3_scheduler(),
                )

            def success(output: RenderData) -> None:
                self._render_data = output
                self.__renderPage(None)

            QueryOp(
                parent=self.mw,
                op=get_data,
                success=success,
            ).run_in_background()
        else:
            self.web.evalWithCallback("window.pageYOffset", self.__renderPage)

    def __renderPage(self, offset: int | None) -> None:
        data = self._render_data
        content = DeckBrowserContent(
            tree=self._renderDeckTree(data.tree),
            stats=self._renderStats(),
        )
        gui_hooks.deck_browser_will_render_content(self, content)
        self.web.stdHtml(
            self._v1_upgrade_message(data.sched_upgrade_required)
            + self._render_mcat_panel()
            + self._body % content.__dict__,
            css=["css/deckbrowser.css"],
            js=[
                "js/vendor/jquery.min.js",
                "js/vendor/jquery-ui.min.js",
                "js/deckbrowser.js",
            ],
            context=self,
        )
        self._drawButtons()
        if offset is not None:
            self._scrollToOffset(offset)
        gui_hooks.deck_browser_did_render(self)

    def _scrollToOffset(self, offset: int) -> None:
        self.web.eval("window.scrollTo(0, %d, 'instant');" % offset)

    def _renderStats(self) -> str:
        return '<div id="studiedToday"><span>{}</span></div>'.format(
            self._render_data.studied_today
        )

    # Speedrun: MCAT readiness panel (home page)
    ##########################################################################

    # Honesty / give-up thresholds for the home-page readiness display. The
    # mastery + range logic lives in the Rust engine (rslib/src/stats); this
    # only decides how to *present* it, and when to abstain.
    # A readiness score is shown only when BOTH hold: enough graded cards to
    # estimate a mastery rate, and enough of the exam's topics actually touched.
    # 50 reviews keeps the 95% Wilson band meaningful (±~0.14 at p=0.5); the 50%
    # topic gate stops a deck that only drilled one subject from claiming
    # readiness for the whole exam (see challenge 7c).
    _MCAT_MIN_REVIEWS = 50
    _MCAT_MIN_TOPIC_COVERAGE = 0.5

    def _render_mcat_panel(self) -> str:
        """Home-page readiness card driven entirely by the Rust engine calls
        ``mcat_deck_score`` and ``mcat_mastery``. Fails safe to an empty string
        so it can never break the deck list."""
        try:
            score = self.mw.col._backend.mcat_deck_score(search="")
            mastery = self.mw.col._backend.mcat_mastery(search="")
        except Exception:
            return ""

        if score.total_cards == 0:
            return ""

        def pct(x: float) -> str:
            return f"{x * 100:.0f}%"

        rated = score.rated_cards
        scorable = score.scorable_cards
        coverage = (rated / scorable) if scorable else 0.0
        # Topic coverage: fraction of topics (decks) with at least one review.
        topics_with_cards = [t for t in mastery.topics if t.total_cards > 0]
        topics_reviewed = [t for t in topics_with_cards if t.rated_cards > 0]
        topic_total = len(topics_with_cards)
        topic_coverage = (len(topics_reviewed) / topic_total) if topic_total else 0.0
        threshold_pct = round(score.mastered_threshold * 100)

        css = """
<style>
.mcat-card{max-width:640px;margin:14px auto 4px;padding:16px 18px;border:1px solid
 var(--border,rgba(128,128,128,.35));border-radius:12px;text-align:start;
 background:var(--canvas-elevated,rgba(128,128,128,.06));}
.mcat-head{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px;}
.mcat-title{font-weight:700;font-size:15px;}
.mcat-tag{font-size:11px;opacity:.6;}
.mcat-score{font-size:34px;font-weight:800;line-height:1.1;}
.mcat-sub{font-size:12px;opacity:.8;margin-top:2px;}
.mcat-bar{position:relative;height:12px;border-radius:6px;margin:12px 0 6px;
 background:rgba(128,128,128,.25);overflow:hidden;}
.mcat-range{position:absolute;top:0;bottom:0;background:rgba(70,130,220,.55);}
.mcat-point{position:absolute;top:-3px;width:3px;height:18px;background:currentColor;}
.mcat-grid{display:flex;gap:18px;flex-wrap:wrap;font-size:12px;margin-top:8px;}
.mcat-grid b{font-size:15px;display:block;}
.mcat-note{font-size:11px;opacity:.7;margin-top:10px;line-height:1.4;}
.mcat-conf{font-weight:700;}
.mcat-abstain{font-size:15px;font-weight:700;margin:4px 0;}
.mcat-subtitle{font-weight:700;font-size:13px;margin:2px 0 8px;display:flex;
 justify-content:space-between;align-items:baseline;}
.mcat-ttable{width:100%;border-collapse:collapse;font-size:12px;}
.mcat-ttable th{text-align:start;opacity:.6;font-weight:600;padding:2px 6px;}
.mcat-ttable td{padding:3px 6px;border-top:1px solid rgba(128,128,128,.18);}
.mcat-tname{font-weight:600;}
.mcat-tbarcell{width:120px;}
.mcat-tbar{height:8px;border-radius:4px;background:rgba(128,128,128,.25);overflow:hidden;}
.mcat-tbar>div{height:100%;background:rgba(70,160,90,.75);}
</style>
"""

        # 7a Rust change on the dashboard: per-topic mastery from mcat_mastery.
        # Weakest topics (lowest mastered fraction) surface first.
        topic_rows = ""
        for t in sorted(
            mastery.topics,
            key=lambda t: (
                (t.mastered_cards / t.total_cards) if t.total_cards else 0.0,
                t.topic,
            ),
        ):
            frac = (t.mastered_cards / t.total_cards) if t.total_cards else 0.0
            recall = pct(t.average_recall) if t.rated_cards else "—"
            topic_rows += f"""
    <tr><td class="mcat-tname">{html.escape(t.topic)}</td>
    <td>{t.mastered_cards}/{t.total_cards}</td><td>{t.rated_cards}</td>
    <td>{recall}</td>
    <td class="mcat-tbarcell"><div class="mcat-tbar">
      <div style="width:{frac * 100:.0f}%"></div></div></td></tr>"""

        topics_html = f"""
<div class="mcat-card">
  <div class="mcat-subtitle"><span>Per-topic mastery</span>
   <span class="mcat-tag">Rust engine · mcat_mastery</span></div>
  <table class="mcat-ttable">
    <tr><th>Topic</th><th>Mastered</th><th>Reviewed</th><th>Avg recall</th>
     <th>Mastery</th></tr>
    {topic_rows}
  </table>
  <div class="mcat-note">Mastered = current FSRS recall ≥ {threshold_pct}%.
   Computed in a single Rust pass over {score.total_cards} cards.</div>
</div>
"""

        # Honesty rule: refuse a score until there is enough evidence on BOTH
        # axes — enough graded reviews, and enough of the topics touched.
        enough_reviews = rated >= self._MCAT_MIN_REVIEWS
        enough_topics = topic_coverage >= self._MCAT_MIN_TOPIC_COVERAGE
        if not (enough_reviews and enough_topics):
            reasons = []
            if not enough_reviews:
                reasons.append(
                    f"only <b>{rated}</b> of {self._MCAT_MIN_REVIEWS} needed reviews"
                )
            if not enough_topics:
                reasons.append(
                    f"only <b>{pct(topic_coverage)}</b> topic coverage "
                    f"({len(topics_reviewed)}/{topic_total} topics), "
                    f"need {pct(self._MCAT_MIN_TOPIC_COVERAGE)}"
                )
            return css + f"""
<div class="mcat-card">
  <div class="mcat-head">
    <span class="mcat-title">MCAT Readiness</span>
    <span class="mcat-tag">Rust engine · mcat_deck_score</span>
  </div>
  <div class="mcat-abstain">No score yet — not enough data.</div>
  <div class="mcat-sub">Give-up rule: a score is shown only after at least
   {self._MCAT_MIN_REVIEWS} graded reviews <b>and</b>
   {pct(self._MCAT_MIN_TOPIC_COVERAGE)} topic coverage. Missing:
   {"; ".join(reasons)}. Updates automatically as you review.</div>
  <div class="mcat-note">Mastered = current FSRS recall ≥ {threshold_pct}% ·
   {score.total_cards} cards in deck.</div>
</div>
""" + topics_html

        if topic_coverage < 0.60:
            conf = "Low"
            conf_why = (
                f"you have reviewed only {pct(topic_coverage)} of the "
                f"{topic_total} topics"
            )
        elif topic_coverage < 0.85:
            conf = "Medium"
            conf_why = f"{pct(topic_coverage)} of topics reviewed, some still untouched"
        else:
            conf = "High"
            conf_why = f"{pct(topic_coverage)} of topics reviewed"

        # Best next topic to study: lowest average recall among reviewed topics.
        rated_topics = [t for t in mastery.topics if t.rated_cards > 0]
        if rated_topics:
            weakest = min(rated_topics, key=lambda t: t.average_recall)
            best_next = f"{weakest.topic} ({pct(weakest.average_recall)} recall)"
        else:
            best_next = "review any topic to begin"

        lower = max(0.0, min(1.0, score.score_lower))
        upper = max(0.0, min(1.0, score.score_upper))
        point = max(0.0, min(1.0, score.score))

        return css + f"""
<div class="mcat-card">
  <div class="mcat-head">
    <span class="mcat-title">MCAT Readiness</span>
    <span class="mcat-tag">Rust engine · mcat_deck_score</span>
  </div>
  <div class="mcat-score">{pct(point)}</div>
  <div class="mcat-sub">mastery now · likely range
   <b>{pct(lower)} – {pct(upper)}</b></div>
  <div class="mcat-bar">
    <div class="mcat-range" style="left:{lower * 100:.1f}%;width:{(upper - lower) * 100:.1f}%"></div>
    <div class="mcat-point" style="left:{point * 100:.1f}%"></div>
  </div>
  <div class="mcat-grid">
    <div>Confidence<b class="mcat-conf">{conf}</b></div>
    <div>Topics<b>{len(topics_reviewed)} / {topic_total}</b></div>
    <div>Coverage<b>{pct(coverage)}</b></div>
    <div>Reviewed<b>{rated} / {scorable}</b></div>
    <div>Mastered<b>{score.mastered_cards}</b></div>
  </div>
  <div class="mcat-note">
   <b>Why a range?</b> {score.unseen_cards} cards are still unreviewed, so the true
   score is uncertain ({conf_why}). The band is a 95% interval that narrows as you
   review more.<br>
   <b>Best next topic:</b> {best_next}.<br>
   Mastered = current FSRS recall ≥ {threshold_pct}% over {score.total_cards} cards.
  </div>
</div>
""" + topics_html

    def _renderDeckTree(self, top: DeckTreeNode) -> str:
        buf = """
<tr><th colspan=5 align=start>{}</th>
<th class=count>{}</th>
<th class=count>{}</th>
<th class=count>{}</th>
<th class=optscol></th></tr>""".format(
            tr.decks_deck(),
            tr.actions_new(),
            tr.decks_learn_header(),
            tr.decks_review_header(),
        )
        buf += self._topLevelDragRow()

        ctx = RenderDeckNodeContext(current_deck_id=self._render_data.current_deck_id)

        for child in top.children:
            buf += self._render_deck_node(child, ctx)

        return buf

    def _render_deck_node(self, node: DeckTreeNode, ctx: RenderDeckNodeContext) -> str:
        if node.collapsed:
            prefix = "+"
        else:
            prefix = "−"

        def indent() -> str:
            return "&nbsp;" * 6 * (node.level - 1)

        if node.deck_id == ctx.current_deck_id:
            klass = "deck current"
        else:
            klass = "deck"

        buf = (
            "<tr class='%s' id='%d' onclick='if(event.shiftKey) return pycmd(\"select:%d\")'>"
            % (
                klass,
                node.deck_id,
                node.deck_id,
            )
        )
        # deck link
        if node.children:
            collapse = (
                "<a class=collapse href=# onclick='return pycmd(\"collapse:%d\")'>%s</a>"
                % (node.deck_id, prefix)
            )
        else:
            collapse = "<span class=collapse></span>"
        if node.filtered:
            extraclass = "filtered"
        else:
            extraclass = ""
        buf += """

        <td class=decktd colspan=5>%s%s<a class="deck %s"
        href=# onclick="return pycmd('open:%d')">%s</a></td>""" % (
            indent(),
            collapse,
            extraclass,
            node.deck_id,
            html.escape(node.name),
        )

        # due counts
        def nonzeroColour(cnt: int, klass: str) -> str:
            if not cnt:
                klass = "zero-count"
            return f'<span class="{klass}">{cnt}</span>'

        review = nonzeroColour(node.review_count, "review-count")
        learn = nonzeroColour(node.learn_count, "learn-count")

        buf += ("<td align=end>%s</td>" * 3) % (
            nonzeroColour(node.new_count, "new-count"),
            learn,
            review,
        )
        # options
        buf += (
            "<td align=center class=opts><a onclick='return pycmd(\"opts:%d\");'>"
            "<img src='/_anki/imgs/gears.svg' class=gears></a></td></tr>" % node.deck_id
        )
        # children
        if not node.collapsed:
            for child in node.children:
                buf += self._render_deck_node(child, ctx)
        return buf

    def _topLevelDragRow(self) -> str:
        return "<tr class='top-level-drag-row'><td colspan='6'>&nbsp;</td></tr>"

    # Options
    ##########################################################################

    def _showOptions(self, did: str) -> None:
        m = QMenu(self.mw)
        a = m.addAction(tr.actions_rename())
        assert a is not None
        qconnect(a.triggered, lambda b, did=did: self._rename(DeckId(int(did))))
        a = m.addAction(tr.actions_options())
        assert a is not None
        qconnect(a.triggered, lambda b, did=did: self._options(DeckId(int(did))))
        a = m.addAction(tr.actions_export())
        assert a is not None
        qconnect(a.triggered, lambda b, did=did: self._export(DeckId(int(did))))
        a = m.addAction(tr.actions_delete())
        assert a is not None
        qconnect(a.triggered, lambda b, did=did: self._delete(DeckId(int(did))))
        gui_hooks.deck_browser_will_show_options_menu(m, int(did))
        m.popup(QCursor.pos())

    def _export(self, did: DeckId) -> None:
        self.mw.onExport(did=did)

    def _rename(self, did: DeckId) -> None:
        def prompt(name: str) -> None:
            new_name = getOnlyText(
                tr.decks_new_deck_name(), default=name, title=tr.actions_rename()
            )
            if not new_name or new_name == name:
                return
            else:
                rename_deck(
                    parent=self.mw, deck_id=did, new_name=new_name
                ).run_in_background()

        QueryOp(
            parent=self.mw, op=lambda col: col.decks.name(did), success=prompt
        ).run_in_background()

    def _options(self, did: DeckId) -> None:
        display_options_for_deck_id(did)

    def _collapse(self, did: DeckId) -> None:
        node = self.mw.col.decks.find_deck_in_tree(self._render_data.tree, did)
        if node:
            node.collapsed = not node.collapsed
            set_deck_collapsed(
                parent=self.mw,
                deck_id=did,
                collapsed=node.collapsed,
                scope=DeckCollapseScope.REVIEWER,
            ).run_in_background()
            self._renderPage(reuse=True)

    def _handle_drag_and_drop(self, source: DeckId, target: DeckId) -> None:
        reparent_decks(
            parent=self.mw, deck_ids=[source], new_parent=target
        ).run_in_background()

    def _delete(self, did: DeckId) -> None:
        deck = self.mw.col.decks.find_deck_in_tree(self._render_data.tree, did)
        assert deck is not None
        deck_name = deck.name
        remove_decks(
            parent=self.mw, deck_ids=[did], deck_name=deck_name
        ).run_in_background()

    # Top buttons
    ######################################################################

    drawLinks = [
        ["", "shared", tr.decks_get_shared()],
        ["", "create", tr.decks_create_deck()],
        ["Ctrl+Shift+I", "import", tr.decks_import_file()],
    ]

    def _drawButtons(self) -> None:
        buf = ""
        drawLinks = deepcopy(self.drawLinks)
        for b in drawLinks:
            if b[0]:
                b[0] = tr.actions_shortcut_key(val=shortcut(b[0]))
            buf += """
<button title='%s' onclick='pycmd(\"%s\");'>%s</button>""" % tuple(b)
        self.bottom.draw(
            buf=buf,
            link_handler=self._linkHandler,
            web_context=DeckBrowserBottomBar(self),
        )

    def _onShared(self) -> None:
        openLink(f"{aqt.appShared}decks/")

    def _on_create(self) -> None:
        if op := add_deck_dialog(
            parent=self.mw, default_text=self.mw.col.decks.current()["name"]
        ):
            op.run_in_background()

    ######################################################################

    def _v1_upgrade_message(self, required: bool) -> str:
        if not required:
            return ""

        update_required = tr.scheduling_update_required().replace("V2", "v3")

        return f"""
<center>
<div class=callout>
    <div>
      {update_required}
    </div>
    <div>
      <button onclick='pycmd("v2upgrade")'>
        {tr.scheduling_update_button()}
      </button>
      <button onclick='pycmd("v2upgradeinfo")'>
        {tr.scheduling_update_more_info_button()}
      </button>
    </div>
</div>
</center>
"""

    def _confirm_upgrade(self) -> None:
        if self.mw.col.sched_ver() == 1:
            self.mw.col.mod_schema(check=True)
            self.mw.col.upgrade_to_v2_scheduler()
        self.mw.col.set_v3_scheduler(True)

        showInfo(tr.scheduling_update_done())
        self.refresh()
