# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
"""Speedrun cosmetic layer: a shared Y2K / retro-computer theme for the desktop
webviews other than the home dashboard (which styles itself in ``deckbrowser``).

``page_theme(scope)`` returns a ``<style>`` block that reframes an Anki webview
as a retro OS "desktop": a cyan grid background with a twinkling star layer,
pixel fonts, retro window chrome (title bar + fake min/max/close controls) and
chunky push-buttons. It is a pure CSS overlay keyed to Anki's existing markup —
it adds no data and no DOM, uses ``!important`` so it wins over the page's own
styles, and never touches the study content itself (card text keeps its own
font so passages stay readable)."""

from __future__ import annotations

_FONTS = (
    "@import url('https://fonts.googleapis.com/css2?"
    "family=Press+Start+2P&family=VT323&display=swap');"
)

_KEYFRAMES = """
@keyframes y2kTwinkle{0%,100%{opacity:.28}50%{opacity:.9}}
@keyframes y2kBlink{0%,49%{opacity:1}50%,100%{opacity:.1}}
@keyframes y2kBarber{from{background-position:0 0}to{background-position:40px 0}}
@keyframes y2kBoot{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}
@keyframes y2kFloat{0%,100%{transform:translateY(0) rotate(-6deg)}
 50%{transform:translateY(-10px) rotate(8deg)}}
"""

# cyan grid "desktop" + twinkling star field + one floating sparkle
_DESKTOP_BG = """
html,body{font-family:'VT323','Courier New',monospace !important;color:#14132b !important;
 background:
  linear-gradient(rgba(255,255,255,.30) 2px,transparent 2px) 0 0/34px 34px,
  linear-gradient(90deg,rgba(255,255,255,.30) 2px,transparent 2px) 0 0/34px 34px,
  #18cfe0 !important;background-attachment:fixed !important;min-height:100vh;}
body::before{content:"";position:fixed;inset:0;pointer-events:none;z-index:0;
 background-image:
  radial-gradient(2px 2px at 12% 22%,#fff,transparent),
  radial-gradient(2px 2px at 78% 14%,#fff,transparent),
  radial-gradient(3px 3px at 34% 68%,#fff,transparent),
  radial-gradient(2px 2px at 88% 74%,#fff28a,transparent),
  radial-gradient(3px 3px at 58% 41%,#ff9ed6,transparent),
  radial-gradient(2px 2px at 22% 88%,#7fe9ff,transparent);
 animation:y2kTwinkle 2.3s ease-in-out infinite;}
body::after{content:"\\2726";position:fixed;left:6%;top:28%;font-size:26px;color:#fff28a;
 text-shadow:0 0 6px #fff;animation:y2kFloat 4.5s ease-in-out infinite;
 pointer-events:none;z-index:0;}
"""

# ---- the deck overview (shown when a deck is clicked) -----------------------
_OVERVIEW = """
center{position:relative !important;max-width:560px !important;margin:28px auto !important;
 background:#fbf7ff !important;border:3px solid #14132b !important;border-radius:8px !important;
 box-shadow:7px 7px 0 rgba(20,19,43,.38) !important;padding:46px 24px 28px !important;
 z-index:1;animation:y2kBoot .4s steps(6,end) both !important;}
center::before{content:"study.exe";position:absolute;top:0;left:0;right:0;height:26px;
 display:flex;align-items:center;padding:0 10px;font-family:'Press Start 2P',monospace;
 font-size:8px;color:#14132b;border-bottom:3px solid #14132b;
 background:linear-gradient(180deg,#8fdcff,#39a7ff);border-radius:8px 8px 0 0;}
center::after{content:"_ \\25A1 \\2715";position:absolute;top:5px;right:8px;
 font-family:'Press Start 2P',monospace;font-size:7px;color:#14132b;background:#fff;
 border:2px solid #14132b;padding:3px 4px;line-height:1;}
center h3{font-family:'Press Start 2P',monospace !important;font-size:15px !important;
 color:#14132b !important;text-shadow:2px 2px 0 #7fe9ff;margin:6px 0 16px !important;
 line-height:1.5 !important;}
.descfont,.description,.descmid{font-family:'VT323',monospace !important;font-size:17px !important;
 color:#14132b !important;}
center table{font-family:'VT323',monospace !important;color:#14132b !important;}
center table td{font-size:19px !important;color:#14132b !important;}
.new-count{color:#2f78d6 !important;}
.learn-count{color:#e0347a !important;}
.review-count{color:#19a06a !important;}
#study,button#study{background:#ffe98a !important;color:#14132b !important;
 border:3px solid #14132b !important;border-radius:0 !important;
 box-shadow:5px 5px 0 rgba(20,19,43,.4) !important;
 font-family:'Press Start 2P',monospace !important;font-size:11px !important;
 padding:14px 20px !important;text-transform:uppercase !important;cursor:pointer;}
#study:hover{transform:translate(2px,2px) !important;
 box-shadow:3px 3px 0 rgba(20,19,43,.4) !important;}
a,a.smallLink{color:#8b5cf6 !important;}
"""

