"""Checkpointed measurement of frozen extraction outputs, without a BYOK job.

Extractors receive source snapshots only. The host must enforce the separate
candidate/evaluator workspace boundary; a Python protocol is not an isolation wall.
Current-pipeline extraction.json files are adapted without running the pipeline's
API-backed LLM stages. A completed empty file is a real miss, not missing coverage.
"""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Protocol

from folio_insights.measurement.annotations import AnnotationAuthor, AnnotationInput, AnnotationStore
from folio_insights.measurement.gold import PinnedOntology, validate_gold
from folio_insights.measurement.judge_prompts import INSTRUCTIONS, PROMPT_VERSION
from folio_insights.measurement.judges import (
    ConceptCandidate, JudgeItem, JudgePacket, JudgePort,
    JudgeSpan, adjudication_items, claude_sample,
)
from folio_insights.measurement.matching import (
    MATCHER_POLICY, EquivalenceInputs, Prediction, PredictionDocument, content_digest,
    freeze_equivalences,
)
from folio_insights.measurement.schema import EvaluationInputs, GoldSuite, SourceSnapshot, TagSelection
from folio_insights.measurement.scoring import SCORER_VERSION, score_suite
from folio_insights.measurement.store import RunReport, RunStore
from folio_insights.models.knowledge_unit import KnowledgeUnit

RUN_VERSION = "checkpointed-measurement-v1"


def judge_template_sha256() -> str:
    """Pin instructions and the closed schema independently of individual batches."""
    return content_digest({"version": PROMPT_VERSION, "instructions": INSTRUCTIONS,
                           "schema": json.loads(Path(__file__).with_name("judge.schema.json").read_text())})


class ExtractionPort(Protocol):
    @property
    def sha256(self) -> str: ...

    async def extract(self, source: SourceSnapshot) -> PredictionDocument: ...


class PipelineExtraction:
    """An explicit source-ID → completed single-source pipeline output manifest.

    Read bytes once when starting a run, so changes during extraction cannot sneak
    past the run fingerprint. A subsequent invocation observes changed files.
    """
    def __init__(self, paths: dict[str, Path]) -> None:
        self.paths = {sid: Path(path) for sid, path in paths.items()}
        self._payloads: dict[str, bytes] = {}

    @property
    def sha256(self) -> str:
        self._payloads = {sid: path.read_bytes() for sid, path in self.paths.items()}
        return content_digest({sid: hashlib.sha256(data).hexdigest()
                               for sid, data in self._payloads.items()})

    async def extract(self, source: SourceSnapshot) -> PredictionDocument:
        if source.source_id not in self._payloads:
            raise ValueError("source extraction unavailable")
        data = json.loads(self._payloads[source.source_id])
        if not isinstance(data, dict) or not isinstance(data.get("units"), list):
            raise ValueError("not a completed pipeline extraction")
        if data.get("coverage_complete", True) is not True:
            raise ValueError("pipeline extraction coverage incomplete")
        units = [KnowledgeUnit.model_validate(u) for u in data["units"]]
        if len({u.source_file for u in units}) > 1:
            raise ValueError("manifest entries must be single-source extractions")
        kinds = {"advice": "advice", "principle": "rule", "citation": "citation",
                 "procedural_rule": "rule", "pitfall": "advice"}
        predictions = []
        for unit in units:
            span = unit.original_span
            if (span.source_file != unit.source_file or not 0 <= span.start < span.end <= len(source.text)
                    or unit.source_snippet != source.text[span.start:span.end]):
                raise ValueError("pipeline extraction is not grounded in source snapshot")
            if unit.provenance and (unit.provenance.source_snapshot_id != source.source_id
                                    or unit.provenance.source_sha256 != source.sha256):
                raise ValueError("pipeline provenance differs from source snapshot")
            predictions.append(Prediction(
                item_id=unit.id, kind=unit.proposition_kind or kinds[unit.unit_type.value],
                text=unit.text, span={"start": span.start, "end": span.end},
                tags=tuple(TagSelection(label=t.label, branch=t.branch) for t in unit.folio_tags),
                links=tuple(link.model_dump() for link in unit.links)))
        return PredictionDocument(source_id=source.source_id, source_sha256=source.sha256,
                                  propositions=tuple(predictions), coverage_complete=True,
                                  judgments_complete=False)


