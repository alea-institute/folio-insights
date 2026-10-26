"""Frozen semantic edges and deterministic maximum atomic one-to-one matching."""
from __future__ import annotations

import hashlib
import json
import unicodedata
from collections import deque
from typing import Literal

from pydantic import model_validator

from folio_insights.measurement.gold import PinnedOntology, ResolvedConcept
from folio_insights.measurement.schema import (
    GoldDocument, GoldProposition, GoldSuite, MeasurementModel, Nonempty, Sha256,
    TagSelection,
)


SOURCE_TYPE_LABELS = (
    "Judicial Opinion", "Brief / Memorandum of Law", "Statutes", "Regulations",
    "Law Review Article", "Jury Instructions",
)


class MatcherPolicy(MeasurementModel):
    version: Literal["atomic-one-to-one-v1"] = "atomic-one-to-one-v1"
    source_type_version: Literal["source-genre-v1"] = "source-genre-v1"
    source_type_labels: tuple[str, ...] = SOURCE_TYPE_LABELS

    @model_validator(mode="after")
    def check_policy(self) -> MatcherPolicy:
        if self.source_type_labels != SOURCE_TYPE_LABELS:
            raise ValueError("source-type policy changes require a new matcher version")
        return self

    def classify_tag(self, tag: ResolvedConcept, ontology: PinnedOntology) -> Literal[
        "meaning", "source-type"
    ]:
        # Classify resolved identity and ancestry, never a caller's branch label.
        # Document components and documents that express meaning (e.g. Evidence,
        # Notice, Noncompete Agreement) are deliberately not blanket-excluded.
        pending, visited = [tag.iri], set()
        while pending:
            iri = pending.pop()
            if iri in visited:
                continue
            visited.add(iri)
            concept = ontology.concepts[iri]
            if concept.label in self.source_type_labels:
                return "source-type"
            pending.extend(concept.parents)
        return "meaning"


MATCHER_POLICY = MatcherPolicy()


class Prediction(GoldProposition):
    tags: tuple[TagSelection, ...] = ()


class PredictionDocument(MeasurementModel):
    source_id: Nonempty
    source_sha256: Sha256
    propositions: tuple[Prediction, ...]
    coverage_complete: bool
    judgments_complete: bool

    @model_validator(mode="after")
    def unique_ids(self) -> PredictionDocument:
        ids = [p.item_id for p in self.propositions]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate prediction item ID; duplicate claims need distinct IDs")
        return self


class EquivalenceEdge(MeasurementModel):
    source_id: Nonempty
    prediction_id: Nonempty
    gold_id: Nonempty
    verdict: Literal["equivalent", "different", "uncertain"]
    author: Nonempty
    reason: Nonempty


class EquivalenceInputs(MeasurementModel):
    matcher_version: Literal["atomic-one-to-one-v1"]
    gold_sha256: Sha256
    predictions_sha256: Sha256
    edges: tuple[EquivalenceEdge, ...]


def content_digest(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def freeze_equivalences(
    suite: GoldSuite, predictions: tuple[PredictionDocument, ...],
    edges: tuple[EquivalenceEdge, ...] = (),
) -> EquivalenceInputs:
    """Pin edges to complete gold (including ontology) and prediction content."""
    rows = []
    for row in sorted(predictions, key=lambda r: r.source_id):
        data = row.model_dump(mode="json")
        data["propositions"] = sorted(data["propositions"], key=lambda p: p["item_id"])
        rows.append(data)
    known = {d.source.source_id: d for d in suite.documents}
    proposed = {r.source_id: r for r in predictions}
    seen = set()
    for edge in edges:
        key = (edge.source_id, edge.prediction_id, edge.gold_id)
        if key in seen:
            raise ValueError("duplicate equivalence edge")
        seen.add(key)
        if (edge.source_id not in known or edge.source_id not in proposed
                or edge.gold_id not in {p.item_id for p in known[edge.source_id].propositions}
                or edge.prediction_id not in {
                    p.item_id for p in proposed[edge.source_id].propositions}):
            raise ValueError("equivalence edge has unknown endpoint")
    return EquivalenceInputs(
        matcher_version=MATCHER_POLICY.version,
        gold_sha256=content_digest(suite.model_dump(mode="json")),
        predictions_sha256=content_digest(rows),
        edges=tuple(sorted(edges, key=lambda e: (e.source_id, e.prediction_id, e.gold_id))),
    )


class MatchPair(MeasurementModel):
    prediction_id: str
    gold_id: str


class MatchResult(MeasurementModel):
    pairs: tuple[MatchPair, ...]
    unmatched_predictions: tuple[str, ...]
    unmatched_gold: tuple[str, ...]
    invalid_grounding: tuple[str, ...]
    uncertain_edges: tuple[EquivalenceEdge, ...]


def match_document(
    gold: GoldDocument, predictions: PredictionDocument,
    equivalences: EquivalenceInputs | None = None,
) -> MatchResult:
    """Exact spans plus identical NFC atomic text/kind or authored semantic edges.

    Span equality alone never establishes atomic equivalence. Sorted augmenting
    paths give a maximum-cardinality match with stable tie breaking, independent
    of input order. Each prediction and gold item can receive credit once.
    """
    if (predictions.source_id != gold.source.source_id
            or predictions.source_sha256 != gold.source.sha256):
        raise ValueError("matching requires the same source snapshot")
    proposed = {p.item_id: p for p in predictions.propositions}
    expected = {p.item_id: p for p in gold.propositions}
    invalid = set()
    for p in proposed.values():
        try:
            p.span.source_slice(gold.source.text)
        except ValueError:
            invalid.add(p.item_id)
    edges = {(e.prediction_id, e.gold_id): e for e in (
        equivalences.edges if equivalences else ()) if e.source_id == gold.source.source_id}
    adjacency = {}
    for pid, pred in sorted(proposed.items()):
        adjacency[pid] = []
        if pid in invalid:
            continue
        for gid, item in sorted(expected.items()):
            edge = edges.get((pid, gid))
            exact = (pred.kind == item.kind and unicodedata.normalize("NFC", pred.text)
                     == unicodedata.normalize("NFC", item.text))
            if pred.span == item.span and (
                edge.verdict == "equivalent" if edge else exact
            ):
                adjacency[pid].append(gid)
    assigned: dict[str, str] = {}
    for start in adjacency:
        queue = deque([start])
        visited = {start}
        paths: dict[str, str] = {}
        free = None
        while queue and free is None:
            pid = queue.popleft()
            for gid in adjacency[pid]:
                if gid in paths:
                    continue
                paths[gid] = pid
                if gid not in assigned:
                    free = gid
                    break
                owner = assigned[gid]
                if owner not in visited:
                    visited.add(owner)
                    queue.append(owner)
        if free is not None:
            reverse = {pid: gid for gid, pid in assigned.items()}
            while free is not None:
                pid = paths[free]
                assigned[free] = pid
                free = reverse.get(pid)
    pairs = tuple(MatchPair(prediction_id=pid, gold_id=gid)
                  for gid, pid in sorted(assigned.items(), key=lambda pair: pair[1]))
    return MatchResult(
        pairs=pairs,
        unmatched_predictions=tuple(sorted(set(proposed) - set(assigned.values()))),
        unmatched_gold=tuple(sorted(set(expected) - set(assigned))),
        invalid_grounding=tuple(sorted(invalid)),
        uncertain_edges=tuple(e for _, e in sorted(edges.items()) if e.verdict == "uncertain"),
    )
