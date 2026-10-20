"""Phase 9 roll-up: the seven principles together on one corpus (Phase 9 U8).

``run_phase9_rollup`` takes a disposable storage root, a generated signing
identity and the fakes the principles need (NLI, framework LLM, BFO LLM,
polysemy LLM), builds the synthetic multi-framework corpus
(``bench.multiframework``) and runs, in order, through public APIs only:

1. **P2** — open a framework-checked context, sign the corpus genesis,
   register a framework as the corpus admin, detect every source's framework
   (metadata, v1 migration, citations, LLM) and gate it; a source whose LLM
   answer is unregistered fails the gate and mints nothing.
2. **P7** — type every unit's subject (rule, then LLM, then default) and
   check strict mode refuses an untypeable subject.
3. **Mint and ingest** — build envelopes from the P2 and P7 answers and
   ingest them in one batch; check the write guard refuses an unregistered
   framework and the cycle guard refuses a planted 3-cycle, journal unchanged.
4. **P7 report** and **P2 temporal query** ("rule at T" per statute version).
5. **P3** — dependency DAG (one bulk read), the in-memory cycle finding,
   supersession and contest events, a retraction preview and commit under
   ``prefer_latest``, and the derived effective states.
6. **P4** — export under EL (default) and with ``expressive``; check a
   planted non-EL axiom names its rule; HermiT over the DL TBox when a JRE
   is available.
7. **P5** — closed-world counts: open over the corpus as stored (no writer
   emits ``fi:closedUnder``), closed over the same triples plus a declared
   island's membership.
8. **P1** — cluster validation with coverage and cross-reference checks,
   HermiT when available, else the NLI fallback, and labels its checkers.
9. **P6** — polysemy candidates from the P1 clusters and P2 registry, the
   detector on each, and the FP gate over the labeled set as computed (the
   gate status is reported, whatever it is).
10. **R1/R2** — every projected ``fi:`` term is declared, and no stored
    shard's bytes changed during the run.

Each step is timed; the report records hardware, the corpus size, timings,
and per-principle outcomes. Nothing here calls a network service or a live
model: the caller injects the fakes. HermiT steps run only when
``validation.hermit.hermit_available()`` says so and are otherwise reported
as skipped with the reason.
"""
from __future__ import annotations

import os
import platform
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from folio_insights.bench.multiframework import (
    FI,
    MultiFrameworkCorpusGenerator,
    SyntheticCorpus,
    SyntheticSource,
    SyntheticUnit,
    mint_shard,
    unit_iri,
)

REPORT_FORMAT = "folio-insights/phase9-rollup/v1"
T = TypeVar("T")


@dataclass
class RollupFakes:
    """The injected stand-ins for every model a principle could call."""

    nli: Any                 # validation.nli.NliScorer
    framework_llm: Any       # frameworks.detector.FrameworkLLM
    bfo_llm: Any             # bfo.classifier.BfoLLM
    polysemy_llm: Any        # port-shaped client for the detector's Rule 4


@dataclass
class _Clock:
    timings: dict[str, float] = field(default_factory=dict)

    async def step(self, name: str, work: Callable[[], Awaitable[T]]) -> T:
        started = time.perf_counter()
        try:
            return await work()
        finally:
            self.timings[name] = round(time.perf_counter() - started, 3)


def hardware() -> dict[str, Any]:
    """The machine the run measured (no identifying host names)."""
    model = platform.processor() or ""
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("model name"):
                    model = line.split(":", 1)[1].strip()
                    break
    except OSError:
        pass
    memory_gb: float | None = None
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    memory_gb = round(int(line.split()[1]) / 1024 / 1024, 1)
                    break
    except OSError:
        pass
    return {
        "cpu_model": model,
        "logical_cpus": os.cpu_count(),
        "memory_gb": memory_gb,
        "machine": platform.machine(),
        "system": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
    }


