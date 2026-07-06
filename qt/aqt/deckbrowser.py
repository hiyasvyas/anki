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
    # Whole MCAT dashboard (mastery + deck score + performance + readiness +
    # pace) from one shared engine scan, computed on the background thread so it
    # never blocks the UI. None if the engine call failed (panels fail safe).
    mcat_dash: object = None


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
        elif cmd == "mcat_set_exam_date":
            self._mcat_set_exam_date_value(arg)
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
                # Compute the MCAT dashboard here, on the background thread, so
                # its one-scan engine pass never freezes the UI on first paint.
                try:
                    mcat_dash = col._backend.mcat_dashboard(search="")
                except Exception:
                    mcat_dash = None
                return RenderData(
                    tree=col.sched.deck_due_tree(),
                    current_deck_id=col.decks.get_current_id(),
                    studied_today=col.studied_today(),
                    sched_upgrade_required=not col.v3_scheduler(),
                    mcat_dash=mcat_dash,
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
        # The whole dashboard (mastery + deck score + performance + readiness +
        # pace) was computed in one shared engine scan on the background thread
        # (see get_data), so drawing the panels here does no engine work on the
        # UI thread. Falls back to a direct fetch only if that failed.
        dash = getattr(data, "mcat_dash", None)
        self.web.stdHtml(
            self._render_page_theme()
            + self._v1_upgrade_message(data.sched_upgrade_required)
            + self._render_mcat_scores(dash)
            + self._render_ai_panel()
            + self._render_mcat_panel(dash)
            + self._render_pace_panel(dash)
            + self._render_mcat_modal()
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
        """Speedrun cosmetic layer: a full Y2K / retro-computer theme for the
        home page. A cyan grid 'desktop', pixel fonts, and every panel reframed
        as a retro OS window (title bar + fake min/max/close controls), plus
        moving features — a twinkling star layer, floating sparkles, a blinking
        status light, a marquee status line and a barber-pole progress bar. It
        is a pure CSS overlay keyed to the existing panel classes: it adds no
        data and no markup, uses !important so it wins over the panels' own
        styles, and can never affect the scores or break the deck list."""
        return """
<style>
@import url('https://fonts.googleapis.com/css2?family=Press+Start+2P&family=VT323&display=swap');

@keyframes y2kFloat{0%,100%{transform:translateY(0) rotate(-6deg)}
 50%{transform:translateY(-10px) rotate(8deg)}}
@keyframes y2kTwinkle{0%,100%{opacity:.28}50%{opacity:.9}}
@keyframes y2kBlink{0%,49%{opacity:1}50%,100%{opacity:.1}}
@keyframes y2kBarber{from{background-position:0 0}to{background-position:40px 0}}
@keyframes y2kBoot{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}
@keyframes y2kMarquee{0%{transform:translateX(55%)}100%{transform:translateX(-130%)}}

/* ---------- the desktop ---------- */
html,body{font-family:'VT323','Courier New',monospace !important;color:#14132b !important;
 background:
  linear-gradient(rgba(255,255,255,.30) 2px,transparent 2px) 0 0/34px 34px,
  linear-gradient(90deg,rgba(255,255,255,.30) 2px,transparent 2px) 0 0/34px 34px,
  #18cfe0 !important;background-attachment:fixed !important;min-height:100vh;}
body{font-size:17px !important;}
body::before{content:"";position:fixed;inset:0;pointer-events:none;z-index:0;
 background-image:
  radial-gradient(2px 2px at 12% 22%,#fff,transparent),
  radial-gradient(2px 2px at 78% 14%,#fff,transparent),
  radial-gradient(3px 3px at 34% 68%,#fff,transparent),
  radial-gradient(2px 2px at 88% 74%,#fff28a,transparent),
  radial-gradient(3px 3px at 58% 41%,#ff9ed6,transparent),
  radial-gradient(2px 2px at 22% 88%,#7fe9ff,transparent);
 animation:y2kTwinkle 2.3s ease-in-out infinite;}

/* ---------- shared retro-window chrome ---------- */
.prog-greet,.pc-summary,.pc-donut-card,.ai-card,.mcat-card,.pace-card{
 background:#fbf7ff !important;border:3px solid #14132b !important;border-radius:8px !important;
 box-shadow:7px 7px 0 rgba(20,19,43,.38) !important;position:relative !important;
 overflow:hidden !important;z-index:1;animation:y2kBoot .4s steps(6,end) both !important;}

/* title-bar strip for the single-title windows */
.ai-card,.mcat-card,.pace-card,.pc-summary,.prog-greet{padding-top:34px !important;}
.ai-card::before,.mcat-card::before,.pace-card::before,.pc-summary::before,.prog-greet::before{
 position:absolute !important;top:0 !important;left:0 !important;right:0 !important;
 height:24px !important;display:flex !important;align-items:center !important;
 padding:0 10px !important;font-family:'Press Start 2P',monospace !important;
 font-size:8px !important;color:#14132b !important;border-bottom:3px solid #14132b !important;
 letter-spacing:.02em !important;text-transform:lowercase !important;border-radius:0 !important;
 width:auto !important;height:24px !important;background-clip:border-box !important;
 -webkit-text-fill-color:#14132b !important;}
.prog-greet::before{content:"\\2605 welcome.exe" !important;
 background:linear-gradient(180deg,#ff9ed6,#ff4fa3) !important;}
.pc-summary::before{content:"progress.sys" !important;
 background:linear-gradient(180deg,#8fdcff,#39a7ff) !important;}
.ai-card::before{content:"ai_generator.exe" !important;
 background:linear-gradient(180deg,#c9a3ff,#8b5cf6) !important;}
.mcat-card::before{content:"readiness.exe" !important;
 background:linear-gradient(180deg,#7dffb8,#19c37d) !important;}
.pace-card::before{content:"pace_trainer.exe" !important;
 background:linear-gradient(180deg,#ffe98a,#ffcf3f) !important;}
/* fake window controls */
.ai-card::after,.mcat-card::after,.pace-card::after,.pc-summary::after,.prog-greet::after{
 content:"_ \\25A1 \\2715" !important;position:absolute !important;top:3px !important;
 right:8px !important;left:auto !important;bottom:auto !important;width:auto !important;
 height:auto !important;font-family:'Press Start 2P',monospace !important;font-size:7px !important;
 color:#14132b !important;background:#fff !important;border:2px solid #14132b !important;
 padding:3px 4px !important;border-radius:0 !important;opacity:1 !important;
 box-shadow:none !important;line-height:1 !important;transform:none !important;
 animation:none !important;-webkit-text-fill-color:#14132b !important;}

/* ---------- greeting window ---------- */
.prog-hero{position:relative !important;max-width:720px;}
.prog-hero::before{content:"\\2726";position:absolute;left:-8px;top:38px;font-size:26px;
 color:#fff28a;text-shadow:0 0 6px #fff;animation:y2kFloat 4s ease-in-out infinite;
 pointer-events:none;z-index:5;}
.prog-hero::after{content:"\\2748";position:absolute;right:-6px;top:150px;font-size:22px;
 color:#ff9ed6;animation:y2kFloat 5s ease-in-out infinite .6s;pointer-events:none;z-index:5;}
.prog-greet h1{font-family:'VT323',monospace !important;font-size:42px !important;
 color:#14132b !important;letter-spacing:0 !important;text-shadow:2px 2px 0 #7fe9ff;
 margin:2px 0 0 !important;}
.prog-greet{overflow:hidden !important;}
.prog-greet p{font-family:'VT323',monospace !important;font-size:19px !important;
 color:#8b5cf6 !important;white-space:nowrap !important;display:inline-block !important;
 animation:y2kMarquee 13s linear infinite !important;margin:2px 0 0 !important;}

/* ---------- section label as a pixel tab ---------- */
.prog-section{font-family:'Press Start 2P',monospace !important;font-size:10px !important;
 color:#14132b !important;background:#fff28a !important;border:3px solid #14132b !important;
 box-shadow:4px 4px 0 rgba(20,19,43,.35) !important;display:inline-flex !important;
 padding:9px 12px !important;border-radius:6px !important;text-transform:uppercase !important;
 margin:20px 2px 14px !important;}
.prog-section::before{background:#ff5fae !important;border:2px solid #14132b !important;
 border-radius:0 !important;width:10px !important;height:10px !important;box-shadow:none !important;
 animation:y2kBlink 1s steps(1) infinite !important;}

/* ---------- progress summary window ---------- */
.pc-sum-big{font-family:'VT323',monospace !important;font-size:40px !important;
 color:#14132b !important;}
.pc-sum-lbl,.pc-sum-foot{font-family:'VT323',monospace !important;font-size:16px !important;}
.pc-sum-pct{font-family:'Press Start 2P',monospace !important;font-size:12px !important;
 color:#ff4fa3 !important;}
.pc-sum-pct span{font-family:'VT323',monospace !important;font-size:14px !important;}
.pc-progress{background:#fff !important;border:2px solid #14132b !important;height:16px !important;
 border-radius:0 !important;padding:2px !important;box-shadow:inset 2px 2px 0 rgba(20,19,43,.12) !important;}
.pc-progress>div{border-radius:0 !important;box-shadow:none !important;
 background:repeating-linear-gradient(45deg,#ff5fae 0 10px,#ff9ed6 10px 20px) !important;
 animation:y2kBarber .6s linear infinite !important;}

/* ---------- donut windows (Memory / Performance / Readiness) ---------- */
.pc-donut-card .pc-top{margin:-16px -16px 12px -16px !important;padding:7px 9px !important;
 border-bottom:3px solid #14132b !important;font-family:'Press Start 2P',monospace !important;
 font-size:8px !important;color:#14132b !important;align-items:center !important;}
.m-mem .pc-top{background:linear-gradient(180deg,#7fe9ff,#22b8d6) !important;}
.m-perf .pc-top{background:linear-gradient(180deg,#ff9ed6,#ff4fa3) !important;}
.m-ready .pc-top{background:linear-gradient(180deg,#7dffb8,#19c37d) !important;}
.pc-name{font-family:'Press Start 2P',monospace !important;font-size:8px !important;
 color:#14132b !important;}
.pc-badge{font-family:'Press Start 2P',monospace !important;font-size:6.5px !important;
 background:#fff !important;border:2px solid #14132b !important;border-radius:0 !important;
 color:#14132b !important;padding:3px 5px !important;}
.m-mem{--a1:#22b8d6 !important;--a2:#7fe9ff !important;}
.m-perf{--a1:#ff4fa3 !important;--a2:#ff9ed6 !important;}
.m-ready{--a1:#19c37d !important;--a2:#7dffb8 !important;}
.pc-ring-bg{stroke:#e3def2 !important;}
.pc-val{-webkit-text-fill-color:#14132b !important;background:none !important;
 color:#14132b !important;font-family:'VT323',monospace !important;font-size:36px !important;}
.pc-range{font-family:'VT323',monospace !important;font-size:15px !important;color:#14132b !important;}
.pc-range b{color:#ff4fa3 !important;}
.pc-tag{font-family:'VT323',monospace !important;font-size:12px !important;
 color:rgba(20,19,43,.55) !important;}

/* ---------- AI window ---------- */
.ai-title{font-family:'Press Start 2P',monospace !important;font-size:11px !important;
 color:#14132b !important;}
.ai-sub{font-family:'VT323',monospace !important;font-size:16px !important;color:#14132b !important;}
.ai-btn{background:#ffe98a !important;color:#14132b !important;border:3px solid #14132b !important;
 border-radius:0 !important;box-shadow:4px 4px 0 rgba(20,19,43,.4) !important;
 font-family:'Press Start 2P',monospace !important;font-size:9px !important;
 padding:12px 14px !important;text-transform:uppercase !important;}
.ai-btn:hover{transform:translate(2px,2px) !important;
 box-shadow:2px 2px 0 rgba(20,19,43,.4) !important;}

/* ---------- readiness / mastery windows ---------- */
.mcat-title,.pace-title{font-family:'Press Start 2P',monospace !important;
 font-size:11px !important;color:#14132b !important;}
.mcat-tag,.pace-tag{font-family:'VT323',monospace !important;font-size:14px !important;}
.mcat-sub,.pace-sub,.mcat-note,.pace-note{font-family:'VT323',monospace !important;
 font-size:16px !important;}
.mcat-subtitle{font-family:'Press Start 2P',monospace !important;font-size:9px !important;}
.mcat-score{-webkit-text-fill-color:#ff4fa3 !important;background:none !important;
 color:#ff4fa3 !important;font-family:'VT323',monospace !important;font-size:54px !important;}
.mcat-abstain{font-family:'Press Start 2P',monospace !important;font-size:12px !important;
 color:#e0347a !important;}
.mcat-bar{background:#fff !important;border:2px solid #14132b !important;border-radius:0 !important;
 height:14px !important;}
.mcat-range{border-radius:0 !important;box-shadow:none !important;
 background:repeating-linear-gradient(45deg,#22b8d6 0 8px,#7fe9ff 8px 16px) !important;
 animation:y2kBarber .6s linear infinite !important;}
.mcat-point{background:#14132b !important;box-shadow:none !important;border-radius:0 !important;}
.mcat-grid>div{background:#fff !important;border:2px solid #14132b !important;
 border-radius:0 !important;box-shadow:3px 3px 0 rgba(20,19,43,.22) !important;
 font-family:'VT323',monospace !important;font-size:15px !important;}
.mcat-grid b{font-family:'VT323',monospace !important;font-size:22px !important;color:#14132b !important;}
/* blinking status lights on the in-body headings */
.ai-title::before,.mcat-title::before,.pace-title::before{border-radius:0 !important;
 width:9px !important;height:9px !important;background:#19c37d !important;box-shadow:none !important;
 animation:y2kBlink 1.1s steps(1) infinite !important;}

/* ---------- retro tables ---------- */
.mcat-tablewrap,.pace-tablewrap{border:3px solid #14132b !important;border-radius:0 !important;
 box-shadow:4px 4px 0 rgba(20,19,43,.3) !important;background:#fff !important;}
.mcat-ttable,.pace-ttable{background:#fff !important;}
.mcat-ttable thead th,.pace-ttable thead th{font-family:'Press Start 2P',monospace !important;
 font-size:7.5px !important;background:#c9a3ff !important;color:#14132b !important;
 border-bottom:3px solid #14132b !important;}
.mcat-ttable tbody tr,.pace-ttable tbody tr{background:#fff !important;}
.mcat-ttable tbody tr:nth-child(even),.pace-ttable tbody tr:nth-child(even){
 background:#f3ecff !important;}
.mcat-ttable tbody td,.pace-ttable tbody td{border-top:2px solid #e6def7 !important;
 font-family:'VT323',monospace !important;font-size:16px !important;color:#14132b !important;}
.mcat-ttable tbody tr:hover,.pace-ttable tbody tr:hover{background:#ffe98a !important;}
.mcat-tname,.pace-tname{color:#14132b !important;}
.mcat-tbar{background:#eee !important;border:2px solid #14132b !important;border-radius:0 !important;
 height:11px !important;}
.mcat-tbar>div{border-radius:0 !important;box-shadow:none !important;
 background:repeating-linear-gradient(45deg,#19c37d 0 7px,#7dffb8 7px 14px) !important;}
.pace-btn{background:#ffe98a !important;color:#14132b !important;border:3px solid #14132b !important;
 border-radius:0 !important;box-shadow:4px 4px 0 rgba(20,19,43,.4) !important;
 font-family:'Press Start 2P',monospace !important;font-size:9px !important;
 text-transform:uppercase !important;padding:11px 14px !important;}
.pace-ready{color:#19c37d !important;font-family:'Press Start 2P',monospace !important;
 font-size:8px !important;}

/* ---------- the deck-list window ---------- */
center>table{background:#fff !important;border:3px solid #14132b !important;border-radius:0 !important;
 box-shadow:7px 7px 0 rgba(20,19,43,.38) !important;padding:16px 18px !important;margin-top:10px;
 font-family:'VT323','Courier New',monospace !important;position:relative;}
center>table tr,center>table td,center>table th{background:transparent !important;}
center>table th{font-family:'Press Start 2P',monospace !important;font-size:8px !important;
 color:#c02a86 !important;border-bottom:3px solid #14132b !important;text-transform:uppercase;
 padding-bottom:8px !important;}
center>table td{color:#14132b !important;font-size:18px !important;}
center>table a.deck,center>table .collapse{color:#14132b !important;}
center>table tr.deck td{border-bottom:2px solid #e6def7 !important;}
center>table .current td,
center>table tr:hover:not(.top-level-drag-row) td{background:#ffe98a !important;}
#studiedToday{font-family:'Press Start 2P',monospace !important;font-size:9px !important;
 color:#14132b !important;background:#fff !important;border:2px solid #14132b !important;
 display:inline-block !important;padding:9px 12px !important;
 box-shadow:3px 3px 0 rgba(20,19,43,.3) !important;margin:1.5em 0 !important;}
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

    def _mcat_dashboard(self):  # type: ignore[no-untyped-def]
        """Fetch all five dashboard scores in one shared engine pass
        (``mcat_dashboard``), which each score panel then reads from instead of
        issuing its own RPCs. Every field is identical to calling the matching
        single RPC; this only removes the redundant full-collection scans.
        Returns ``None`` on any error so the panels fall back to fetching for
        themselves and the deck list is never broken."""
        try:
            if self.mw.col is None:
                return None
            return self.mw.col._backend.mcat_dashboard(search="")
        except Exception:
            return None

    def _render_mcat_scores(self, dash=None) -> str:  # type: ignore[no-untyped-def]
        """The dashboard hero: a greeting header, a progress-summary card, and the
        three honest scores — Memory, Performance, and Readiness — each drawn as a
        donut with its range, driven entirely by the Rust engine (``mcat_deck_score``,
        ``mcat_performance``, ``mcat_readiness``, read here from the shared
        ``mcat_dashboard`` pass). This is the memory→performance→score bridge from
        section 4: they are shown as three *separate* numbers, never one blended
        figure. Readiness carries the engine's give-up rule and abstains when the
        evidence is thin. Fails safe to an empty string so it can never break the
        deck list."""
        try:
            if dash is None:
                dash = self._mcat_dashboard()
            if dash is None:
                return ""
            memory = dash.deck_score
            perf = dash.performance
            ready = dash.readiness
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
            p_note = f"memory × transfer {perf.transfer_factor:.2f}"
        else:
            p_note = "transfer not yet measured"

        span = (ready.scale_max - ready.scale_min) or 1.0
        if ready.has_score:
            r_center = f"{ready.projected_score:.0f}"
            r_range = f"likely <b>{ready.score_lower:.0f}–{ready.score_upper:.0f}</b>"
            r_frac = clamp01((ready.projected_score - ready.scale_min) / span)
            r_badge = f"{ready.confidence} conf"
        else:
            r_center = "—"
            missing = ready.reasons[0] if ready.reasons else "not enough data"
            r_range = f"no score yet · {html.escape(missing)}"
            r_frac = 0.0
            r_badge = "on hold"

        # Progress-summary numbers for the wide card (the mockup's "204/300 / 68%").
        reviewed = memory.rated_cards
        scorable = memory.scorable_cards
        mastered = memory.mastered_cards
        unseen = memory.unseen_cards
        coverage = clamp01(reviewed / scorable) if scorable else 0.0

        # Greeting header (the mockup's "Hey Yev," line), from the local time and
        # the current Anki profile name; the subtitle is the honest studied-today
        # line Anki already computes.
        import time as _time

        _hour = _time.localtime().tm_hour
        _part = "morning" if _hour < 12 else "afternoon" if _hour < 18 else "evening"
        try:
            _name = (self.mw.pm.name or "").strip()
        except Exception:
            _name = ""
        greet = f"Good {_part}" + (f", {html.escape(_name)}" if _name else "")
        try:
            studied = self._render_data.studied_today or "Time to study."
        except Exception:
            studied = "Time to study."

        # SVG donut (the mockup's colored pie cards). r=46 in a 104px box gives a
        # circumference we split into a coloured "filled" arc and a track.
        import math as _math

        _circ = 2 * _math.pi * 46.0

        def _donut(key: str, frac: float, center: str) -> str:
            fill = clamp01(frac) * _circ
            return f"""
      <div class="pc-donut">
        <svg viewBox="0 0 104 104">
          <defs><linearGradient id="grad-{key}" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stop-color="var(--a1)"/>
            <stop offset="100%" stop-color="var(--a2)"/></linearGradient></defs>
          <circle class="pc-ring-bg" cx="52" cy="52" r="46"/>
          <circle class="pc-ring-fg" cx="52" cy="52" r="46" stroke="url(#grad-{key})"
            stroke-dasharray="{fill:.1f} {_circ - fill:.1f}"/>
        </svg>
        <div class="pc-center"><div class="pc-val">{center}</div></div>
      </div>"""

        def _donut_card(
            cls: str,
            key: str,
            title: str,
            badge: str,
            frac: float,
            center: str,
            range_html: str,
            tag: str,
        ) -> str:
            return f"""
    <div class="prog-card pc-donut-card {cls}">
      <div class="pc-top"><span class="pc-name">{title}</span>
       <span class="pc-badge">{badge}</span></div>
      {_donut(key, frac, center)}
      <div class="pc-range">{range_html}</div>
      <div class="pc-tag">{tag}</div>
    </div>"""

        mem_card = _donut_card(
            "m-mem",
            "mem",
            "Memory",
            "recall",
            m_point,
            pct(m_point),
            f"range <b>{pct(m_lower)}–{pct(m_upper)}</b>",
            "Rust · mcat_deck_score",
        )
        perf_card = _donut_card(
            "m-perf",
            "perf",
            "Performance",
            "new Qs",
            p_point,
            pct(p_point),
            f"range <b>{pct(p_lower)}–{pct(p_upper)}</b>",
            f"Rust · mcat_performance · {html.escape(p_note)}",
        )
        ready_card = _donut_card(
            "m-ready",
            "ready",
            "Readiness",
            r_badge,
            r_frac,
            r_center,
            r_range,
            f"Rust · mcat_readiness · MCAT {ready.scale_min:.0f}–{ready.scale_max:.0f}",
        )

        css = """
<style>
@keyframes mcatUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}
.prog-hero{max-width:720px;margin:16px auto 4px;text-align:start;
 animation:mcatUp .5s cubic-bezier(.2,.7,.3,1) both;}
.prog-greet h1{font-size:27px;font-weight:900;color:#2c2a44;margin:0;letter-spacing:-.02em;}
.prog-greet p{font-size:13px;color:rgba(49,46,77,.62);margin:5px 0 0;}
.prog-section{font-size:13px;font-weight:800;color:rgba(49,46,77,.72);
 margin:18px 2px 11px;display:flex;align-items:center;gap:8px;}
.prog-section::before{content:"";width:8px;height:8px;border-radius:50%;
 background:linear-gradient(135deg,#6d5efc,#9d8bff);}
.prog-row{display:flex;gap:12px;flex-wrap:wrap;align-items:stretch;}
.prog-card{border-radius:22px;padding:16px 16px 14px;position:relative;overflow:hidden;
 border:1px solid var(--brd,#e7e3fb);
 background:linear-gradient(150deg,var(--bg1,#fff),var(--bg2,#f7f6ff));
 box-shadow:0 10px 26px var(--glow,rgba(109,94,252,.14)),0 2px 6px rgba(60,50,110,.05);
 transition:transform .18s ease,box-shadow .18s ease;
 animation:mcatUp .5s cubic-bezier(.2,.7,.3,1) both;}
.prog-card:hover{transform:translateY(-4px);
 box-shadow:0 18px 40px var(--glow,rgba(109,94,252,.2)),0 4px 10px rgba(60,50,110,.08);}
.pc-donut-card{flex:1 1 148px;min-width:148px;display:flex;flex-direction:column;}
.pc-donut-card:nth-child(3){animation-delay:.06s}
.pc-donut-card:nth-child(4){animation-delay:.12s}
.pc-summary{flex:1.6 1 210px;min-width:210px;--bg1:#ffffff;--bg2:#f6f5ff;
 --brd:#e7e3fb;--glow:rgba(109,94,252,.14);color:#2c2a44;}
.pc-top{display:flex;justify-content:space-between;align-items:center;gap:6px;}
.pc-name{font-weight:800;font-size:14px;color:#312e4d;}
.pc-badge{font-size:9.5px;font-weight:800;color:var(--a1);background:rgba(255,255,255,.72);
 border:1px solid var(--brd);padding:3px 8px;border-radius:999px;white-space:nowrap;}
.pc-donut{position:relative;width:104px;height:104px;margin:12px auto 4px;}
.pc-donut svg{width:104px;height:104px;transform:rotate(-90deg);}
.pc-ring-bg{fill:none;stroke:rgba(49,46,77,.11);stroke-width:8;}
.pc-ring-fg{fill:none;stroke-width:8;stroke-linecap:round;}
.pc-center{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;}
.pc-val{font-size:24px;font-weight:900;color:var(--a1);
 background:linear-gradient(135deg,var(--a1),var(--a2));-webkit-background-clip:text;
 background-clip:text;-webkit-text-fill-color:transparent;line-height:1;}
.pc-range{font-size:11px;color:rgba(49,46,77,.72);text-align:center;margin-top:3px;}
.pc-range b{color:var(--a1);}
.pc-tag{font-size:9px;color:rgba(49,46,77,.42);text-align:center;
 margin-top:auto;padding-top:8px;}
.pc-sum-big{font-size:29px;font-weight:900;color:#2c2a44;letter-spacing:-.02em;line-height:1;}
.pc-sum-lbl{font-size:12px;color:rgba(49,46,77,.6);margin-top:4px;}
.pc-sum-pct{font-size:15px;font-weight:900;color:#6d5efc;margin-top:15px;}
.pc-sum-pct span{font-size:11px;font-weight:600;color:rgba(49,46,77,.55);margin-left:5px;}
.pc-progress{height:9px;border-radius:999px;background:rgba(49,46,77,.10);
 margin-top:7px;overflow:hidden;}
.pc-progress>div{height:100%;border-radius:999px;
 background:linear-gradient(90deg,#6d5efc,#9d8bff);box-shadow:0 0 10px rgba(109,94,252,.45);}
.pc-sum-foot{font-size:11px;color:rgba(49,46,77,.55);margin-top:10px;}
.m-mem{--a1:#6d5efc;--a2:#9d8bff;--bg1:#eef0ff;--bg2:#f7f0ff;--brd:#ddd8ff;--glow:rgba(109,94,252,.22);}
.m-perf{--a1:#c026d3;--a2:#f472e6;--bg1:#fdeafe;--bg2:#fdf0f8;--brd:#f4d3f6;--glow:rgba(192,38,211,.20);}
.m-ready{--a1:#0d9488;--a2:#34d399;--bg1:#e5fbf3;--bg2:#effcf1;--brd:#c4f1e2;--glow:rgba(13,148,136,.20);}
</style>
"""
        return (
            css
            + f"""
<div class="prog-hero">
  <div class="prog-greet">
    <h1>{greet}</h1>
    <p>{html.escape(studied)} 💪</p>
  </div>
  <div class="prog-section">My Progress</div>
  <div class="prog-row">
    <div class="prog-card pc-summary">
      <div class="pc-sum-big">{reviewed:,} / {scorable:,}</div>
      <div class="pc-sum-lbl">Cards reviewed</div>
      <div class="pc-sum-pct">{pct(coverage)}<span>of deck covered</span></div>
      <div class="pc-progress"><div style="width:{coverage * 100:.0f}%"></div></div>
      <div class="pc-sum-foot">{mastered:,} mastered · {unseen:,} still to review</div>
    </div>
    {mem_card}
    {perf_card}
    {ready_card}
  </div>
</div>
"""
        )

    def _render_mcat_panel(self, dash=None) -> str:  # type: ignore[no-untyped-def]
        """Home-page readiness card driven entirely by the Rust engine calls
        ``mcat_deck_score`` and ``mcat_mastery`` (read here from the shared
        ``mcat_dashboard`` pass). Fails safe to an empty string so it can never
        break the deck list."""
        try:
            if dash is None:
                dash = self._mcat_dashboard()
            if dash is None:
                return ""
            score = dash.deck_score
            mastery = dash.mastery
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
.mcat-tablewrap{margin-top:14px;border-radius:16px;overflow:hidden;
 border:1px solid rgba(13,148,136,.18);background:#edfbf5;
 box-shadow:0 4px 14px rgba(13,148,136,.10);}
.mcat-ttable{width:100%;border-collapse:collapse;font-size:12px;background:#edfbf5;}
.mcat-ttable thead th{background:#cdf3e7;color:#0f766e;font-weight:800;
 font-size:10px;text-transform:uppercase;letter-spacing:.05em;padding:9px 12px;text-align:start;}
.mcat-ttable thead th.num{text-align:end;}
.mcat-ttable tbody tr{background:#edfbf5;}
.mcat-ttable tbody tr:nth-child(even){background:#e0f7ee;}
.mcat-ttable tbody td{background:transparent;padding:9px 12px;
 border-top:1px solid rgba(13,148,136,.12);color:#26413a;vertical-align:middle;}
.mcat-ttable tbody tr:hover{background:#d3f4e6;}
.mcat-ttable tbody tr:hover td{background:transparent;}
.mcat-ttable .num{text-align:end;font-variant-numeric:tabular-nums;color:rgba(38,65,58,.85);}
.mcat-tname{font-weight:700;color:#1d3630;}
.mcat-tbarcell{width:120px;}
.mcat-tbar{height:8px;border-radius:999px;background:rgba(38,65,58,.12);overflow:hidden;}
.mcat-tbar>div{height:100%;border-radius:999px;
 background:linear-gradient(90deg,#0d9488,#34d399);box-shadow:0 0 8px rgba(52,211,153,.55);}
</style>
"""

        # 7a Rust change on the dashboard: per-topic mastery from mcat_mastery.
        # Topics are listed in deck order (alphabetical by full deck name), the
        # same order the deck list uses when you pick a deck to study, so this
        # table lines up row-for-row with the Pace Trainer below it.
        def _leaf(name: str) -> str:
            # Show just the deck's leaf name (after the last "::") so the table
            # reads cleanly; the full path stays in the tooltip.
            return name.split("::")[-1].strip() or name

        # Reuse the Pace Trainer's per-topic review counts so the "Reviews"
        # number for a topic (e.g. "Behavioral") is identical in both panels
        # instead of showing unique-reviewed-cards here and review-events there.
        pace_reviews = {p.deck_id: p.window_reviews for p in dash.pace.topics}
        window_days = dash.pace.window_days

        topic_rows = ""
        for t in sorted(mastery.topics, key=lambda t: t.topic):
            frac = (t.mastered_cards / t.total_cards) if t.total_cards else 0.0
            recall = pct(t.average_recall) if t.rated_cards else "—"
            reviews = pace_reviews.get(t.deck_id, 0)
            topic_rows += f"""
    <tr><td class="mcat-tname" title="{html.escape(t.topic)}">{html.escape(_leaf(t.topic))}</td>
    <td class="num">{t.mastered_cards}/{t.total_cards}</td><td class="num">{reviews}</td>
    <td class="num">{recall}</td>
    <td class="mcat-tbarcell"><div class="mcat-tbar">
      <div style="width:{frac * 100:.0f}%"></div></div></td></tr>"""

        topics_html = f"""
<div class="mcat-card">
  <div class="mcat-subtitle"><span>Per-topic mastery</span>
   <span class="mcat-tag">Rust engine · mcat_mastery</span></div>
  <div class="mcat-tablewrap">
  <table class="mcat-ttable">
    <thead><tr><th>Topic</th><th class="num">Mastered</th>
     <th class="num">Reviews ({window_days}d)</th>
     <th class="num">Avg recall</th><th>Mastery</th></tr></thead>
    <tbody>{topic_rows}</tbody>
  </table>
  </div>
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

    def _mcat_set_exam_date_value(self, text: str) -> None:
        """Store the MCAT date submitted by the in-page Y2K modal (epoch seconds)
        in the config key the Rust pace model reads. Only sets the ladder's
        *starting* rung. The modal already validates the YYYY-MM-DD shape; this
        keeps the strptime guard as a safety net for impossible dates."""
        import datetime

        text = (text or "").strip()
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

    def _render_mcat_modal(self) -> str:
        """Y2K in-webview pop-up for the MCAT exam-date prompt so the dialog
        matches the deck page exactly (native Qt dialogs can't). It is a retro OS
        window (title bar + fake close control, pixel font, chunky push-buttons)
        over a dimmed backdrop, hidden until ``mcatExamModal(cur)`` shows it. OK
        submits the typed date back to Python via ``pycmd`` for validation and
        storage; it adds no data and can never break the deck list."""
        return r"""
<style>
#mcat-modal-back{position:fixed;inset:0;z-index:9999;display:none;
 align-items:center;justify-content:center;background:rgba(20,19,43,.55);}
#mcat-modal-back.show{display:flex;}
#mcat-modal{width:340px;max-width:88vw;background:#fbf7ff;border:3px solid #14132b;
 border-radius:8px;box-shadow:9px 9px 0 rgba(20,19,43,.45);overflow:hidden;
 font-family:'VT323','Courier New',monospace;animation:y2kBoot .3s steps(6,end) both;}
#mcat-modal .mm-bar{display:flex;align-items:center;justify-content:space-between;
 height:26px;padding:0 10px;border-bottom:3px solid #14132b;
 background:linear-gradient(180deg,#ffe98a,#ffcf3f);
 font-family:'Press Start 2P',monospace;font-size:8px;color:#14132b;
 text-transform:lowercase;}
#mcat-modal .mm-x{font-family:'Press Start 2P',monospace;font-size:7px;color:#14132b;
 background:#fff;border:2px solid #14132b;padding:3px 4px;line-height:1;cursor:pointer;}
#mcat-modal .mm-body{padding:16px 16px 18px;}
#mcat-modal .mm-title{font-family:'Press Start 2P',monospace;font-size:10px;
 color:#14132b;margin:0 0 14px;line-height:1.7;}
#mcat-modal .mm-input{width:100%;box-sizing:border-box;font-family:'VT323',monospace;
 font-size:24px;color:#14132b;background:#fff;border:3px solid #14132b;border-radius:0;
 padding:5px 10px;margin-bottom:4px;letter-spacing:.04em;}
#mcat-modal .mm-input:focus{outline:none;box-shadow:inset 3px 3px 0 rgba(20,19,43,.14);}
#mcat-modal .mm-err{font-family:'VT323',monospace;font-size:16px;color:#e0347a;
 min-height:20px;margin-bottom:8px;}
#mcat-modal .mm-row{display:flex;gap:10px;align-items:center;}
#mcat-modal .mm-btn{font-family:'Press Start 2P',monospace;font-size:9px;color:#14132b;
 border:3px solid #14132b;border-radius:0;cursor:pointer;padding:10px 12px;
 text-transform:uppercase;box-shadow:4px 4px 0 rgba(20,19,43,.4);}
#mcat-modal .mm-btn:hover{transform:translate(2px,2px);box-shadow:2px 2px 0 rgba(20,19,43,.4);}
#mcat-modal .mm-ok{background:#7dffb8;}
#mcat-modal .mm-cancel{background:#fff;}
</style>
<div id="mcat-modal-back" onclick="if(event.target===this)mcatCloseExam()">
  <div id="mcat-modal">
    <div class="mm-bar"><span>&#x2605; set_exam_date.exe</span>
     <span class="mm-x" onclick="mcatCloseExam()">&#x2715;</span></div>
    <div class="mm-body">
      <div class="mm-title">Enter your MCAT<br>exam date</div>
      <input id="mcat-exam-input" class="mm-input" type="text"
       placeholder="YYYY-MM-DD" inputmode="numeric" maxlength="10"
       onkeydown="if(event.key==='Enter')mcatSubmitExam()">
      <div id="mcat-exam-err" class="mm-err"></div>
      <div class="mm-row">
        <button class="mm-btn mm-cancel" onclick="mcatCloseExam()">Cancel</button>
        <button class="mm-btn mm-ok" onclick="mcatSubmitExam()">OK</button>
      </div>
    </div>
  </div>
</div>
<script>
function mcatExamModal(cur){
  var i=document.getElementById('mcat-exam-input');
  if(i){i.value=cur||'';}
  var e=document.getElementById('mcat-exam-err');if(e){e.textContent='';}
  document.getElementById('mcat-modal-back').classList.add('show');
  if(i){setTimeout(function(){i.focus();i.select();},30);}
}
function mcatCloseExam(){
  document.getElementById('mcat-modal-back').classList.remove('show');
}
function mcatSubmitExam(){
  var i=document.getElementById('mcat-exam-input');
  var v=((i&&i.value)||'').trim();
  var e=document.getElementById('mcat-exam-err');
  var m=/^(\d{4})-(\d{2})-(\d{2})$/.exec(v);
  if(!m||+m[2]<1||+m[2]>12||+m[3]<1||+m[3]>31){
    if(e){e.textContent='Use format YYYY-MM-DD';}
    return;
  }
  pycmd('mcat_set_exam_date:'+v);
}
</script>
"""

    def _render_pace_panel(self, dash=None) -> str:  # type: ignore[no-untyped-def]
        """Home-page Pace Trainer card driven by the Rust ``mcat_pace`` RPC (read
        here from the shared ``mcat_dashboard`` pass). Shows the exam-date prompt
        when unset, then the pace ladder and per-topic target / accuracy /
        mean-time, listed in deck order so the rows line up with the Per-topic
        mastery table and the deck list. Fails safe to an empty string so it can
        never break the deck list."""
        try:
            if dash is None:
                dash = self._mcat_dashboard()
            if dash is None:
                return ""
            pace = dash.pace
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
.pace-tablewrap{margin-top:12px;border-radius:16px;overflow:hidden;
 border:1px solid rgba(234,122,27,.22);background:#fff7ec;
 box-shadow:0 4px 14px rgba(234,122,27,.10);}
.pace-ttable{width:100%;border-collapse:collapse;font-size:12px;background:#fff7ec;}
.pace-ttable thead th{background:#ffe7c4;color:#b45309;font-weight:800;
 font-size:10px;text-transform:uppercase;letter-spacing:.05em;padding:9px 12px;text-align:start;}
.pace-ttable thead th.num{text-align:end;}
.pace-ttable tbody tr{background:#fff7ec;}
.pace-ttable tbody tr:nth-child(even){background:#fdeed6;}
.pace-ttable tbody td{background:transparent;padding:9px 12px;
 border-top:1px solid rgba(234,122,27,.14);color:#4a3410;vertical-align:middle;}
.pace-ttable tbody tr:hover{background:#fde3ba;}
.pace-ttable tbody tr:hover td{background:transparent;}
.pace-ttable .num{text-align:end;font-variant-numeric:tabular-nums;color:rgba(74,52,16,.9);}
.pace-tname{font-weight:700;color:#3a2708;}
.pace-phase{color:rgba(74,52,16,.75);}
.pace-note{font-size:11px;color:rgba(74,52,16,.72);margin-top:12px;line-height:1.5;}
.pace-note b{color:#4a3410;}
.pace-ready{color:#0d9488;font-weight:800;}
</style>
"""

        import datetime as _dt

        current_cfg = self.mw.col.get_config("examDate", None)
        cur_str = ""
        if current_cfg:
            try:
                cur_str = _dt.datetime.fromtimestamp(current_cfg).strftime("%Y-%m-%d")
            except (ValueError, OverflowError, OSError):
                cur_str = ""

        if pace.exam_months_remaining < 0:
            exam_html = """
  <div class="pace-sub">No exam date set — the ladder starts at
   <b>unlimited</b> until you add one.</div>
  <div class="pace-btn" onclick="mcatExamModal('')">Set MCAT exam date</div>"""
        else:
            start_ms = self._PACE_LADDER_MS[
                min(pace.start_rung, len(self._PACE_LADDER_MS) - 1)
            ]
            exam_html = f"""
  <div class="pace-sub">Exam in <b>{pace.exam_months_remaining:.1f} months</b>
   · starting target <b>{target_label(start_ms)}</b> · goal <b>{goal}</b>
   <span class="pace-tag" style="cursor:pointer"
    onclick="mcatExamModal('{cur_str}')">(change)</span>
   <span class="pace-tag" style="cursor:pointer"
    onclick='pycmd("mcat_clear_exam")'>(clear)</span></div>"""

        def _leaf(name: str) -> str:
            # Show just the deck's leaf name (after the last "::"); full path
            # stays in the tooltip.
            return name.split("::")[-1].strip() or name

        rows = ""
        # Deck order (alphabetical by full deck name) so this table lines up
        # row-for-row with the Per-topic mastery table and the deck list you
        # pick from when you start studying.
        for t in sorted(pace.topics, key=lambda t: t.topic):
            acc = f"{t.accuracy * 100:.0f}%" if t.window_reviews else "—"
            mean = secs(t.mean_answer_ms) if t.window_reviews else "—"
            status = f'<span class="pace-phase">{html.escape(t.phase)}</span>'
            if t.ready_for_next_rung:
                status += ' <span class="pace-ready">▲ almost</span>'
            rows += f"""
    <tr><td class="pace-tname" title="{html.escape(t.topic)}">{html.escape(_leaf(t.topic))}</td>
    <td class="num">{t.window_reviews}</td><td class="num">{acc}</td><td class="num">{mean}</td>
    <td class="num">{target_label(t.target_ms)}</td><td>{status}</td></tr>"""

        return (
            css
            + f"""
<div class="pace-card">
  <div class="pace-head">
    <span class="pace-title">Pace Trainer</span>
    <span class="pace-tag">Rust engine · mcat_pace</span>
  </div>{exam_html}
  <div class="pace-tablewrap">
  <table class="pace-ttable">
    <thead><tr><th>Topic</th><th class="num">Reviews ({pace.window_days}d)</th>
     <th class="num">Accuracy</th><th class="num">Mean time</th>
     <th class="num">Target</th><th>Phase</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  </div>
  <div class="pace-note">Topics are listed in deck order — the same order as
   the deck list you pick from to study and the Per-topic mastery table above.
   A topic only
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
