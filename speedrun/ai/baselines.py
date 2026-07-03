"""Simpler-method baselines, scored with the SAME checker as the AI generator so
the comparison is apples-to-apples (the grading rule "show your AI beats a
simpler method").

Two retrieval baselines, each "producing" a transfer question for a source by
retrieving the nearest EXISTING question from a fixed bank:

* keyword / TF-IDF cosine retrieval  (scikit-learn if installed, else pure-python)
* vector / embedding retrieval        (sentence-transformers if installed, else a
                                        documented hashing-embedding proxy)

A retrieval baseline can only ever return questions that already exist, so it
cannot ground to an arbitrary new source as tightly as generation can, and it
tends to restate questions the student has already seen -- exactly what the
checker's grounding and transfer tests catch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import checker
from . import config
from . import textsim
from .items import BankItem, GeneratedItem, GoldItem, load_bank, load_generated, load_gold
from .sources import SourceUnit, index_by_id, load_sources


@dataclass
class MethodMetrics:
    method: str
    n: int
    pass_rate: float
    grounded_rate: float
    transfer_ok_rate: float
    wellformed_rate: float
    wrong_fact_rate: float
    mean_grounding: float
    mean_transfer_sim: float

    def to_dict(self) -> Dict[str, object]:
        return {
            "method": self.method,
            "n": self.n,
            "pass_rate": round(self.pass_rate, 3),
            "grounded_rate": round(self.grounded_rate, 3),
            "transfer_ok_rate": round(self.transfer_ok_rate, 3),
            "wellformed_rate": round(self.wellformed_rate, 3),
            "wrong_fact_rate": round(self.wrong_fact_rate, 3),
            "mean_grounding": round(self.mean_grounding, 3),
            "mean_transfer_sim": round(self.mean_transfer_sim, 3),
        }


def _bank_doc(b: BankItem) -> str:
    return b.stem + " " + " ".join(b.choices)


def _bank_to_generated(b: BankItem, unit: SourceUnit, method: str) -> GeneratedItem:
    """Wrap a retrieved bank MCQ as a card claiming to be grounded in `unit`.

    A retrieval baseline supplies no rationale of its own, which is an inherent
    (and honest) limitation vs. a generator that explains its answer.
    """
    return GeneratedItem(
        id="{}-{}".format(method, unit.source_id),
        stem=b.stem,
        choices=list(b.choices),
        answer_index=b.answer_index,
        rationale="",
        source_id=unit.source_id,
        citation=unit.citation,
        transfer_tags=["retrieved-existing"],
        origin=method,
    )


def _retrieve(units: List[SourceUnit], bank: List[BankItem], method: str) -> List[GeneratedItem]:
    if not units or not bank:
        return []
    queries = [u.text for u in units]
    corpus = [_bank_doc(b) for b in bank]
    if method == "baseline-tfidf":
        sim = textsim.tfidf_cross_similarity(queries, corpus)
    else:
        sim = textsim.vector_cross_similarity(queries, corpus)
    out: List[GeneratedItem] = []
    for i, unit in enumerate(units):
        row = sim[i]
        best_j = max(range(len(row)), key=lambda j: row[j]) if row else 0
        out.append(_bank_to_generated(bank[best_j], unit, method))
    return out


def compute_metrics(
    method: str,
    items: List[GeneratedItem],
    sources_by_id: Dict[str, SourceUnit],
    gold: List[GoldItem],
) -> MethodMetrics:
    results = checker.check_all(items, sources_by_id, gold)
    gold_by_source: Dict[str, List[GoldItem]] = {}
    for g in gold:
        gold_by_source.setdefault(g.source_id, []).append(g)

    n = len(results)
    if n == 0:
        return MethodMetrics(method, 0, 0, 0, 0, 0, 0, 0, 0)

    passed = sum(1 for r in results if r.passed)
    grounded = sum(1 for r in results if r.grounded)
    transfer_ok = sum(1 for r in results if r.is_transfer)
    wellformed = sum(1 for r in results if r.wellformed)
    wrong = sum(
        1
        for it in items
        if checker.answer_key_verdict(it, gold_by_source.get(it.source_id, [])) == "wrong"
    )
    mean_g = sum(r.grounding_score for r in results) / n
    mean_t = sum(r.transfer_sim for r in results) / n
    return MethodMetrics(
        method=method,
        n=n,
        pass_rate=passed / n,
        grounded_rate=grounded / n,
        transfer_ok_rate=transfer_ok / n,
        wellformed_rate=wellformed / n,
        wrong_fact_rate=wrong / n,
        mean_grounding=mean_g,
        mean_transfer_sim=mean_t,
    )


@dataclass
class BaselineComparison:
    metrics: List[MethodMetrics] = field(default_factory=list)
    backends: Dict[str, str] = field(default_factory=dict)
    ai_beats: Dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return {
            "metrics": [m.to_dict() for m in self.metrics],
            "backends": dict(self.backends),
            "ai_beats_baselines_on_pass_rate": self.ai_beats,
        }


def run_baselines() -> BaselineComparison:
    units = load_sources()
    sources_by_id = index_by_id(units)
    gold = load_gold()
    bank = load_bank()
    ai_items = load_generated()

    ai_metrics = compute_metrics("ai-claude", ai_items, sources_by_id, gold)
    tfidf_items = _retrieve(units, bank, "baseline-tfidf")
    vec_items = _retrieve(units, bank, "baseline-vector")
    tfidf_metrics = compute_metrics("baseline-tfidf", tfidf_items, sources_by_id, gold)
    vec_metrics = compute_metrics("baseline-vector", vec_items, sources_by_id, gold)

    ai_beats = {
        "baseline-tfidf": ai_metrics.pass_rate > tfidf_metrics.pass_rate,
        "baseline-vector": ai_metrics.pass_rate > vec_metrics.pass_rate,
    }
    return BaselineComparison(
        metrics=[ai_metrics, tfidf_metrics, vec_metrics],
        backends=dict(textsim.BACKENDS),
        ai_beats=ai_beats,
    )