def _item_id(*parts: str) -> str:
    return content_digest(parts)


def build_packet(suite: GoldSuite, predictions: tuple[PredictionDocument, ...],
                 ontology: PinnedOntology) -> JudgePacket:
    # The catalog includes the whole pinned slice, not just expected/proposed tags;
    # missing-tag review can therefore name selections outside the existing pool.
    selections = {(tag.label, tag.branch) for doc in suite.documents for prop in doc.propositions
                  for tag in prop.tags}
    selections.update((tag.label, tag.branch) for doc in predictions for prop in doc.propositions
                      for tag in prop.tags)
    selections.update((c.label, c.label) for c in ontology.concepts.values())
    catalog = tuple(ConceptCandidate(concept_id=_item_id(label, branch), label=label, branch=branch)
                    for label, branch in sorted(selections))
    items, context = [], []
    def add(source, prop, kind):
        concepts = tuple(dict.fromkeys(_item_id(t.label, t.branch) for t in prop.tags))
        item = JudgeItem(item_id=_item_id(source.source_id, kind, prop.item_id),
                         source_id=source.source_id, kind=kind, proposition_id=prop.item_id,
                         text=prop.text, span=JudgeSpan(**prop.span.model_dump()), concept_ids=concepts)
        items.append(item)
        if kind == "prediction":
            context.append(item)
        for concept in concepts:
            items.append(item.model_copy(update={"kind": "tag", "concept_ids": (concept,),
                         "item_id": _item_id(source.source_id, kind, prop.item_id, concept)}))
    sources = {doc.source.source_id: doc.source for doc in suite.documents}
    for doc in predictions:
        for prop in doc.propositions:
            add(sources[doc.source_id], prop, "prediction")
    for doc in suite.documents:
        for prop in doc.propositions:
            add(doc.source, prop, "gold")
        items.append(JudgeItem(
            item_id=_item_id(doc.source.source_id, "omission"), source_id=doc.source.source_id,
            kind="omission", proposition_id="source-coverage",
            text="Review the entire source for propositions or tags omitted from the candidate output.",
            span=JudgeSpan(start=0, end=len(doc.source.text))))
    return JudgePacket(sources=tuple(sources.values()), items=tuple(items),
                       predictions=tuple(context), catalog=catalog)