def _sign_event(event: Any, signing_key: Any, did: str, when: datetime) -> Any:
    """Sign a governance event over its canonical payload (as ``corpus init``)."""
    from folio_insights.identity.signer import sign_attestation
    from folio_insights.shards import AttestedSignature

    key_id = f"{did}#{did.removeprefix('did:key:')}"
    placeholder = event.model_copy(update={"signature": AttestedSignature(
        did=did, action=event.action, signed_at=when, signing_key_id=key_id)})
    signature = sign_attestation(
        placeholder.signature_payload().decode("utf-8"), signing_key, did, event.action,
        signing_key_id=key_id, did_doc_snapshot_at=None, now=when,
    )
    return placeholder.model_copy(update={"signature": signature})


def _unsigned(did: str, action: str, when: datetime) -> Any:
    from folio_insights.shards import AttestedSignature

    return AttestedSignature(did=did, action=action, signed_at=when)  # type: ignore[arg-type]


class _OverlayRunner:
    """A ``SparqlRunner`` over a snapshot of the corpus triples plus extra
    triples (the P5 island membership no writer emits yet)."""

    def __init__(self, triples: list[Any], extra: list[tuple[str, str, str]]) -> None:
        from pyoxigraph import NamedNode, Quad, Store

        self.store = Store()
        self.store.extend([Quad(t.subject, t.predicate, t.object) for t in triples])
        self.store.extend([Quad(NamedNode(s), NamedNode(p), NamedNode(o)) for s, p, o in extra])

    async def query(self, sparql: str, *, include_tbox: bool = False) -> Any:
        result = self.store.query(sparql)
        names = [v.value for v in result.variables]
        return [{n: sol[n] for n in names} for sol in result]


def _declared_fi_terms() -> set[str]:
    from rdflib import OWL, RDF, URIRef

    from folio_insights.vocab import FI_PREFIX, load_graph

    declaring = {OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty, OWL.Class}
    g = load_graph(include_bfo_mapping=True)
    return {
        str(s) for s, _, o in g.triples((None, RDF.type, None))
        if o in declaring and isinstance(s, URIRef) and str(s).startswith(FI_PREFIX)
    }


async def run_phase9_rollup(
    root: str | Path,
    *,
    signing_key: Any,
    did: str,
    fakes: RollupFakes,
    labeled_set: Path,
    workdir: str | Path,
    generator: MultiFrameworkCorpusGenerator | None = None,
    corpus: str = "phase9-rollup",
    use_hermit: bool | None = None,
) -> dict[str, Any]:
    """Run every Phase 9 principle over one synthetic corpus; return the report.

    ``use_hermit``: ``None`` runs HermiT when it is available, ``False``
    never runs it (the cluster check falls back to NLI, the DL TBox is not
    reasoned over). ``workdir`` receives the exports.
    """
    from folio_insights.validation.hermit import hermit_available

    total_started = time.perf_counter()
    clock = _Clock()
    workdir = Path(workdir)
    available, why = hermit_available()
    hermit = available if use_hermit is None else (use_hermit and available)
    hermit_reason = "available" if hermit else (why if not available else "disabled by caller")
    skipped: list[str] = []
    if not hermit:
        skipped += [f"P1 HermiT cluster reasoning: {hermit_reason}",
                    f"P4 HermiT over the expressive TBox: {hermit_reason}"]

    generator = generator or MultiFrameworkCorpusGenerator()
    data: SyntheticCorpus = await clock.step("generate", _async(generator.generate))
    report: dict[str, Any] = {
        "format": REPORT_FORMAT,
        "hardware": hardware(),
        "corpus": {"name": corpus, "seed": data.seed,
                   "units_per_source": generator.units_per_source,
                   "sources": len(data.sources)},
        "hermit": hermit_reason,
        "skipped": skipped,
        "principles": {},
    }
    principles: dict[str, Any] = report["principles"]

    from folio_insights.frameworks.registry import open_framework_checked_context

    ctx, guard = await open_framework_checked_context(Path(root), corpus)
    try:
        await _run(ctx, guard, data, clock, principles, report,
                   signing_key=signing_key, did=did, fakes=fakes,
                   labeled_set=labeled_set, workdir=workdir, hermit=hermit)
    finally:
        await ctx.close()
    report["timings_s"] = clock.timings
    report["timings_s"]["total"] = round(time.perf_counter() - total_started, 3)
    return report


