"""Exhaustive source/genre score matrices, with explicit readiness and provenance."""
from __future__ import annotations

from math import sqrt
from typing import Literal

from pydantic import Field, computed_field, model_validator

from folio_insights.measurement.gold import GoldSetError, PinnedOntology, validate_gold
from folio_insights.measurement.matching import (
    MATCHER_POLICY, EquivalenceInputs, MatcherPolicy, PredictionDocument,
    content_digest, freeze_equivalences, match_document,
)
from folio_insights.measurement.schema import (
    Genre, GoldSuite, MeasurementModel, Nonempty, TagSelection,
)

SCORER_VERSION = "exhaustive-counts-v1"


class Counts(MeasurementModel):
    tp: int = Field(default=0, ge=0)
    fp: int = Field(default=0, ge=0)
    fn: int = Field(default=0, ge=0)
    evaluated: bool = True

    @computed_field
    @property
    def precision_denominator(self) -> int:
        return self.tp + self.fp

    @computed_field
    @property
    def recall_denominator(self) -> int:
        return self.tp + self.fn

    @computed_field
    @property
    def precision(self) -> float | None:
        return self.tp / self.precision_denominator if (
            self.evaluated and self.precision_denominator) else None

    @computed_field
    @property
    def recall(self) -> float | None:
        return self.tp / self.recall_denominator if (
            self.evaluated and self.recall_denominator) else None

    def _interval(self, denominator: int) -> tuple[float, float] | None:
        """Wilson 95% interval, a sampling diagnostic rather than a gate axis."""
        if not self.evaluated or not denominator:
            return None
        z = 1.959963984540054
        rate = self.tp / denominator
        scale = 1 + z * z / denominator
        center = (rate + z * z / (2 * denominator)) / scale
        margin = z * sqrt(rate * (1 - rate) / denominator
                          + z * z / (4 * denominator * denominator)) / scale
        return max(0, center - margin), min(1, center + margin)

    @computed_field
    @property
    def precision_interval(self) -> tuple[float, float] | None:
        return self._interval(self.precision_denominator)

    @computed_field
    @property
    def recall_interval(self) -> tuple[float, float] | None:
        return self._interval(self.recall_denominator)

    def __add__(self, other: Counts) -> Counts:
        return Counts(tp=self.tp + other.tp, fp=self.fp + other.fp, fn=self.fn + other.fn,
                      evaluated=self.evaluated and other.evaluated)


def _counts(expected: set, proposed: set) -> Counts:
    return Counts(tp=len(expected & proposed), fp=len(proposed - expected),
                  fn=len(expected - proposed))


class HumanAnchor(MeasurementModel):
    genre: Genre
    verified_by: Literal["Damien Riehl"]
    annotation_id: Nonempty
    verified_at: Nonempty


class TagDecision(MeasurementModel):
    tag: TagSelection
    accepted: bool
    author: Nonempty
    reason: Nonempty


class TagPool(MeasurementModel):
    source_id: Nonempty
    gold_id: Nonempty
    decisions: tuple[TagDecision, ...]


class PoolAudit(MeasurementModel):
    genre: Genre
    sampled_tags: int = Field(ge=0)
    missing_tags: int = Field(ge=0)
    uncorrected_missing_tags: int = Field(ge=0)

    @model_validator(mode="after")
    def check_counts(self) -> PoolAudit:
        if not self.uncorrected_missing_tags <= self.missing_tags <= self.sampled_tags:
            raise ValueError("pool-miss counts must fit the sample denominator")
        return self


class PendingTag(MeasurementModel):
    source_id: str
    prediction_id: str
    gold_id: str
    tag_iri: str


class Diagnostics(MeasurementModel):
    source_types: Counts = Counts()
    branches: Counts = Counts()
    links: Counts = Counts()
    invalid_grounding: tuple[str, ...] = ()
    unresolved_tags: tuple[str, ...] = ()


class ScoreRow(MeasurementModel):
    propositions: Counts
    tags: Counts
    diagnostics: Diagnostics
    readiness: Literal["ready", "incomplete"]
    reasons: tuple[str, ...] = ()
    label: Literal["judge agreement, unanchored", "human-anchored"]
    pool_sampled_tags: int = 0
    pool_missing_tags: int = 0
    pool_uncorrected_missing_tags: int = 0

    @computed_field
    @property
    def pool_miss_rate(self) -> float | None:
        return self.pool_missing_tags / self.pool_sampled_tags if self.pool_sampled_tags else None

    @computed_field
    @property
    def tag_recall_label(self) -> Literal["pool-limited"] | None:
        if (self.pool_sampled_tags and
                self.pool_uncorrected_missing_tags / self.pool_sampled_tags > .05):
            return "pool-limited"
        return None

    @computed_field
    @property
    def target_met(self) -> bool | None:
        if self.readiness != "ready":
            return None
        values = (self.propositions.precision, self.propositions.recall,
                  self.tags.precision, self.tags.recall)
        targets = (.95, .90, .95, .90)
        if any(v is not None and v < t for v, t in zip(values, targets, strict=True)):
            return False
        return True if all(v is not None for v in values) else None