class MeasurementCoordinator:
    def __init__(self, store: RunStore, annotations: AnnotationStore, *, batch_size: int = 20):
        if batch_size <= 0:
            raise ValueError("batch size must be positive")
        self.store, self.annotations, self.batch_size = store, annotations, batch_size

    async def run(self, suite: GoldSuite, inputs: EvaluationInputs, *, extractor: ExtractionPort,
                  ontology: PinnedOntology, codex: JudgePort, claude: JudgePort,
                  split_id: str | None = None, cancelled: threading.Event | None = None,
                  equivalences: EquivalenceInputs | None = None) -> RunReport:
        validate_gold(suite, ontology)
        if (inputs.gold_sha256 != content_digest(suite.model_dump(mode="json"))
                or inputs.gold_revision != suite.gold_revision
                or inputs.source_snapshots != {d.source.source_id: d.source.sha256 for d in suite.documents}
                or inputs.ontology_sha256 != suite.ontology_sha256
                or inputs.scorer_version != SCORER_VERSION or inputs.matcher_version != MATCHER_POLICY.version
                or inputs.judge_prompt_sha256 != {p: judge_template_sha256() for p in ("codex", "claude")}
                or set(inputs.judge_identities) != {"codex", "claude"}):
            raise ValueError("evaluation pins differ from measurement inputs")
        if any(d.source.partition in {"held-out", "retired"} for d in suite.documents) and not split_id:
            raise ValueError("held-out and retired runs require a split ID")
        bindings = {"version": RUN_VERSION, "inputs": inputs.model_dump(mode="json"),
                    "extraction_sha256": extractor.sha256, "split_id": split_id,
                    "equivalences": equivalences.model_dump(mode="json") if equivalences else None}
        run_id = content_digest(bindings)
        with self.store.lock(run_id):
            report = self.store.load(run_id)
            if report is None:
                report = self.store.save(RunReport(run_id=run_id, inputs=inputs, artifacts={
                    "bindings": self.store.put(bindings),
                    "gold": self.store.put(suite.model_dump(mode="json"))}))
            report = self.store.save(report.model_copy(update={"status": "running", "errors": {}}))
            try:
                return await self._resume(report, suite, ontology, extractor, codex, claude,
                                          split_id, cancelled, equivalences)
            except (KeyboardInterrupt, InterruptedError):
                # Fetch the most recent item checkpoint, not a stale local snapshot.
                report = self.store.load(run_id)
                return self.store.save(report.model_copy(update={"status": "incomplete",
                                                               "errors": {"run": "cancelled"}}))

    async def _annotate(self, report, packet, provider, split_id):
        sources = {s.source_id: s for s in packet.sources}
        items = {i.item_id: i for i in packet.items}
        identity = report.inputs.judge_identities[provider]
        author = AnnotationAuthor(kind="judge", identity=f"{provider}/{identity.model}/{identity.cli_version}")
        for judgment in self.store.judgments(report.run_id, provider):
            revision = content_digest(judgment.model_dump(mode="json"))
            key = _item_id(provider, judgment.item_id, revision)
            if key in report.annotation_links:
                continue
            item = items[judgment.item_id]
            source = sources[item.source_id]
            annotation = await self.annotations.append(AnnotationInput(
                idempotency_key=_item_id(report.run_id, provider, item.item_id, revision),
                source_id=source.source_id, source_sha256=source.sha256, genre=source.genre,
                run_id=report.run_id, item_id=item.item_id,
                tag_id=item.concept_ids[0] if item.kind == "tag" else None,
                partition=source.partition, split_id=split_id, action="judge-verdict",
                verdict=judgment.verdict, reason=judgment.reason,
                span_start=item.span.start, span_end=item.span.end), author=author)
            if annotation.annotation_id not in report.annotation_ids:
                report = self.store.save(report.model_copy(update={
                    "annotation_ids": (*report.annotation_ids, annotation.annotation_id),
                    "annotation_links": {**report.annotation_links, key: annotation.annotation_id}}))
        return report

    async def _judge(self, report, packet, provider, judge, split_id, cancelled):
        report = self.store.save(report.model_copy(update={"stage": provider}))
        report = await self._annotate(report, packet, provider, split_id)
        done = set()
        last = None
        known = {i.item_id for i in packet.items}
        for attempt in self.store.results(report.run_id, provider=provider):
            ids = {j.item_id for j in attempt.judgments} | set(attempt.missing_item_ids)
            successful = (attempt.status == "complete" and not attempt.error
                          and not attempt.missing_item_ids and not attempt.unresolved_concept_ids
                          and attempt.identity == report.inputs.judge_identities[provider]
                          and len(ids) == len(attempt.judgments)
                          and ids <= known
                          and attempt.input_sha256 == packet.select(tuple(ids)).sha256)
            if successful:
                done.update(ids)
            else:
                done.difference_update(ids)
            last = attempt
        done.intersection_update(j.item_id for j in self.store.judgments(report.run_id, provider))
        missing = tuple(i.item_id for i in packet.items if i.item_id not in done)
        batches = [missing[n:n + self.batch_size] for n in range(0, len(missing), self.batch_size)]
        if not batches and (last is None or last.status != "complete" or last.error
                            or last.unresolved_concept_ids or last.provider != provider
                            or last.identity != report.inputs.judge_identities[provider]):
            batches = [()]
        for ids in batches:
            if cancelled and cancelled.is_set():
                raise InterruptedError
            selected = packet.select(ids)
            result = judge.judge(selected, cancelled=cancelled)
            expected = set(ids)
            got = [j.item_id for j in result.judgments]
            valid = (result.provider == provider and result.input_sha256 == selected.sha256
                     and len(got) == len(set(got)) and set(got) <= expected
                     and set(result.missing_item_ids) == expected - set(got)
                     and (not got or result.identity == report.inputs.judge_identities[provider]))
            if result.status == "complete" and (result.error or result.missing_item_ids):
                valid = False
            usable = valid and not result.unresolved_concept_ids
            if usable and result.status == "complete" and not result.error:
                done.update(got)
            missing = tuple(i.item_id for i in packet.items if i.item_id not in done)
            error = "judge-result-mismatch" if not valid else result.error
            if valid and result.identity != report.inputs.judge_identities[provider] and not error:
                error = "judge-identity-mismatch"
            if valid and result.unresolved_concept_ids:
                error = "unresolved-concept-selections"
            if valid and result.status == "incomplete" and not error:
                error = "judgments-incomplete"
            report = self.store.record_result(report.model_copy(update={
                "status": "incomplete" if error else "running",
                "missing_item_ids": {**report.missing_item_ids, provider: missing},
                "errors": {provider: error} if error else {}}), result, keep_judgments=usable)
            last = result
            report = await self._annotate(report, packet, provider, split_id)
            if error:
                return report, None
        return report, last.model_copy(update={
            "input_sha256": packet.sha256, "judgments": self.store.judgments(report.run_id, provider),
            "missing_item_ids": (), "status": "complete", "error": None})

    async def _resume(self, report, suite, ontology, extractor, codex, claude,
                      split_id, cancelled, equivalences):
        report = self.store.save(report.model_copy(update={"stage": "extraction"}))
        for doc in suite.documents:
            if cancelled and cancelled.is_set():
                raise InterruptedError
            if doc.source.source_id in report.extractions:
                continue
            try:
                row = await extractor.extract(doc.source)
                if (row.source_id != doc.source.source_id or row.source_sha256 != doc.source.sha256
                        or not row.coverage_complete):
                    raise ValueError("incomplete extraction")
                for prop in row.propositions:
                    prop.span.source_slice(doc.source.text)
            except (ValueError, OSError):
                return self.store.save(report.model_copy(update={"status": "incomplete",
                                      "errors": {"extraction": "extraction-incomplete"}}))
            digest = self.store.put(row.model_dump(mode="json"))
            report = self.store.save(report.model_copy(update={
                "extractions": {**report.extractions, doc.source.source_id: digest}}))
        rows = tuple(PredictionDocument.model_validate(self.store.artifact(report.extractions[d.source.source_id]))
                     for d in suite.documents)
        if equivalences is not None and equivalences != freeze_equivalences(suite, rows, equivalences.edges):
            raise ValueError("stale or incompatible extraction equivalences")
        packet = build_packet(suite, rows, ontology)
        report, first = await self._judge(report, packet, "codex", codex, split_id, cancelled)
        second, sample = None, None
        if first is not None:
            sample = claude_sample(packet, first.judgments, seed=report.inputs.sampling_seed)
            report = self.store.save(report.model_copy(update={"sample": sample.model_dump(mode="json")}))
            report, second = await self._judge(report, packet.select(sample.item_ids), "claude", claude,
                                                split_id, cancelled)
        pending = ()
        if first is not None and second is not None:
            pending = tuple(a.model_dump(mode="json") for a in adjudication_items(packet, first, second, sample))
            # New source-grounded omissions and outside-pool suggestions need authored
            # adjudication, even when both judges happen to propose the same addition.
            by_id = {i.item_id: i for i in packet.items}
            for result in (first, second):
                for verdict in result.judgments:
                    if (verdict.omission is not None or
                            set(verdict.concept_ids) - set(by_id[verdict.item_id].concept_ids)):
                        pending += ({"item_id": verdict.item_id, "provider": result.provider,
                                     "reasons": ["proposed-addition"], "judgment": verdict.model_dump(mode="json")},)
        complete = first is not None and second is not None and not pending
        scored_rows = tuple(r.model_copy(update={"judgments_complete": complete}) for r in rows)
        # The supplied edges were checked against immutable extraction content.
        # Rebind only the coordinator-owned readiness flags for this score snapshot.
        scored_equivalences = (freeze_equivalences(suite, scored_rows, equivalences.edges)
                               if equivalences is not None else None)
        scores = score_suite(suite, scored_rows, ontology=ontology, equivalences=scored_equivalences)
        status = "incomplete" if report.errors else ("adjudication" if pending else
                 ("complete" if scores.readiness == "ready" else "incomplete"))
        artifacts = {**report.artifacts, "scores": self.store.put(scores.model_dump(mode="json")),
                     "predictions": self.store.put([r.model_dump(mode="json") for r in scored_rows])}
        return self.store.save(report.model_copy(update={
            "status": status, "stage": "finished" if status == "complete" else report.stage,
            "artifacts": artifacts, "adjudication": pending, "scores": scores.model_dump(mode="json")}))