def _async(fn: Callable[[], T]) -> Callable[[], Awaitable[T]]:
    async def run() -> T:
        return fn()
    return run


async def _run(
    ctx: Any, guard: Any, data: SyntheticCorpus, clock: _Clock,
    principles: dict[str, Any], report: dict[str, Any], *,
    signing_key: Any, did: str, fakes: RollupFakes, labeled_set: Path,
    workdir: Path, hermit: bool,
) -> None:
    from folio_insights.bfo.classifier import BfoClassifier, BfoInput, BfoUnclassifiable, FolioTag
    from folio_insights.bfo.report import corpus_report, record_assignment
    from folio_insights.bfo.spine import ParentMapResolver
    from folio_insights.frameworks.detector import FrameworkDetector
    from folio_insights.frameworks.query import shards_in_framework_at
    from folio_insights.frameworks.registry import load_registry, register_framework
    from folio_insights.governance.events import RoleAssertionEvent
    from folio_insights.models.framework import UnregisteredFramework
    from folio_insights.quality.confidence_gate import ConfidenceGate
    from folio_insights.revision.acyclicity import DependencyCycle

    resolver = ParentMapResolver(data.folio_parents)
    p = data.planted

    # ── P2: genesis, registration, detection ─────────────────────────────
    async def setup() -> Any:
        now = datetime.now(UTC).replace(microsecond=0)
        genesis = RoleAssertionEvent(corpus=ctx.corpus, signature=_unsigned(did, "role_assertion", now),
                                     subject_did=did, role="corpus_admin")
        await ctx.governance.append(_sign_event(genesis, signing_key, did, now),
                                    op_id=f"genesis:{ctx.corpus}")
        for framework in data.registered_frameworks:
            await register_framework(ctx, framework, signing_key=signing_key, did=did)
        return await guard.refresh(ctx)

    registry = await clock.step("p2_register", setup)

    def detect() -> dict[str, Any]:
        detector = FrameworkDetector(registry, llm=fakes.framework_llm)
        gate = ConfidenceGate()
        out = {}
        for source in data.sources:
            detection = detector.detect(source.metadata)
            out[source.key] = (detection, gate.check_framework(detection))
        return out

    detections = await clock.step("p2_detect", _async(detect))
    determinism = all(
        FrameworkDetector(registry, llm=fakes.framework_llm).detect(s.metadata) == detections[s.key][0]
        for s in data.sources
    )
    minted_sources = [s for s in data.sources if detections[s.key][1].passed]

    # ── P7: typing ────────────────────────────────────────────────────────
    def classify() -> dict[str, Any]:
        classifier = BfoClassifier(mode="permissive", llm=fakes.bfo_llm, resolver=resolver)
        return {
            u.key: classifier.classify(_bfo_input(u, s, BfoInput, FolioTag))
            for s in minted_sources for u in s.units
        }

    assignments = await clock.step("p7_classify", _async(classify))
    strict = BfoClassifier(mode="strict", llm=fakes.bfo_llm, resolver=resolver)
    default_keys = sorted(k for k, a in assignments.items() if a.is_default)
    strict_refused = 0
    for source in minted_sources:
        for unit in source.units:
            if unit.key in default_keys:
                try:
                    strict.classify(_bfo_input(unit, source, BfoInput, FolioTag))
                except BfoUnclassifiable:
                    strict_refused += 1

    # ── mint and ingest ───────────────────────────────────────────────────
    iri_of = {u.key: unit_iri(s.uri, u.span) for s in data.sources for u in s.units}
    shards = [
        mint_shard(s, u, framework_id=detections[s.key][0].framework_id,
                   bfo_category=assignments[u.key].category,
                   valid_time=detections[s.key][0].valid_time, iri_of=iri_of)
        for s in minted_sources for u in s.units
    ]

    async def ingest() -> Any:
        return await ctx.ingest_shards(shards, op_id="rollup:ingest")

    await clock.step("ingest", ingest)
    head = await ctx.journal_head()
    unregistered_refused = False
    try:
        rogue = shards[0].model_copy(update={"framework_id": "zz.unregistered.body"})
        await ctx.shards.put(rogue.shard_iri, rogue)
    except UnregisteredFramework:
        unregistered_refused = True
    cycle_source = data.source(p.cycle_source)
    cycle_iris = {u.key: unit_iri(cycle_source.uri, u.span) for u in p.cycle}
    cycle_shards = [
        mint_shard(cycle_source, u, framework_id=cycle_source.expected_framework or "",
                   bfo_category="continuant_dependent", valid_time=None,
                   iri_of={**iri_of, **cycle_iris})
        for u in p.cycle
    ]
    cycle_refused: list[str] = []
    try:
        await ctx.ingest_shards(cycle_shards, op_id="rollup:cycle")
    except DependencyCycle as exc:
        cycle_refused = list(exc.cycle)
    journal_unchanged = await ctx.journal_head() == head
    before = {s.shard_iri: (await ctx.shards.get_record(s.shard_iri)).payload for s in shards}

    report["corpus"].update({
        "shards": len(shards),
        "frameworks": sorted({s.framework_id for s in shards}),
        "sources_minted": len(minted_sources),
    })

    principles["P2"] = {
        "requirement": "R5",
        "registered": [f.id for f in data.registered_frameworks],
        "detections": {
            k: {"framework_id": d.framework_id, "source": d.source, "confidence": d.confidence,
                "gate": g.passed, "migration_warnings": list(d.migration_warnings),
                "valid_time": None if d.valid_time is None else [
                    None if d.valid_time.start is None else d.valid_time.start.isoformat(),
                    None if d.valid_time.end is None else d.valid_time.end.isoformat()]}
            for k, (d, g) in sorted(detections.items())
        },
        "detection_sources": sorted({d.source for d, g in detections.values() if g.passed}),
        "expected_frameworks_matched": all(
            detections[s.key][0].framework_id == s.expected_framework
            if s.expected_framework else not detections[s.key][1].passed
            for s in data.sources
        ),
        "deterministic": determinism,
        "unregistered_write_refused": unregistered_refused,
    }

    # ── P7 report; P2 temporal query ─────────────────────────────────────
    async def bfo_report() -> Any:
        key_of = {v: k for k, v in iri_of.items()}
        for shard in shards:
            await record_assignment(ctx, shard.shard_iri, assignments[key_of[shard.shard_iri]])
        return await corpus_report(ctx)

    bfo = (await clock.step("p7_record_and_report", bfo_report)).as_dict()
    spine_rows = await ctx.query(
        f"SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {{ ?s <{FI}subjectBfoClass> ?c }}")
    principles["P7"] = {
        "requirement": "R10",
        "coverage": bfo["coverage"],
        "default_share": bfo["default_share"],
        "provenance": {k: sum(s["provenance"][k] for s in bfo["sources"])
                       for k in ("rule", "llm", "default", "unrecorded")},
        "categories": bfo["categories"],
        "event_subcount": bfo["event_subcount"],
        "sources_reported": len(bfo["sources"]),
        "strict_refused_defaults": strict_refused,
        "defaults": len(default_keys),
        "projected_spine_class": int(spine_rows[0]["n"].value),
    }

    old, new = iri_of[p.superseded], iri_of[p.superseding]

    async def temporal() -> dict[str, list[str]]:
        out = {}
        for at in ("2012-06-01", "2024-06-01", "1999-01-01"):
            rows = await shards_in_framework_at(ctx, "us.federal.fre", datetime.fromisoformat(at)
                                                .replace(tzinfo=UTC), reference=p.supersession_reference)
            out[at] = [r[0] for r in rows]
        return out

    windows = await clock.step("p2_temporal_query", temporal)
    principles["P2"]["rule_at_t"] = {
        "query": "shards_in_framework_at(us.federal.fre, T, reference=<planted rule>)",
        "results": windows,
        "picks_version": windows["2012-06-01"] == [old] and windows["2024-06-01"] == [new]
        and windows["1999-01-01"] == [],
    }

    # ── P3: DAG, cycles, revision effects ────────────────────────────────
    await _p3(ctx, data, clock, principles, iri_of, shards, cycle_shards, cycle_refused,
              journal_unchanged, signing_key=signing_key, did=did)

    # ── P4: EL profile and export flags ──────────────────────────────────
    await _p4(ctx, clock, principles, workdir, hermit=hermit)

    # ── P5: closed-world islands ─────────────────────────────────────────
    await _p5(ctx, data, clock, principles, iri_of)

    # ── P1: cluster validation ───────────────────────────────────────────
    await _p1(ctx, data, clock, principles, iri_of, resolver, fakes=fakes, hermit=hermit)

    # ── P6: polysemy ─────────────────────────────────────────────────────
    head_before_p6 = await ctx.journal_head()
    registry = await load_registry(ctx)
    await _p6(data, clock, principles, shards, registry, resolver, fakes=fakes,
              labeled_set=labeled_set)
    principles["P6"]["journal_unchanged"] = await ctx.journal_head() == head_before_p6

    # ── R1 / R2 ──────────────────────────────────────────────────────────
    async def cross_cutting() -> dict[str, Any]:
        rows = await ctx.query("SELECT DISTINCT ?p WHERE { ?s ?p ?o }")
        types = await ctx.query("SELECT DISTINCT ?c WHERE { ?s a ?c }")
        used = {r["p"].value for r in rows if r["p"].value.startswith(FI)}
        used |= {r["c"].value for r in types if r["c"].value.startswith(FI)}
        undeclared = sorted(used - _declared_fi_terms())
        after = {iri: (await ctx.shards.get_record(iri)).payload for iri in before}
        return {
            "R1_projected_fi_terms": len(used),
            "R1_undeclared": undeclared,
            "R2_shard_bytes_unchanged": after == before,
        }

    report["cross_cutting"] = await clock.step("r1_r2_checks", cross_cutting)


