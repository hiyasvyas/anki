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
        elif cmd == "mcat_set_exam":
            self._mcat_set_exam_date()
        elif cmd == "mcat_clear_exam":
            self._mcat_clear_exam_date()
        elif cmd == "mcat_gen_ai":
            import aqt.mcat_ai

            aqt.mcat_ai.generate_practice_deck(self.mw)
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
            self._render_page_theme()
            + self._v1_upgrade_message(data.sched_upgrade_required)
            + self._render_mcat_scores()
            + self._render_ai_panel()
            + self._render_mcat_panel()
            + self._render_pace_panel()
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

    def _render_page_theme(self) -> str:
        """Speedrun cosmetic layer: replace the plain gray deck-browser
        background with a soft pastel wash and turn the deck list into a frosted
        'glass' card. Colors are forced (not theme variables) so it reads the
        same in both light and dark Anki themes. Purely visual — no data."""
        return """
<style>
html,body{background:linear-gradient(135deg,#f2f0ff 0%,#fdeafb 34%,#e6fbf3 68%,#fff4e4 100%)
 fixed !important;min-height:100vh;}
center>table{background:rgba(255,255,255,.66);border:1px solid rgba(120,110,190,.20);
 border-radius:20px;padding:14px 20px !important;margin-top:6px;
 box-shadow:0 12px 30px rgba(80,70,140,.14),0 2px 6px rgba(80,70,140,.06);
 backdrop-filter:blur(6px);}
center>table th{color:rgba(49,46,77,.62) !important;
 border-bottom:1px solid rgba(120,110,190,.22) !important;}
center>table td{color:#312e4d;}
center>table a.deck,center>table .collapse{color:#312e4d !important;}
center>table tr.deck td{border-bottom:1px solid rgba(120,110,190,.14) !important;}
center>table .current td,
center>table tr:hover:not(.top-level-drag-row) td{
 background:rgba(109,94,252,.12) !important;}
#studiedToday{color:rgba(49,46,77,.7) !important;margin:1.6em 0 !important;}
</style>
"""

    def _render_ai_panel(self) -> str:
        """Home-page entry point for the in-app AI Transfer-Question generator
        (``aqt/mcat_ai.py``). Turns an existing deck into new, reworded,
        gate-checked practice questions. Fails safe to an empty string."""
        try:
            if self.mw.col is None or not self.mw.col.decks.all_names_and_ids(
                include_filtered=False
            ):
                return ""
            import aqt.mcat_ai

            if not aqt.mcat_ai.ai_enabled(self.mw.col):
                return ""
        except Exception:
            return ""

        css = """
<style>
@keyframes mcatUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}
.ai-card{--a1:#7c3aed;--a2:#c084fc;max-width:700px;margin:16px auto 8px;padding:18px 22px;
 border:1px solid #e6d8fb;border-radius:20px;text-align:start;color:#33235c;
 background:linear-gradient(150deg,#f5edff,#fdf0fb);
 box-shadow:0 12px 30px rgba(124,58,237,.18),0 2px 6px rgba(90,60,140,.06);
 position:relative;overflow:hidden;animation:mcatUp .5s cubic-bezier(.2,.7,.3,1) both;
 display:flex;justify-content:space-between;align-items:center;gap:16px;}
.ai-card::before{content:"";position:absolute;top:0;left:0;right:0;height:4px;
 background:linear-gradient(90deg,var(--a1),var(--a2));}
.ai-card::after{content:"";position:absolute;top:-60px;right:-60px;width:180px;height:180px;
 border-radius:50%;background:radial-gradient(closest-side,var(--a2),transparent);
 opacity:.26;pointer-events:none;}
.ai-title{font-weight:800;font-size:16px;display:flex;align-items:center;gap:8px;}
.ai-title::before{content:"";width:10px;height:10px;border-radius:50%;
 background:linear-gradient(135deg,var(--a1),var(--a2));box-shadow:0 0 10px var(--a2);}
.ai-sub{font-size:12px;color:rgba(51,35,92,.8);margin-top:4px;line-height:1.45;max-width:430px;}
.ai-btn{flex:none;border:0;cursor:pointer;font-size:13px;font-weight:800;color:#fff;
 padding:11px 20px;border-radius:12px;white-space:nowrap;
 background:linear-gradient(135deg,var(--a1),var(--a2));
 box-shadow:0 6px 18px rgba(124,58,237,.42);
 transition:transform .15s ease,box-shadow .15s ease;}
.ai-btn:hover{transform:translateY(-2px);box-shadow:0 10px 26px rgba(124,58,237,.55);}
</style>
"""
        return (
            css
            + """
<div class="ai-card">
  <div>
    <div class="ai-title">AI Practice Generator</div>
    <div class="ai-sub">Turn any deck into <b>new, reworded exam-style
     questions</b> — the memory&rarr;performance bridge. Each card is checked for
     source-grounding and blocked if it's a copy or a wrong fact, then added as a
     practice deck you can study here.</div>
  </div>
  <button class="ai-btn" onclick='pycmd("mcat_gen_ai")'>&#10022; Generate practice deck</button>
</div>
"""
        )

    # Speedrun: MCAT readiness panel (home page)
    ##########################################################################

    # Honesty / give-up thresholds for the home-page readiness display. The
    # mastery + range logic lives in the Rust engine (rslib/src/stats); this
    # only decides how to *present* it, and when to abstain.
    # A readiness score is shown only when BOTH hold: enough graded cards to
    # estimate a mastery rate, and enough of the exam's topics actually touched.
    # 230 reviews ties the evidence floor to one full-length MCAT (~230 scored
    # questions), matching the field benchmark that a real readiness signal only
    # emerges once a student has worked through at least a practice-test's worth
    # of material; it also tightens the 95% Wilson band to ±~0.065 at p=0.5 (vs
    # ±~0.14 at 50), so the first score we ever show is already reasonably
    # precise. The 50% topic gate stops a deck that only drilled one subject from
    # claiming readiness for the whole exam (see challenge 7c).
    _MCAT_MIN_REVIEWS = 230
    _MCAT_MIN_TOPIC_COVERAGE = 0.5

    def _render_mcat_scores(self) -> str:
        """The three honest scores side by side — Memory, Performance, and
        Readiness — each with a range, driven entirely by the Rust engine
        (``mcat_deck_score``, ``mcat_performance``, ``mcat_readiness``). This is
        the memory→performance→score bridge from section 4: they are shown as
        three *separate* numbers, never one blended figure. Readiness carries
        the engine's give-up rule and abstains when the evidence is thin. Fails
        safe to an empty string so it can never break the deck list."""
        try:
            memory = self.mw.col._backend.mcat_deck_score(search="")
            perf = self.mw.col._backend.mcat_performance(search="")
            ready = self.mw.col._backend.mcat_readiness(search="")
        except Exception:
            return ""

        if memory.scorable_cards == 0:
            return ""

        def pct(x: float) -> str:
            return f"{x * 100:.0f}%"

        def clamp01(x: float) -> float:
            return max(0.0, min(1.0, x))

        m_point, m_lower, m_upper = (
            clamp01(memory.score),
            clamp01(memory.score_lower),
            clamp01(memory.score_upper),
        )
        p_point, p_lower, p_upper = (
            clamp01(perf.performance),
            clamp01(perf.perf_lower),
            clamp01(perf.perf_upper),
        )
        if perf.transfer_measured:
            p_note = f"memory × measured transfer {perf.transfer_factor:.2f}"
        else:
            p_note = "transfer not yet measured — shown equal to memory"

        span = (ready.scale_max - ready.scale_min) or 1.0
        if ready.has_score:
            r_big = f"{ready.projected_score:.0f}"
            r_sub = (
                f"likely <b>{ready.score_lower:.0f}–{ready.score_upper:.0f}</b>"
                f" · {ready.confidence} confidence"
            )
            r_lo = clamp01((ready.score_lower - ready.scale_min) / span)
            r_hi = clamp01((ready.score_upper - ready.scale_min) / span)
            r_pt = clamp01((ready.projected_score - ready.scale_min) / span)
            r_bar = f"""
    <div class="mcat3-bar">
      <div class="mcat3-range" style="left:{r_lo * 100:.1f}%;width:{(r_hi - r_lo) * 100:.1f}%"></div>
      <div class="mcat3-point" style="left:{r_pt * 100:.1f}%"></div>
    </div>"""
        else:
            r_big = "—"
            missing = ready.reasons[0] if ready.reasons else "not enough data"
            r_sub = f"no score yet · {html.escape(missing)}"
            r_bar = ""

        def bar(lower: float, upper: float, point: float) -> str:
            return f"""
    <div class="mcat3-bar">
      <div class="mcat3-range" style="left:{lower * 100:.1f}%;width:{(upper - lower) * 100:.1f}%"></div>
      <div class="mcat3-point" style="left:{point * 100:.1f}%"></div>
    </div>"""

        css = """
<style>
@keyframes mcatUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}
.mcat3-wrap{max-width:700px;margin:20px auto 8px;display:flex;gap:14px;}
.mcat3-tile{flex:1;position:relative;padding:18px 18px 16px;border-radius:20px;
 border:1px solid var(--brd);color:#312e4d;
 background:linear-gradient(150deg,var(--bg1),var(--bg2));
 box-shadow:0 10px 26px var(--glow),0 2px 6px rgba(60,50,110,.06);
 overflow:hidden;text-align:start;
 animation:mcatUp .5s cubic-bezier(.2,.7,.3,1) both;
 transition:transform .18s ease,box-shadow .18s ease;}
.mcat3-tile:nth-child(2){animation-delay:.08s}
.mcat3-tile:nth-child(3){animation-delay:.16s}
.mcat3-tile:hover{transform:translateY(-4px);
 box-shadow:0 18px 40px var(--glow),0 4px 10px rgba(60,50,110,.08);}
.mcat3-tile::before{content:"";position:absolute;top:0;left:0;right:0;height:4px;
 background:linear-gradient(90deg,var(--a1),var(--a2));}
.mcat3-tile::after{content:"";position:absolute;top:-48px;right:-48px;width:140px;height:140px;
 border-radius:50%;background:radial-gradient(closest-side,var(--a2),transparent);
 opacity:.32;pointer-events:none;}
.mcat3-label{display:flex;align-items:center;gap:7px;font-size:11px;font-weight:800;
 text-transform:uppercase;letter-spacing:.07em;color:rgba(49,46,77,.66);}
.mcat3-label::before{content:"";width:9px;height:9px;border-radius:50%;
 background:linear-gradient(135deg,var(--a1),var(--a2));box-shadow:0 0 10px var(--a2);}
.mcat3-big{font-size:40px;font-weight:900;line-height:1.05;margin-top:7px;letter-spacing:-.02em;
 color:var(--a1);background:linear-gradient(135deg,var(--a1),var(--a2));
 -webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;}
.mcat3-sub{font-size:11px;color:rgba(49,46,77,.78);margin-top:3px;line-height:1.4;}
.mcat3-sub b{color:var(--a1);}
.mcat3-bar{position:relative;height:9px;border-radius:999px;margin:12px 0 2px;
 background:rgba(49,46,77,.12);}
.mcat3-range{position:absolute;top:0;bottom:0;border-radius:999px;
 background:linear-gradient(90deg,var(--a1),var(--a2));box-shadow:0 0 12px var(--a2);}
.mcat3-point{position:absolute;top:-4px;width:4px;height:17px;border-radius:3px;
 background:#fff;box-shadow:0 0 0 2px var(--a2),0 0 10px var(--a2);}
.mcat3-tag{font-size:10px;color:rgba(49,46,77,.5);margin-top:9px;}
.m-mem{--a1:#6d5efc;--a2:#9d8bff;--bg1:#eef0ff;--bg2:#f7f0ff;--brd:#ddd8ff;--glow:rgba(109,94,252,.22);}
.m-perf{--a1:#c026d3;--a2:#f472e6;--bg1:#fdeafe;--bg2:#fdf0f8;--brd:#f4d3f6;--glow:rgba(192,38,211,.20);}
.m-ready{--a1:#0d9488;--a2:#34d399;--bg1:#e5fbf3;--bg2:#effcf1;--brd:#c4f1e2;--glow:rgba(13,148,136,.20);}
</style>
"""
        return (
            css
            + f"""
<div class="mcat3-wrap">
  <div class="mcat3-tile m-mem">
    <div class="mcat3-label">Memory</div>
    <div class="mcat3-big">{pct(m_point)}</div>
    <div class="mcat3-sub">recall now · range <b>{pct(m_lower)}–{pct(m_upper)}</b></div>
    {bar(m_lower, m_upper, m_point)}
    <div class="mcat3-tag">Rust · mcat_deck_score</div>
  </div>
  <div class="mcat3-tile m-perf">
    <div class="mcat3-label">Performance</div>
    <div class="mcat3-big">{pct(p_point)}</div>
    <div class="mcat3-sub">new questions · range <b>{pct(p_lower)}–{pct(p_upper)}</b></div>
    {bar(p_lower, p_upper, p_point)}
    <div class="mcat3-tag">Rust · mcat_performance · {html.escape(p_note)}</div>
  </div>
  <div class="mcat3-tile m-ready">
    <div class="mcat3-label">Readiness</div>
    <div class="mcat3-big">{r_big}</div>
    <div class="mcat3-sub">{r_sub}</div>{r_bar}
    <div class="mcat3-tag">Rust · mcat_readiness · MCAT {ready.scale_min:.0f}–{ready.scale_max:.0f}</div>
  </div>
</div>
"""
        )

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
@keyframes mcatUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}
.mcat-card{--a1:#0d9488;--a2:#34d399;max-width:700px;margin:16px auto 8px;padding:20px 22px;
 border:1px solid #c4f1e2;border-radius:20px;text-align:start;color:#26413a;
 background:linear-gradient(150deg,#e6fbf4,#f0fcf3);
 box-shadow:0 12px 30px rgba(13,148,136,.18),0 2px 6px rgba(40,90,80,.06);
 position:relative;overflow:hidden;animation:mcatUp .5s cubic-bezier(.2,.7,.3,1) both;}
.mcat-card::before{content:"";position:absolute;top:0;left:0;right:0;height:4px;
 background:linear-gradient(90deg,var(--a1),var(--a2));}
.mcat-card::after{content:"";position:absolute;top:-60px;right:-60px;width:180px;height:180px;
 border-radius:50%;background:radial-gradient(closest-side,var(--a2),transparent);
 opacity:.22;pointer-events:none;}
.mcat-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;}
.mcat-title{font-weight:800;font-size:16px;display:flex;align-items:center;gap:8px;}
.mcat-title::before{content:"";width:10px;height:10px;border-radius:50%;
 background:linear-gradient(135deg,var(--a1),var(--a2));box-shadow:0 0 10px var(--a2);}