# ---- the reviewer's main webview (the card sits in a window) ----------------
# The card body keeps its own font so long passages stay readable; we only add
# the desktop background and frame the card in a retro window.
_REVIEWER = """
#qa{background:#fff !important;border:3px solid #14132b !important;border-radius:8px !important;
 box-shadow:7px 7px 0 rgba(20,19,43,.30) !important;padding:24px 26px !important;
 max-width:840px;margin:26px auto !important;position:relative;z-index:1;
 animation:y2kBoot .4s steps(6,end) both !important;}
"""

# ---- the reviewer's bottom bar (Again / Hard / Good / Easy) -----------------
_REVIEWER_BOTTOM = """
html,body{background:#18cfe0 !important;font-family:'VT323','Courier New',monospace !important;
 background-image:
  linear-gradient(rgba(255,255,255,.30) 2px,transparent 2px),
  linear-gradient(90deg,rgba(255,255,255,.30) 2px,transparent 2px) !important;
 background-size:34px 34px !important;}
#outer,#innertable,#middle{background:transparent !important;}
button{background:#fbf7ff !important;color:#14132b !important;border:3px solid #14132b !important;
 border-radius:0 !important;box-shadow:3px 3px 0 rgba(20,19,43,.4) !important;
 font-family:'Press Start 2P',monospace !important;font-size:9px !important;
 padding:9px 12px !important;text-transform:uppercase !important;cursor:pointer;}
button:hover{transform:translate(1px,1px) !important;
 box-shadow:2px 2px 0 rgba(20,19,43,.4) !important;}
.stattxt,#time{font-family:'VT323','Courier New',monospace !important;font-size:13px !important;
 color:#14132b !important;text-transform:none !important;}
"""

# ---- the statistics page (SvelteKit "graphs") ------------------------------
# Each graph is a TitledContainer ``.container`` with an ``<h1>`` title, laid
# out in a ``.graphs-container`` grid. We reframe every graph card as a retro
# OS window (title bar from its own <h1>, chunky border, hard shadow) so the
# stats screen matches the home dashboard. The graph SVGs keep their own colours
# so the charts stay readable.
_GRAPHS = """
/* force the page out of the dark palette so it matches the light home page */
.night-mode,html.night-mode,body{color:#14132b !important;}
.container{
 background:#fbf7ff !important;border:3px solid #14132b !important;border-radius:0 !important;
 box-shadow:6px 6px 0 rgba(20,19,43,.35) !important;overflow:hidden !important;
 color:#14132b !important;animation:y2kBoot .4s steps(6,end) both !important;}
.container h1{
 font-family:'Press Start 2P',monospace !important;font-size:9px !important;
 color:#14132b !important;background:linear-gradient(180deg,#8fdcff,#39a7ff) !important;
 border:0 !important;border-bottom:3px solid #14132b !important;line-height:1.5 !important;
 margin:-1rem -1.75rem 14px -1.25rem !important;padding:9px 12px !important;
 text-transform:lowercase !important;letter-spacing:.02em !important;}
.container *{color:#14132b !important;}
/* graph axis / value text is drawn as SVG <text>; force it to ink so it stays
   readable on the light retro cards even when Anki is in night mode */
svg text{fill:#14132b !important;opacity:1 !important;}
.graph .subtitle{font-family:'VT323',monospace !important;font-size:16px !important;
 color:#14132b !important;}
/* range/day controls become retro fields */
input,select,button,label{font-family:'VT323','Courier New',monospace !important;
 color:#14132b !important;}
input[type=text],input[type=number],select{background:#fff !important;color:#14132b !important;
 border:2px solid #14132b !important;border-radius:0 !important;}
button{background:#fbf7ff !important;border:2px solid #14132b !important;border-radius:0 !important;}
h1,h2,h3{color:#14132b !important;}
table{font-family:'VT323','Courier New',monospace !important;color:#14132b !important;}
table td,table th{font-size:16px !important;color:#14132b !important;}
"""

_SCOPES = {
    "overview": _DESKTOP_BG + _OVERVIEW,
    "reviewer": _DESKTOP_BG + _REVIEWER,
    "reviewer_bottom": _REVIEWER_BOTTOM,
    "graphs": _DESKTOP_BG + _GRAPHS,
}


def page_theme(scope: str) -> str:
    """Return a ``<style>`` overlay for the given webview scope.

    Unknown scopes fall back to the bare desktop background so a new caller can
    never break by requesting a scope that does not exist yet.
    """
    body = _SCOPES.get(scope, _DESKTOP_BG)
    return f"<style>\n{_FONTS}\n{_KEYFRAMES}\n{body}\n</style>\n"


def inject_style_js(scope: str) -> str:
    """Return JS that appends this scope's theme as a ``<style>`` element.

    For webviews that load a compiled SvelteKit/TS page (e.g. the statistics
    ``graphs`` page) we can't pass a ``<style>`` through ``stdHtml``; instead we
    ``eval`` this after load. It is idempotent (guards on a fixed id) so it is
    safe to call on every refresh, and fails closed inside the page (a bad
    scope just injects the plain desktop background)."""
    import json

    css = _FONTS + _KEYFRAMES + _SCOPES.get(scope, _DESKTOP_BG)
    element_id = f"mcat-y2k-{scope}"
    return (
        "(function(){"
        f"var id={json.dumps(element_id)};"
        "if(document.getElementById(id)){return;}"
        "var s=document.createElement('style');s.id=id;"
        f"s.textContent={json.dumps(css)};"
        "(document.head||document.documentElement).appendChild(s);"
        "})();"
    )