def _bfo_input(unit: SyntheticUnit, source: SyntheticSource, bfo_input: Any, folio_tag: Any) -> Any:
    return bfo_input(
        speech_act=unit.speech_act,
        folio_tags=tuple(folio_tag(iri=t, verified=True) for t in unit.tags),
        subject=unit.subject,
        source_uri=source.uri,
    )


async def _p3(
    ctx: Any, data: SyntheticCorpus, clock: _Clock, principles: dict[str, Any],
    iri_of: dict[str, str], shards: list[Any], cycle_shards: list[Any],
    cycle_refused: list[str], journal_unchanged: bool, *, signing_key: Any, did: str,
) -> None:
    from folio_insights.governance.events import (
        ContestEvent,
        ContestResolutionEvent,
        SupersessionEvent,
    )
    from folio_insights.governance.retract import build_cascade_preview, commit_cascade
    from folio_insights.revision.dependency_graph import DependencyGraph
    from folio_insights.revision.effective_state import effective_states

    p = data.planted
    graph = await clock.step("p3_dag_build", lambda: DependencyGraph.from_store(ctx.shards))
    with_cycle = DependencyGraph.from_shards([*shards, *cycle_shards])
    cycles = with_cycle.cycles()

    async def events() -> Any:
        now = datetime.now(UTC).replace(microsecond=0)
        for event in (
            SupersessionEvent(corpus=ctx.corpus, signature=_unsigned(did, "supersede", now),
                              old_shard_iri=iri_of[p.superseded], new_shard_iri=iri_of[p.superseding]),
            ContestEvent(corpus=ctx.corpus, signature=_unsigned(did, "contest", now),
                         shard_iri=iri_of[p.contested], voter_did=did,
                         position_text="synthetic objection"),
            ContestEvent(corpus=ctx.corpus, signature=_unsigned(did, "contest", now),
                         shard_iri=iri_of[p.resolved], voter_did=did,
                         position_text="synthetic objection"),
            ContestResolutionEvent(corpus=ctx.corpus, signature=_unsigned(did, "resolve_contest", now),
                                   shard_iri=iri_of[p.resolved], resolution_path="distinguo"),
        ):
            await ctx.governance.append(_sign_event(event, signing_key, did, now))
        head = await ctx.journal_head()
        preview = await build_cascade_preview(
            iri_of[p.retracted], ctx.corpus, store=ctx.shards, log=ctx.governance,
            state_position=head, policy="prefer_latest",
        )
        await commit_cascade(preview, store=ctx.shards, log=ctx.governance,
                             signing_key=signing_key, did=did)
        return preview

    preview = await clock.step("p3_governance_events", events)
    states = await clock.step("p3_effective_states",
                              lambda: effective_states(ctx.shards, ctx.governance))

    def status(key: str) -> str:
        return states[iri_of[key]].status

    principles["P3"] = {
        "requirement": "R6",
        "dag": {"nodes": graph.node_count, "edges": graph.edge_count,
                "acyclic": graph.is_acyclic(),
                "build_seconds": clock.timings["p3_dag_build"]},
        "planted_cycle_refused_by_storage": cycle_refused,
        "planted_cycle_journal_unchanged": journal_unchanged,
        "planted_cycle_reported": [list(c) for c in cycles],
        "cycle_is_planted": sorted(iri_of_cycle(cycles)) == sorted(s.shard_iri for s in cycle_shards),
        "retraction_preview": {
            "policy": preview.policy,
            "auto_rederive": len(preview.auto_rederive),
            "aporetic": len(preview.aporetic),
            "review_needed": len(preview.review_needed),
            "depths": sorted(preview.depths.values()),
        },
        "effective_state": {
            "retracted": status(p.retracted),
            "successor": status(p.successor),
            "direct_dependents": [status(k) for k in p.direct_dependents],
            "deep_dependents": [status(k) for k in p.deep_dependents],
            "superseded": status(p.superseded),
            "superseded_valid_time_end": _iso(states[iri_of[p.superseded]].valid_time_end),
            "superseding": status(p.superseding),
            "contested": status(p.contested),
            "resolved": status(p.resolved),
        },
        "status_counts": _counts(s.status for s in states.values()),
    }