class ScoreMatrix(MeasurementModel):
    scorer_version: Literal["exhaustive-counts-v1"] = SCORER_VERSION
    matcher_policy: MatcherPolicy = MATCHER_POLICY
    gold_revision: str
    gold_sha256: str
    predictions_sha256: str
    equivalences_sha256: str
    tag_pools_sha256: str
    pool_audits_sha256: str
    ontology_sha256: str
    ontology_slice_sha256: str
    sources: dict[str, ScoreRow]
    genres: dict[str, ScoreRow]
    micro: ScoreRow
    pending_tags: tuple[PendingTag, ...]
    anchors: tuple[HumanAnchor, ...]

    @computed_field
    @property
    def readiness(self) -> Literal["ready", "incomplete"]:
        return self.micro.readiness

    @computed_field
    @property
    def reasons(self) -> tuple[str, ...]:
        return self.micro.reasons


def _aggregate(rows: list[ScoreRow], *, audit: PoolAudit | None = None) -> ScoreRow:
    def total(axis: str, diagnostic: bool = False) -> Counts:
        return sum((getattr(r.diagnostics if diagnostic else r, axis) for r in rows), Counts())
    return ScoreRow(
        propositions=total("propositions"), tags=total("tags"),
        diagnostics=Diagnostics(
            source_types=total("source_types", True), branches=total("branches", True),
            links=total("links", True),
            invalid_grounding=tuple(i for r in rows for i in r.diagnostics.invalid_grounding),
            unresolved_tags=tuple(i for r in rows for i in r.diagnostics.unresolved_tags)),
        readiness="ready" if all(r.readiness == "ready" for r in rows) else "incomplete",
        reasons=tuple(reason for r in rows for reason in r.reasons),
        label="human-anchored" if all(r.label == "human-anchored" for r in rows)
              else "judge agreement, unanchored",
        pool_sampled_tags=audit.sampled_tags if audit else sum(r.pool_sampled_tags for r in rows),
        pool_missing_tags=audit.missing_tags if audit else sum(r.pool_missing_tags for r in rows),
        pool_uncorrected_missing_tags=(audit.uncorrected_missing_tags if audit else
                                      sum(r.pool_uncorrected_missing_tags for r in rows)),
    )


