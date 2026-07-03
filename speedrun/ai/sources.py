"""Source ingestion -- everything the generator is allowed to draw on, each with
a stable ``source_id`` and a human ``citation`` so every downstream card can be
traced back to a NAMED SOURCE (a hard grading requirement).

Two ingestion paths:

1. Drop-folder ``speedrun/ai/sources/``: any ``*.json`` / ``*.txt`` / ``*.md``
   file becomes one or more source units. See ``sources/README.md`` for the
   format. This is the path the user uses to paste Khan Academy CARS passages
   and AAMC-style content (the Khan site is bot-blocked to automated fetches).

2. Best-effort auto-discovery of the user's Anki collection
   (``%APPDATA%/Anki2/<profile>/collection.anki2``), read READ-ONLY via
   sqlite3, producing units cited as "MCAT deck note <nid>". Wrapped in
   try/except and never required.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from . import config


@dataclass
class SourceUnit:
    """One citable unit of source material."""

    source_id: str
    citation: str
    text: str
    topic: str = "general"
    url: Optional[str] = None
    origin: str = "drop-folder"

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, object]) -> "SourceUnit":
        return SourceUnit(
            source_id=str(d.get("source_id") or d.get("id") or ""),
            citation=str(d.get("citation") or ""),
            text=str(d.get("text") or ""),
            topic=str(d.get("topic") or "general"),
            url=(str(d["url"]) if d.get("url") else None),
            origin=str(d.get("origin") or "drop-folder"),
        )


_PARAGRAPH_RE = re.compile(r"\n\s*\n")


def _units_from_json_file(path: Path) -> List[SourceUnit]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    stem = path.stem
    default_citation = str(path.name)

    # Normalize into a list of raw unit dicts + file-level citation/url.
    file_citation = default_citation
    file_url: Optional[str] = None
    raw_units: List[dict] = []

    if isinstance(data, dict) and "units" in data:
        file_citation = str(data.get("citation") or default_citation)
        file_url = (str(data["url"]) if data.get("url") else None)
        units = data.get("units")
        if isinstance(units, list):
            raw_units = [u for u in units if isinstance(u, dict)]
    elif isinstance(data, list):
        raw_units = [u for u in data if isinstance(u, dict)]
    elif isinstance(data, dict):
        raw_units = [data]

    out: List[SourceUnit] = []
    for i, u in enumerate(raw_units):
        text = str(u.get("text") or u.get("content") or "").strip()
        if not text:
            continue
        sid = str(u.get("source_id") or u.get("id") or "{}#{}".format(stem, i))
        citation = str(u.get("citation") or file_citation)
        url = (str(u["url"]) if u.get("url") else file_url)
        topic = str(u.get("topic") or "general")
        out.append(
            SourceUnit(
                source_id=sid,
                citation=citation,
                text=text,
                topic=topic,
                url=url,
                origin="drop-folder",
            )
        )
    return out


def _units_from_text_file(path: Path) -> List[SourceUnit]:
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        return []
    # Optional sidecar metadata: <name>.meta.json with {"citation":..,"url":..}.
    citation = str(path.name)
    url: Optional[str] = None
    sidecar = path.with_suffix(path.suffix + ".meta.json")
    if not sidecar.exists():
        sidecar = path.with_name(path.stem + ".meta.json")
    if sidecar.exists():
        try:
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
            citation = str(meta.get("citation") or citation)
            url = (str(meta["url"]) if meta.get("url") else None)
        except Exception:
            pass
    # A leading "URL: ..." line is also honored.
    lines = raw.splitlines()
    if lines and lines[0].lower().startswith("url:"):
        url = lines[0].split(":", 1)[1].strip() or url
        raw = "\n".join(lines[1:])

    paragraphs = [p.strip() for p in _PARAGRAPH_RE.split(raw) if p.strip()]
    out: List[SourceUnit] = []
    for i, para in enumerate(paragraphs):
        out.append(
            SourceUnit(
                source_id="{}#{}".format(path.stem, i),
                citation=citation,
                text=para,
                topic="general",
                url=url,
                origin="drop-folder",
            )
        )
    return out


def load_drop_folder(sources_dir: Optional[Path] = None) -> List[SourceUnit]:
    sources_dir = sources_dir or config.SOURCES_DIR
    units: List[SourceUnit] = []
    if not sources_dir.exists():
        return units
    for path in sorted(sources_dir.iterdir()):
        if not path.is_file():
            continue
        if path.name.endswith(".meta.json"):
            continue
        suffix = path.suffix.lower()
        if suffix == ".json":
            units.extend(_units_from_json_file(path))
        elif suffix in (".txt", ".md"):
            # Skip the human-facing README.
            if path.name.lower() == "readme.md":
                continue
            units.extend(_units_from_text_file(path))
    return units


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_FIELD_SEP = "\x1f"  # Anki stores note fields joined by the unit separator.


def _strip_html(text: str) -> str:
    return _HTML_TAG_RE.sub(" ", text).replace("&nbsp;", " ").strip()


def load_from_collection(limit: int = 25) -> List[SourceUnit]:
    """Best-effort READ-ONLY sample of note fields from the Anki collection.

    Never raises; returns [] on any problem. Opens the DB read-only (falls back
    to a temp copy) so we cannot disturb a running Anki.
    """
    units: List[SourceUnit] = []
    for col_path in config.anki_collection_candidates():
        try:
            units.extend(_read_collection_notes(col_path, limit=limit))
            if units:
                break
        except Exception:
            continue
    return units


def _read_collection_notes(col_path: Path, limit: int) -> List[SourceUnit]:
    conn: Optional[sqlite3.Connection] = None
    tmp_path: Optional[Path] = None
    try:
        try:
            uri = "file:{}?mode=ro".format(col_path.as_posix())
            conn = sqlite3.connect(uri, uri=True)
        except Exception:
            # Fall back to a temp copy (never touch the original).
            fd, tmp = tempfile.mkstemp(suffix=".anki2")
            import os

            os.close(fd)
            tmp_path = Path(tmp)
            shutil.copy2(col_path, tmp_path)
            conn = sqlite3.connect(str(tmp_path))
        cur = conn.cursor()
        cur.execute("SELECT id, flds FROM notes LIMIT ?", (int(limit),))
        rows = cur.fetchall()
        out: List[SourceUnit] = []
        for nid, flds in rows:
            fields = [_strip_html(f) for f in str(flds).split(_FIELD_SEP)]
            fields = [f for f in fields if f]
            if len(fields) < 2:
                continue
            text = "Q: {}  A: {}".format(fields[0], fields[1])
            out.append(
                SourceUnit(
                    source_id="anki-note-{}".format(nid),
                    citation="MCAT deck note {}".format(nid),
                    text=text,
                    topic="anki-collection",
                    url=None,
                    origin="anki-collection",
                )
            )
        return out
    finally:
        if conn is not None:
            conn.close()
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass


def load_sources(
    include_collection: bool = True, collection_limit: int = 25
) -> List[SourceUnit]:
    """All source units: drop-folder first (deterministic), then a best-effort
    collection sample appended (additive; never required)."""
    units = load_drop_folder()
    if include_collection:
        try:
            units.extend(load_from_collection(limit=collection_limit))
        except Exception:
            pass
    # De-duplicate by source_id, keeping the first occurrence.
    seen: Dict[str, SourceUnit] = {}
    for u in units:
        if u.source_id not in seen:
            seen[u.source_id] = u
    return list(seen.values())


def index_by_id(units: List[SourceUnit]) -> Dict[str, SourceUnit]:
    return {u.source_id: u for u in units}