def iri_of_cycle(cycles: list[tuple[str, ...]]) -> list[str]:
    return [iri for cycle in cycles for iri in cycle]


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _counts(values: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items()))


async def _p4(ctx: Any, clock: _Clock, principles: dict[str, Any], workdir: Path, *,
              hermit: bool) -> None:
    from pyoxigraph import NamedNode, RdfFormat, Triple, parse, serialize

    from folio_insights.reason.el_profile import check_el_profile
    from folio_insights.reason.reasoner import HermitReasoner
    from folio_insights.storage.exports import export_corpus

    el = await clock.step("p4_export_el", lambda: export_corpus(ctx, workdir / "export-el"))
    dl = await clock.step("p4_export_expressive",
                          lambda: export_corpus(ctx, workdir / "export-dl", expressive=True))
    shipped = list(parse(path=str(workdir / "export-el" / "tbox.ttl"), format=RdfFormat.TURTLE))
    owl = "http://www.w3.org/2002/07/owl#"
    key = NamedNode("urn:synthetic:tbox#hasSyntheticId")
    rdf_type = NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
    planted = [Triple(key, rdf_type, NamedNode(f"{owl}ObjectProperty")),
               Triple(key, rdf_type, NamedNode(f"{owl}InverseFunctionalProperty"))]
    violations = check_el_profile([*shipped, *planted])
    entry: dict[str, Any] = {
        "requirement": "R7",
        "el_export": {k: el.manifest["tbox_profile"][k]
                      for k in ("profile", "el_conformant", "reasoner")},
        "expressive_export": {
            "profile": dl.manifest["tbox_profile"]["profile"],
            "warnings": len(dl.manifest["tbox_profile"]["warnings"]),
            "el_violation_rules": sorted({v["rule"] for v in dl.manifest["tbox_profile"]["el_violations"]}),
        },
        "shipped_tbox_el_violations": len(check_el_profile(shipped)),
        "planted_violation": [v.as_dict() for v in violations],
        "hermit_dl_tbox": "skipped",
    }
    if hermit:
        dl_tbox = list(parse(path=str(workdir / "export-dl" / "tbox.ttl"), format=RdfFormat.TURTLE))
        nt = workdir / "tbox-dl.nt"
        nt.write_bytes(serialize([t for t in dl_tbox if "shacl" not in str(t)],
                                 format=RdfFormat.N_TRIPLES))

        async def reason() -> Any:
            return HermitReasoner(xmx_mb=512).check(nt, profile="DL")

        result = await clock.step("p4_hermit_dl_tbox", reason)
        entry["hermit_dl_tbox"] = {"consistent": result.consistent,
                                   "unsatisfiable": list(result.unsatisfiable)}
    principles["P4"] = entry