def score_suite(
    suite: GoldSuite, predictions: tuple[PredictionDocument, ...], *,
    ontology: PinnedOntology, equivalences: EquivalenceInputs | None = None,
    tag_pools: tuple[TagPool, ...] = (), pool_audits: tuple[PoolAudit, ...] = (),
    anchors: tuple[HumanAnchor, ...] = (),
) -> ScoreMatrix:
    """Score every gold document, retaining incomplete rows and all denominators.

    Gold tags form the initial adjudicated pool. Explicit pools may add authored
    accept/reject decisions; an accepted addition also increases exhaustive gold.
    New matched-proposition selections wait for adjudication, rather than becoming
    automatic false positives. Unmatched predictions' resolved tags are FPs.
    """
    validate_gold(suite, ontology)
    frozen = freeze_equivalences(suite, predictions, equivalences.edges if equivalences else ())
    if equivalences is not None and equivalences != frozen:
        raise ValueError("stale or incompatible equivalence inputs")
    supplied = {r.source_id: r for r in predictions}
    documents = {d.source.source_id: d for d in suite.documents}
    if len(supplied) != len(predictions) or set(supplied) - set(documents):
        raise ValueError("duplicate or unknown prediction source")
    pools = {(p.source_id, p.gold_id): p for p in tag_pools}
    if len(pools) != len(tag_pools):
        raise ValueError("duplicate tag pool")
    for sid, gid in pools:
        if sid not in documents or gid not in {p.item_id for p in documents[sid].propositions}:
            raise ValueError("unknown tag pool proposition")
    audits = {a.genre: a for a in pool_audits}
    if len(audits) != len(pool_audits) or set(audits) - {d.source.genre for d in suite.documents}:
        raise ValueError("duplicate or unknown pool audit genre")
    anchored = {a.genre for a in anchors}
    sources, pending = {}, []
    for sid, doc in sorted(documents.items()):
        reasons, unresolved = [], []
        def resolve(tags: tuple[TagSelection, ...], item_id: str) -> dict:
            resolved = {}
            for tag in tags:
                try:
                    identity = ontology.resolve(tag.label, tag.branch)
                except GoldSetError:
                    unresolved.append(f"{sid}/{item_id}: {tag.label}")
                    continue
                resolved[identity.iri] = identity
            return resolved

        expected = {p.item_id: resolve(p.tags, p.item_id) for p in doc.propositions}
        decisions = {}
        for gid, tags in expected.items():
            decisions[gid] = {iri: True for iri in tags}
            pool = pools.get((sid, gid))
            if pool is None:
                continue
            for decision in pool.decisions:
                identity = ontology.resolve(decision.tag.label, decision.tag.branch)
                previous = decisions[gid].get(identity.iri)
                if previous is not None and previous != decision.accepted:
                    raise ValueError("pool decision conflicts with accepted gold tag")
                decisions[gid][identity.iri] = decision.accepted
                if decision.accepted:
                    tags[identity.iri] = identity
        row = supplied.get(sid)
        usable = row is not None and row.source_sha256 == doc.source.sha256
        if not usable:
            reasons.append(f"{sid}: missing source" if row is None else f"{sid}: source digest mismatch")
            row = PredictionDocument(source_id=sid, source_sha256=doc.source.sha256,
                                     propositions=(), coverage_complete=False,
                                     judgments_complete=False)
        if not row.coverage_complete:
            reasons.append(f"{sid}: source coverage incomplete")
        if not row.judgments_complete:
            reasons.append(f"{sid}: judgments incomplete")
        matches = match_document(doc, row, frozen)
        if matches.uncertain_edges:
            reasons.append(f"{sid}: uncertain alignments require adjudication")
        proposed = {p.item_id: resolve(p.tags, p.item_id) for p in row.propositions}
        pairs = {p.prediction_id: p.gold_id for p in matches.pairs}
        tag_counts, source_counts, branch_counts = Counts(), Counts(), Counts()
        def category(tags: dict, name: str) -> set[str]:
            return {iri for iri, tag in tags.items()
                    if MATCHER_POLICY.classify_tag(tag, ontology) == name}

        for pid, gid in pairs.items():
            actual, gold = proposed[pid], expected[gid]
            known = {iri: tag for iri, tag in actual.items() if iri in decisions[gid]}
            for iri in sorted(set(actual) - set(known)):
                pending.append(PendingTag(source_id=sid, prediction_id=pid,
                                          gold_id=gid, tag_iri=iri))
            tag_counts += _counts(category(gold, "meaning"), category(known, "meaning"))
            source_counts += _counts(category(gold, "source-type"), category(known, "source-type"))
            branch_counts += _counts({t.branch_iri for t in gold.values()},
                                     {t.branch_iri for t in actual.values()})
        for pid in matches.unmatched_predictions:
            tag_counts += Counts(fp=len(category(proposed[pid], "meaning")))
            source_counts += Counts(fp=len(category(proposed[pid], "source-type")))
            branch_counts += Counts(fp=len({t.branch_iri for t in proposed[pid].values()}))
        for gid in matches.unmatched_gold:
            tag_counts += Counts(fn=len(category(expected[gid], "meaning")))
            source_counts += Counts(fn=len(category(expected[gid], "source-type")))
            branch_counts += Counts(fn=len({t.branch_iri for t in expected[gid].values()}))
        if any(p.source_id == sid for p in pending):
            reasons.append(f"{sid}: outside-pool tags require adjudication")
        if unresolved:
            reasons.append(f"{sid}: unresolved tag selections")
        expected_links = {(p.item_id, link.relation, link.target_id)
                          for p in doc.propositions for link in p.links}
        # Namespace unmatched endpoints so local prediction IDs cannot accidentally
        # earn gold link credit merely because their strings happen to coincide.
        actual_links = {(pairs.get(p.item_id, ("unmatched", p.item_id)), link.relation,
                         pairs.get(link.target_id, ("unmatched", link.target_id)))
                        for p in row.propositions for link in p.links}
        evaluated = usable and row.coverage_complete and row.judgments_complete
        def coverage(count: Counts) -> Counts:
            return count.model_copy(update={"evaluated": evaluated})
        sources[sid] = ScoreRow(
            propositions=coverage(Counts(tp=len(pairs), fp=len(matches.unmatched_predictions),
                                        fn=len(matches.unmatched_gold))),
            tags=coverage(tag_counts), diagnostics=Diagnostics(
                source_types=coverage(source_counts), branches=coverage(branch_counts),
                links=coverage(_counts(expected_links, actual_links)),
                invalid_grounding=matches.invalid_grounding,
                unresolved_tags=tuple(unresolved)),
            readiness="incomplete" if reasons else "ready", reasons=tuple(reasons),
            label="human-anchored" if doc.source.genre in anchored
                  else "judge agreement, unanchored",
        )
    genres = {genre: _aggregate([sources[sid] for sid, doc in documents.items()
                                if doc.source.genre == genre], audit=audits.get(genre))
              for genre in sorted({d.source.genre for d in suite.documents})}
    return ScoreMatrix(
        gold_revision=suite.gold_revision, gold_sha256=frozen.gold_sha256,
        predictions_sha256=frozen.predictions_sha256,
        equivalences_sha256=content_digest(frozen.model_dump(mode="json")),
        tag_pools_sha256=content_digest([p.model_dump(mode="json") for p in sorted(
            tag_pools, key=lambda p: (p.source_id, p.gold_id))]),
        pool_audits_sha256=content_digest([a.model_dump(mode="json") for a in sorted(
            pool_audits, key=lambda a: a.genre)]),
        ontology_sha256=suite.ontology_sha256,
        ontology_slice_sha256=suite.ontology_slice_sha256, sources=sources, genres=genres,
        micro=_aggregate(list(genres.values())),
        pending_tags=tuple(pending), anchors=anchors,
    )
