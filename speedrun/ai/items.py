"""Shared data types + JSON loaders for gold items, generated cards, and the
baseline question bank. Kept separate so every step (generate/check/eval/
baselines/leakage/paraphrase) reads the same schema."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config


@dataclass
class GoldItem:
    id: str
    topic: str
    question: str
    answer: str
    source_id: str
    citation: str

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "GoldItem":
        return GoldItem(
            id=str(d.get("id") or ""),
            topic=str(d.get("topic") or "general"),
            question=str(d.get("question") or ""),
            answer=str(d.get("answer") or ""),
            source_id=str(d.get("source_id") or ""),
            citation=str(d.get("citation") or ""),
        )


@dataclass
class GeneratedItem:
    """A transfer-question MCQ produced by the AI (or a baseline)."""

    id: str
    stem: str
    choices: List[str]
    answer_index: int
    rationale: str
    source_id: str
    citation: str
    transfer_tags: List[str] = field(default_factory=list)
    origin: str = "claude"

    @property
    def correct_choice(self) -> str:
        if 0 <= self.answer_index < len(self.choices):
            return self.choices[self.answer_index]
        return ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any], default_id: str = "") -> "GeneratedItem":
        choices = d.get("choices") or []
        if not isinstance(choices, list):
            choices = []
        try:
            ans = int(d.get("answer_index", -1))
        except (TypeError, ValueError):
            ans = -1
        tags = d.get("transfer_tags") or []
        if not isinstance(tags, list):
            tags = []
        return GeneratedItem(
            id=str(d.get("id") or default_id),
            stem=str(d.get("stem") or ""),
            choices=[str(c) for c in choices],
            answer_index=ans,
            rationale=str(d.get("rationale") or ""),
            source_id=str(d.get("source_id") or ""),
            citation=str(d.get("citation") or ""),
            transfer_tags=[str(t) for t in tags],
            origin=str(d.get("origin") or "claude"),
        )


@dataclass
class BankItem:
    """A pre-existing exam-style MCQ used by the retrieval baselines."""

    id: str
    stem: str
    choices: List[str]
    answer_index: int
    topic: str
    citation: str

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "BankItem":
        choices = d.get("choices") or []
        try:
            ans = int(d.get("answer_index", 0))
        except (TypeError, ValueError):
            ans = 0
        return BankItem(
            id=str(d.get("id") or ""),
            stem=str(d.get("stem") or ""),
            choices=[str(c) for c in choices],
            answer_index=ans,
            topic=str(d.get("topic") or "general"),
            citation=str(d.get("citation") or ""),
        )


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _items_list(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return [i for i in items if isinstance(i, dict)]
        return []
    if isinstance(data, list):
        return [i for i in data if isinstance(i, dict)]
    return []


def load_gold(path: Optional[Path] = None) -> List[GoldItem]:
    path = path or config.GOLD_SET_PATH
    data = _read_json(path)
    return [GoldItem.from_dict(d) for d in _items_list(data)]


def is_sample_generated(path: Optional[Path] = None) -> bool:
    path = path or config.GENERATED_PATH
    if not path.exists():
        return False
    try:
        data = _read_json(path)
    except Exception:
        return False
    return bool(isinstance(data, dict) and data.get("_sample"))


def load_generated(path: Optional[Path] = None) -> List[GeneratedItem]:
    path = path or config.GENERATED_PATH
    if not path.exists():
        return []
    data = _read_json(path)
    out: List[GeneratedItem] = []
    for i, d in enumerate(_items_list(data)):
        out.append(GeneratedItem.from_dict(d, default_id="gen{:03d}".format(i)))
    return out


def load_bank(path: Optional[Path] = None) -> List[BankItem]:
    path = path or config.QUESTION_BANK_PATH
    if not path.exists():
        return []
    data = _read_json(path)
    return [BankItem.from_dict(d) for d in _items_list(data)]


def write_generated(items: List[GeneratedItem], sample: bool, meta: Dict[str, Any],
                    path: Optional[Path] = None) -> None:
    path = path or config.GENERATED_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: Dict[str, Any] = {"_sample": sample}
    payload.update(meta)
    payload["items"] = [it.to_dict() for it in items]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