async def _p5(ctx: Any, data: SyntheticCorpus, clock: _Clock, principles: dict[str, Any],
              iri_of: dict[str, str]) -> None:
    from folio_insights.query.closed_world import (
        CLOSED_UNDER,
        ClosedWorldQuery,
        ClosedWorldScope,
    )

    source = data.source(data.planted.closed_source)
    scope_iri = f"urn:synthetic:scope/{source.key}"
    shard_cls, prop = f"{FI}Shard", f"{FI}dependsOnShard"
    scope = ClosedWorldScope(scope_iri, frozenset({shard_cls}), frozenset({prop}))
    members = [iri_of[u.key] for u in source.units]
    expected_lacking = sum(1 for u in source.units if not u.depends_on_shards)
    chained = next(u for u in source.units if u.depends_on_shards)

    async def run() -> dict[str, Any]:
        triples = await ctx.query("CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }")
        island = _OverlayRunner(triples, [(m, CLOSED_UNDER, scope_iri) for m in members])
        stored = ClosedWorldQuery(ctx, [scope])
        closed = ClosedWorldQuery(island, [scope])
        return {
            "declared_scopes_in_store": await stored.declared_scope_iris(),
            "open_lacking": await stored.count_lacking(shard_cls, prop, scope_iri),
            "closed_lacking": await closed.count_lacking(shard_cls, prop, scope_iri),
            "open_related": await stored.count_related(iri_of[chained.key], prop),
            "closed_related": await closed.count_related(iri_of[chained.key], prop),
        }

    r = await clock.step("p5_closed_world", run)

    def view(result: Any) -> dict[str, Any]:
        out = {"world_assumption": result.world_assumption, "count": result.count,
               "incomplete_note": result.incompleteness_note is not None}
        for extra in ("total_instances", "asserted_with_property"):
            if hasattr(result, extra):
                out[extra] = getattr(result, extra)
        return out

    principles["P5"] = {
        "requirement": "R8",
        "scope": scope_iri,
        "island_members": len(members),
        "expected_lacking": expected_lacking,
        "declared_scopes_in_store": r["declared_scopes_in_store"],
        "membership_source": "overlay (no writer emits fi:closedUnder yet)",
        **{k: view(v) for k, v in r.items() if k != "declared_scopes_in_store"},
    }