.mcat-tag{font-size:11px;color:rgba(38,65,58,.55);}
.mcat-score{font-size:46px;font-weight:900;line-height:1.02;letter-spacing:-.02em;
 color:var(--a1);background:linear-gradient(135deg,var(--a1),var(--a2));
 -webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;}
.mcat-sub{font-size:12px;color:rgba(38,65,58,.82);margin-top:3px;}
.mcat-sub b{color:var(--a1);}
.mcat-bar{position:relative;height:11px;border-radius:999px;margin:14px 0 6px;
 background:rgba(38,65,58,.12);}
.mcat-range{position:absolute;top:0;bottom:0;border-radius:999px;
 background:linear-gradient(90deg,var(--a1),var(--a2));box-shadow:0 0 12px var(--a2);}
.mcat-point{position:absolute;top:-4px;width:4px;height:19px;border-radius:3px;
 background:#fff;box-shadow:0 0 0 2px var(--a2),0 0 10px var(--a2);}
.mcat-grid{display:flex;gap:10px;flex-wrap:wrap;font-size:12px;margin-top:14px;}
.mcat-grid>div{flex:1;min-width:82px;padding:10px 12px;border-radius:13px;
 background:rgba(255,255,255,.6);border:1px solid rgba(13,148,136,.14);color:rgba(38,65,58,.7);}
.mcat-grid b{font-size:17px;display:block;margin-top:3px;font-weight:800;color:#26413a;}
.mcat-conf{color:var(--a1)!important;}
.mcat-note{font-size:11px;color:rgba(38,65,58,.72);margin-top:12px;line-height:1.5;}
.mcat-note b{color:#26413a;}
.mcat-abstain{font-size:19px;font-weight:900;margin:6px 0;color:#b45309;}
.mcat-subtitle{font-weight:800;font-size:14px;margin:2px 0 10px;display:flex;
 justify-content:space-between;align-items:center;}
.mcat-ttable{width:100%;border-collapse:collapse;font-size:12px;}
.mcat-ttable th{text-align:start;color:rgba(38,65,58,.55);font-weight:700;padding:5px 6px;}
.mcat-ttable td{padding:6px 6px;border-top:1px solid rgba(13,148,136,.14);}
.mcat-ttable tr:hover td{background:rgba(52,211,153,.1);}
.mcat-tname{font-weight:600;}
.mcat-tbarcell{width:120px;}
.mcat-tbar{height:9px;border-radius:999px;background:rgba(38,65,58,.12);overflow:hidden;}
.mcat-tbar>div{height:100%;border-radius:999px;
 background:linear-gradient(90deg,#0d9488,#34d399);}
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
            return (
                css
                + f"""
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
"""
                + topics_html
            )

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

        return (
            css
            + f"""
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
"""
            + topics_html
        )

    # Speedrun: Pace Trainer panel (home page)
    ##########################################################################

    # Ladder targets in ms, mirroring PACE_RUNGS_MS in rslib/src/stats/pace.rs.
    # Index 0 == unlimited (no timer); the last entry is the 90s goal.
    _PACE_LADDER_MS = (0, 300_000, 180_000, 120_000, 90_000)

    def _mcat_set_exam_date(self) -> None:
        """Prompt for the MCAT date and store it (epoch seconds) in the config
        key the Rust pace model reads. Only sets the ladder's *starting* rung.
        Pre-fills the current date (if any) so it doubles as an edit."""
        import datetime

        current = self.mw.col.get_config("examDate", None)
        default = ""
        if current:
            try:
                default = datetime.datetime.fromtimestamp(current).strftime("%Y-%m-%d")
            except (ValueError, OverflowError, OSError):
                default = ""

        text = (
            getOnlyText(
                "Enter your MCAT exam date (YYYY-MM-DD):",
                parent=self.mw,
                default=default,
            )
            or ""
        ).strip()
        if not text:
            return
        try:
            day = datetime.datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            showInfo(
                "Please use the format YYYY-MM-DD, e.g. 2026-01-15.", parent=self.mw
            )
            return
        # Anchor at 09:00 local so the day-count is stable regardless of tz.
        epoch = int(day.replace(hour=9, minute=0, second=0).timestamp())
        self.mw.col.set_config("examDate", epoch)
        self.refresh()

    def _mcat_clear_exam_date(self) -> None:
        self.mw.col.remove_config("examDate")
        self.refresh()

    def _render_pace_panel(self) -> str:
        """Home-page Pace Trainer card driven by the Rust ``mcat_pace`` RPC. Shows
        the exam-date prompt when unset, then the pace ladder and per-topic
        target / accuracy / mean-time, sorted weakest-first (the same signal the
        PaceWeakness review order uses). Fails safe to an empty string so it can
        never break the deck list."""
        try:
            pace = self.mw.col._backend.mcat_pace(search="")
        except Exception:
            return ""
        if not pace.topics:
            return ""

        def secs(ms: float) -> str:
            return f"{ms / 1000:.0f}s"

        def target_label(ms: int) -> str:
            return "unlimited" if ms == 0 else secs(ms)

        goal = target_label(pace.goal_ms)
        min_acc_pct = f"{pace.min_accuracy * 100:.0f}%"

        css = """
<style>
@keyframes mcatUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}
.pace-card{--a1:#ea7a1b;--a2:#fbbf24;max-width:700px;margin:16px auto 8px;padding:20px 22px;
 border:1px solid #fbe2bd;border-radius:20px;text-align:start;color:#4a3410;
 background:linear-gradient(150deg,#fff3e0,#fff8ec);
 box-shadow:0 12px 30px rgba(234,122,27,.18),0 2px 6px rgba(120,80,20,.06);
 position:relative;overflow:hidden;animation:mcatUp .5s cubic-bezier(.2,.7,.3,1) both;}
.pace-card::before{content:"";position:absolute;top:0;left:0;right:0;height:4px;
 background:linear-gradient(90deg,var(--a1),var(--a2));}
.pace-card::after{content:"";position:absolute;top:-60px;right:-60px;width:180px;height:180px;
 border-radius:50%;background:radial-gradient(closest-side,var(--a2),transparent);
 opacity:.28;pointer-events:none;}
.pace-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;}
.pace-title{font-weight:800;font-size:16px;display:flex;align-items:center;gap:8px;}
.pace-title::before{content:"";width:10px;height:10px;border-radius:50%;
 background:linear-gradient(135deg,var(--a1),var(--a2));box-shadow:0 0 10px var(--a2);}
.pace-tag{font-size:11px;color:rgba(74,52,16,.55);}
.pace-sub{font-size:12px;color:rgba(74,52,16,.82);margin-top:2px;}
.pace-sub b{color:var(--a1);}
.pace-btn{display:inline-block;margin-top:10px;padding:9px 18px;border-radius:12px;
 border:0;cursor:pointer;font-size:12px;font-weight:800;color:#4a3410;
 background:linear-gradient(135deg,var(--a1),var(--a2));
 box-shadow:0 4px 14px rgba(234,122,27,.42);
 transition:transform .15s ease,box-shadow .15s ease;}
.pace-btn:hover{transform:translateY(-2px);box-shadow:0 8px 22px rgba(234,122,27,.55);}
.pace-ttable{width:100%;border-collapse:collapse;font-size:12px;margin-top:12px;}
.pace-ttable th{text-align:start;color:rgba(74,52,16,.55);font-weight:700;padding:5px 6px;}
.pace-ttable td{padding:6px 6px;border-top:1px solid rgba(234,122,27,.16);}
.pace-ttable tr:hover td{background:rgba(251,191,36,.14);}
.pace-tname{font-weight:600;}
.pace-note{font-size:11px;color:rgba(74,52,16,.72);margin-top:12px;line-height:1.5;}
.pace-note b{color:#4a3410;}
.pace-ready{color:#0d9488;font-weight:800;}
</style>
"""

        if pace.exam_months_remaining < 0:
            exam_html = """
  <div class="pace-sub">No exam date set — the ladder starts at
   <b>unlimited</b> until you add one.</div>
  <div class="pace-btn" onclick='pycmd("mcat_set_exam")'>Set MCAT exam date</div>"""
        else:
            start_ms = self._PACE_LADDER_MS[
                min(pace.start_rung, len(self._PACE_LADDER_MS) - 1)
            ]
            exam_html = f"""
  <div class="pace-sub">Exam in <b>{pace.exam_months_remaining:.1f} months</b>
   · starting target <b>{target_label(start_ms)}</b> · goal <b>{goal}</b>
   <span class="pace-tag" style="cursor:pointer"
    onclick='pycmd("mcat_set_exam")'>(change)</span>
   <span class="pace-tag" style="cursor:pointer"
    onclick='pycmd("mcat_clear_exam")'>(clear)</span></div>"""

        rows = ""
        for t in sorted(pace.topics, key=lambda t: (-t.weakness, t.topic)):
            acc = f"{t.accuracy * 100:.0f}%" if t.window_reviews else "—"
            mean = secs(t.mean_answer_ms) if t.window_reviews else "—"
            status = html.escape(t.phase)
            if t.ready_for_next_rung:
                status += ' <span class="pace-ready">▲ almost</span>'
            rows += f"""
    <tr><td class="pace-tname">{html.escape(t.topic)}</td>
    <td>{t.window_reviews}</td><td>{acc}</td><td>{mean}</td>
    <td>{target_label(t.target_ms)}</td><td>{status}</td></tr>"""

        return (
            css
            + f"""
<div class="pace-card">
  <div class="pace-head">
    <span class="pace-title">Pace Trainer</span>
    <span class="pace-tag">Rust engine · mcat_pace</span>
  </div>{exam_html}
  <table class="pace-ttable">
    <tr><th>Topic</th><th>Reviews ({pace.window_days}d)</th><th>Accuracy</th>
     <th>Mean time</th><th>Target</th><th>Phase</th></tr>
    {rows}
  </table>
  <div class="pace-note">Topics are listed weakest/slowest first — the same
   order the <b>Pace-weakness</b> review order studies them in. A topic only
   drops to a shorter target after ≥ {pace.min_window_reviews} recent reviews
   with ≥ {min_acc_pct} accuracy <b>and</b> a mean time already inside the next
   rung. Measured from answer time Anki already records; FSRS intervals are
   untouched.</div>
</div>
"""
        )

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