# ---- native Qt windows (Add, Browse, Stats chrome) -------------------------
# The home dashboard is a webview we style with CSS; the Add and Browse windows
# are native Qt widgets, so they need a Qt stylesheet (QSS) instead. This gives
# them the same Y2K palette — ink borders, pastel panels, chunky pink/purple
# controls — so the whole app feels cohesive. It only changes colours, borders
# and fonts (never layout/margins) and is applied per-window, so it can't affect
# any other dialog. Qt fonts fall back to a monospace family (web pixel fonts
# aren't available to native widgets), which still reads as retro.
_QSS = """
QMainWindow, QDialog { background: #18cfe0; }
/* fill every generic widget with the cyan "desktop" so night mode can't bleed
   through; specific widgets below re-set their own (white fields, panels…) */
QWidget { background-color: #18cfe0; color: #14132b;
 font-family: "Consolas", "Courier New", monospace; }
QLabel, QCheckBox, QRadioButton, QGroupBox { color: #14132b; background: transparent; }
QDockWidget { background: #18cfe0; color: #14132b; }
QDockWidget::title { background: #c9a3ff; padding: 4px; border: 2px solid #14132b; }
QGroupBox { border: 2px solid #14132b; border-radius: 0; margin-top: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }

QPushButton {
 background: #fbf7ff; color: #14132b;
 border: 2px solid #14132b; border-radius: 0;
 padding: 5px 12px; font-weight: bold;
}
QPushButton:hover { background: #ffe98a; }
QPushButton:pressed { background: #ff9ed6; }
QPushButton:disabled { color: #8781a3; background: #efeaf7; border-color: #8781a3; }
QPushButton:default { background: #ffe98a; }

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit, QDateEdit {
 background: #ffffff; color: #14132b;
 border: 2px solid #14132b; border-radius: 0; padding: 3px 5px;
 selection-background-color: #ff9ed6; selection-color: #14132b;
}
QComboBox::drop-down { border-left: 2px solid #14132b; width: 18px; }
QComboBox QAbstractItemView {
 background: #fbf7ff; color: #14132b; border: 2px solid #14132b;
 selection-background-color: #ffe98a; selection-color: #14132b;
}

QTableView, QTreeView, QListView {
 background: #ffffff; color: #14132b;
 border: 2px solid #14132b; border-radius: 0;
 gridline-color: #e0d5f5; alternate-background-color: #f3ecff;
 selection-background-color: #ffe98a; selection-color: #14132b;
}
QAbstractItemView { background: #ffffff; color: #14132b; }
QTableView::item, QTreeView::item, QListView::item {
 background: transparent; color: #14132b;
}
QTableView::item:selected, QTreeView::item:selected, QListView::item:selected {
 background: #ffe98a; color: #14132b;
}
QTreeView::branch { background: #ffffff; }
QHeaderView::section {
 background: #c9a3ff; color: #14132b;
 border: 0; border-right: 2px solid #14132b; border-bottom: 3px solid #14132b;
 padding: 5px 7px; font-weight: bold;
}

QTabWidget::pane { border: 2px solid #14132b; }
QTabBar::tab {
 background: #fbf7ff; color: #14132b; border: 2px solid #14132b;
 padding: 5px 12px; margin-right: 2px;
}
QTabBar::tab:selected { background: #ffe98a; }

QMenuBar { background: #18cfe0; color: #14132b; }
QMenuBar::item { background: transparent; padding: 4px 8px; }
QMenuBar::item:selected { background: #ffe98a; }
QMenu { background: #fbf7ff; color: #14132b; border: 2px solid #14132b; }
QMenu::item:selected { background: #ffe98a; }

QToolBar { background: #18cfe0; border: 0; spacing: 4px; }
QToolButton {
 background: #fbf7ff; color: #14132b; border: 2px solid #14132b; border-radius: 0;
 padding: 4px 6px;
}
QToolButton:hover { background: #ffe98a; }
QStatusBar { background: #18cfe0; color: #14132b; }
QSplitter::handle { background: #14132b; }

QScrollBar:vertical { background: #e3def2; width: 14px; margin: 0; }
QScrollBar:horizontal { background: #e3def2; height: 14px; margin: 0; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
 background: #8b5cf6; border: 2px solid #14132b;
}
QScrollBar::add-line, QScrollBar::sub-line { background: transparent; border: 0; }
"""


def qt_stylesheet() -> str:
    """Return the Y2K Qt stylesheet for a native window (Add / Browse / Stats).

    Apply with ``widget.setStyleSheet(mcat_theme.qt_stylesheet())`` in the
    window's ``__init__``. It is scoped to that widget tree, so it never leaks
    into the rest of the app, and only restyles colours/borders/fonts."""
    return _QSS