async def _p1(ctx: Any, data: SyntheticCorpus, clock: _Clock, principles: dict[str, Any],
              iri_of: dict[str, str], resolver: Any, *, fakes: RollupFakes, hermit: bool) -> None:
    from folio_insights.validation.coverage import TaskNode
    from folio_insights.validation.validator import validate_corpus

    p = data.planted
    tasks = [TaskNode(id=t["id"], label=t["label"], folio_iri=t.get("folio_iri"),
                      parent_id=t.get("parent_id")) for t in data.task_tree]
    head = await ctx.journal_head()
    validation = await clock.step("p1_validate_clusters", lambda: validate_corpus(
        ctx, tasks=tasks, folio_resolver=resolver, nli=fakes.nli,
        reasoner="auto" if hermit else None, disjoint_seeds=[p.disjoint_classes],
    ))
    contradiction = sorted(iri_of[k] for k in p.contradiction)
    citation = sorted(iri_of[k] for k in p.cross_framework_citation)
    clash = sorted(iri_of[k] for k in p.formal_clash)

    def found(kind: str, pair: list[str]) -> list[dict[str, Any]]:
        return [
            {"checker": f.checker, "severity": f.severity, "clusters": len(f.clusters),
             "proposals": [x.strategy for x in f.proposals] if f.proposals else []}
            for f in validation.findings_of(kind) if sorted(f.shards) == pair
        ]

    summary = validation.summary()
    principles["P1"] = {
        "requirement": "R4",
        "checkers": validation.checkers.model_dump(),
        "summary": summary,
        "planted_contradiction": found("contradiction", contradiction),
        "planted_cross_framework_citation": found("cross_framework_citation", citation),
        "planted_formal_clash": found("contradiction", clash),
        "coverage_gaps": [f.detail.get("task_id") or f.summary
                          for f in validation.findings_of("coverage_gap")],
        "applied": validation.applied,
        "journal_unchanged": await ctx.journal_head() == head,
    }


async def _p6(data: SyntheticCorpus, clock: _Clock, principles: dict[str, Any],
              shards: list[Any], registry: Any, resolver: Any, *, fakes: RollupFakes,
              labeled_set: Path) -> None:
    from folio_insights.polysemy.candidates import polysemy_candidates
    from folio_insights.polysemy.detector import detect_polysemy
    from folio_insights.polysemy.labeled_set import evaluate_labeled_set, load_labeled_set
    from folio_insights.polysemy.prototype_cluster import build_prototype_cluster
    from folio_insights.polysemy.tbox import disjointness_seed_ttl, load_tbox_seeds
    from folio_insights.store.pyoxigraph_store import PyoxigraphStore
    from folio_insights.validation.clusters import ClusterBuilder

    p = data.planted

    def detect() -> dict[str, Any]:
        clusters = ClusterBuilder(registry=registry, folio_resolver=resolver).build(shards)
        found = polysemy_candidates(shards, clusters, registry)
        store = PyoxigraphStore(path=None)
        # The seed names the candidate's term key (the normalized label Rule 1
        # reads), not the concept IRI the shards carry.
        planted_term = next(
            (c.term for c in found.candidates if c.concept == p.polysemy_concept), None)
        if planted_term is not None:
            load_tbox_seeds(store, disjointness_seed_ttl(planted_term, [p.polysemy_frameworks]))
        verdicts = {}
        for candidate in found.candidates:
            verdict = detect_polysemy(build_prototype_cluster(list(candidate.shards)), store,
                                      llm=fakes.polysemy_llm)
            verdicts[candidate.concept] = verdict
        return {"candidates": found, "verdicts": verdicts, "term": planted_term}

    detected = await clock.step("p6_detect_corpus", _async(detect))
    planted = detected["verdicts"].get(p.polysemy_concept)
    evaluation = await clock.step(
        "p6_fp_gate", _async(lambda: evaluate_labeled_set(load_labeled_set(labeled_set))))
    gate = evaluation.report
    principles["P6"] = {
        "requirement": "R9",
        "candidates": len(detected["candidates"].candidates),
        "decisions": _counts(v.decision for v in detected["verdicts"].values()),
        "planted_term": None if planted is None else {
            "term": detected["term"],
            "decision": planted.decision, "matched_rules": list(planted.matched_rules),
            "evidence_score": round(planted.evidence_score, 4),
        },
        "fork_applied": False,  # no API applies a fork without a human disposition
        "fp_gate": {
            "n": gate.n,
            "false_positives": gate.false_positives,
            "fp_rate": round(gate.fp_rate, 4),
            "wilson_upper": round(gate.ci_upper, 4),
            "threshold": gate.threshold,
            "status": gate.status,
            "certified": gate.certified,
            "cases_sha256": evaluation.cases_sha256,
        },
    }


__all__ = ["REPORT_FORMAT", "RollupFakes", "hardware", "run_phase9_rollup"]
