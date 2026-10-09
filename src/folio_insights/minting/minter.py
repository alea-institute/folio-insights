"""The gated shard minter: an extraction run -> hypothesis shards (drain U8, R1-R5).

``mint_run`` reads a ``folio-insights extract`` run (``extraction.json``) and,
for each KnowledgeUnit, in order:

1. **Eligibility** (``minting.eligibility``): anchor recomputed against the
   source file (stored scores never vouch), the unit text supported by the verified
   slice (``minting.support``: specifics, lexical recall, optional NLI), substance
   guard, ruler-derived or B9-verified judged IRIs that the IRI oracle confirms exist
   in their claimed branch, prompt identity, no duplicate in the run. No LLM, no
   writes.
2. **Identity**: ``source_uri`` (``minting.mapper.source_uri_for``) and the
   verified slice give the shard IRI (``shards.minting``). An IRI the corpus
   already holds is reported ``already_present`` and costs no LLM call, which is
   what makes a re-run write nothing (AE2). A shard-IRI cross reference must
   resolve to a shard in the corpus (``dependency_unresolved`` otherwise).
3. **Framework** (Phase 9 detector, once per source; the template hashes and
   routes of any LLM call it made are part of EVERY unit of that source, so
   ``extraction_prompt_hash`` and ``extractor_model`` never depend on unit order) ->
   **fields** (one ``mint.fields.v1`` call; the inferred ``sense`` and ``reference``
   may state no specific the verified slice lacks) -> **BFO** (strict classifier),
   each refusing instead of defaulting (``minting.fields``).
4. **Write**: the shard (signed ``extract`` by the signing key, when given) is
   ingested through ``frameworks.registry.open_framework_checked_context`` (PII
   gate, envelope model, SHACL local tier, ``FrameworkGuard``, cycle guard)
   under op ID ``mint:<run>:<unit-hash>``; its IRI is also registered in the
   collision-checking ``ShardIRIRegistry``.
5. **ExtractEvent**: one per shard, op ID ``mint-extract:<shard IRI>``, naming
   ``extractor_model`` (``ExtractEvent.extractor_model``). An append that fails after
   the shard was written is reported ``failed:<ExceptionType>`` and the run goes on;
   a re-run appends the missing event (the already-present path). For a shard
   already in the corpus the event is signed only by its own
   ``first_extractor_did``; another signer gets ``not_extractor`` and nothing is
   appended.

IRI oracle. A non-dry mint needs an IRI oracle (``--oracle folio|FILE``) so every
carried IRI is checked to exist in its claimed branch before anything is written;
``require_iri_oracle=False`` (``--no-iri-oracle``) runs without, and the report
records ``iri_unchecked`` as an unchecked risk.

Signing and the governance log. The corpus journal accepts a governance event
only when its signature verifies and its signer is authorized at commit time
(``storage.context._append_governance``); an unsigned ExtractEvent is always
refused. So, strictest working option: with a signing key the signer must hold
the ``extractor`` role (or a role that includes it) BEFORE anything is called or
written (``MintRefused("extractor_unauthorized")`` otherwise), every shard
carries an ``extract`` signature and every ExtractEvent is signed, verified and
appended. Without a signing key the shards are written unsigned (the SHACL suite
warns), every unit's ExtractEvent is reported ``unsigned: skipped``, and the
``first_extractor_did`` the shards record is the caller's unproven claim: the report
flags the run ``unattested``.

Source visibility (R5, Chief p10 q3). Every run declares its sources
``public`` or ``non-public``. Private corpora (Phase 13.5) do not exist yet, so a
non-public run mints only into a corpus an operator has marked local-only
(``mark_local_only``: a marker under the storage root's ``local-only/``
directory); anything else is refused with ``MintRefused("source_visibility")``
before the extraction is evaluated, any LLM call is made or the corpus is opened.
The marker records the operator's declaration; keeping that corpus out of
``storage dump`` / exports is the operator's duty until Phase 13.5 enforces it.

The IRI registry defaults to ``<root>/shard-iri-registry.db`` (not the global
``~/.folio-insights`` registry) so that registered source spans stay inside the
storage root a non-public run was confined to.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from folio_insights.llm.errors import RunHalted
from folio_insights.llm.templates import MINT_FIELDS
from folio_insights.minting.eligibility import (
    DEPENDENCY_UNRESOLVED,
    FIELD_INFERENCE_UNAVAILABLE,
    STORAGE_REFUSED,
    UNSUPPORTED_SPECIFICS,
    Eligible,
    Refused,
    RunEvidence,
    evaluate,
)
from folio_insights.minting.fields import (
    FieldFloors,
    OracleBranchResolver,
    classify_bfo,
    detect_framework,
    infer_fields,
    strict_classifier,
)
from folio_insights.minting.mapper import (
    SHARD_IRI_PREFIX,
    build_shard,
    dependency_fields,
    extract_event_op_id,
    extractor_model,
    mint_op_id,
    prompt_hash,
    source_uri_for,
)
from folio_insights.minting.report import (
    ALREADY_PRESENT,
    ELIGIBLE,
    EVENT_APPENDED,
    EVENT_EXISTING,
    EVENT_FAILED_PREFIX,
    EVENT_NOT_EXTRACTOR,
    EVENT_UNSIGNED_SKIPPED,
    FLAG_IRI_UNCHECKED,
    FLAG_UNATTESTED,
    MINTED,
    REFUSED,
    MintReport,
    UnitOutcome,
    rubric_section,
)
from folio_insights.minting.support import (
    SupportPolicy,
    SupportUnavailable,
    unsupported_specifics_only,
)
from folio_insights.models.knowledge_unit import KnowledgeUnit

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from folio_insights.llm.context import LLMRunContext
    from folio_insights.llm.port import LLMPort
    from folio_insights.rubric.oracle import IriOracle
    from folio_insights.storage.context import CorpusStorageContext, StorageConfig

PUBLIC = "public"
NON_PUBLIC = "non-public"
SOURCE_VISIBILITIES: tuple[str, ...] = (PUBLIC, NON_PUBLIC)
LOCAL_ONLY_DIRNAME = "local-only"
LOCAL_ONLY_FORMAT = 1
REGISTRY_FILENAME = "shard-iri-registry.db"


class MintError(ValueError):
    """The run's inputs cannot be read (missing file, malformed run, bad option)."""


class MintRefused(PermissionError):
    """The whole run is refused before any LLM call or write. ``code`` names why."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# ── local-only corpora (R5) ──────────────────────────────────────────────


def local_only_marker(root: Path | str, corpus: str) -> Path:
    digest = hashlib.sha256(corpus.encode("utf-8")).hexdigest()[:32]
    return Path(root) / LOCAL_ONLY_DIRNAME / f"{digest}.json"


def is_local_only(root: Path | str, corpus: str) -> bool:
    """True iff an operator marked ``corpus`` local-only under ``root``."""
    marker = local_only_marker(root, corpus)
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return False
    return (isinstance(data, Mapping) and data.get("format") == LOCAL_ONLY_FORMAT
            and data.get("corpus") == corpus and data.get("local_only") is True)


def mark_local_only(root: Path | str, corpus: str) -> Path:
    """Declare ``corpus`` under ``root`` local-only (idempotent); returns the marker."""
    marker = local_only_marker(root, corpus)
    if is_local_only(root, corpus):
        return marker
    marker.parent.mkdir(parents=True, exist_ok=True)
    tmp = marker.with_suffix(".tmp")
    tmp.write_text(json.dumps({
        "format": LOCAL_ONLY_FORMAT,
        "corpus": corpus,
        "local_only": True,
        "declared_at": datetime.now(UTC).isoformat(),
        "note": "non-public sources may be minted into this corpus; keep it out of "
                "dumps and exports (Phase 13.5 will enforce private corpora)",
    }, indent=2) + "\n", encoding="utf-8")
    tmp.replace(marker)
    return marker


def check_visibility(root: Path | str, corpus: str, source_visibility: str) -> None:
    """Refuse a non-public run into a corpus not marked local-only (R5)."""
    if source_visibility not in SOURCE_VISIBILITIES:
        raise MintError(f"source visibility must be one of {SOURCE_VISIBILITIES}; "
                        f"got {source_visibility!r}")
    if source_visibility == NON_PUBLIC and not is_local_only(root, corpus):
        raise MintRefused(
            "source_visibility",
            f"non-public sources mint only into a private or local-only corpus; corpus "
            f"{corpus!r} is neither (mark it with `folio-insights mint {corpus} "
            "--mark-local-only` if it never leaves this machine). Nothing was called or written.",
        )


# ── inputs ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LoadedRun:
    path: Path
    sha256: str
    data: Mapping[str, Any]
    units: tuple[tuple[Mapping[str, Any], KnowledgeUnit], ...]

    @property
    def summary(self) -> Mapping[str, Any]:
        summary = self.data.get("summary")
        return summary if isinstance(summary, Mapping) else {}


def load_run(extraction_json: Path | str) -> LoadedRun:
    from pydantic import ValidationError

    path = Path(extraction_json)
    if path.is_dir():
        path = path / "extraction.json"
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise MintError(f"extraction file not found: {path}") from exc
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise MintError(f"extraction file is not valid JSON: {path}") from exc
    raw_units = data.get("units") if isinstance(data, Mapping) else None
    if not isinstance(raw_units, list):
        raise MintError(f"{path}: expected an object with a 'units' list")
    units: list[tuple[Mapping[str, Any], KnowledgeUnit]] = []
    ids: set[str] = set()
    for index, item in enumerate(raw_units):
        try:
            unit = KnowledgeUnit.model_validate(item)
        except ValidationError as exc:
            raise MintError(f"{path}: unit {index} is not a KnowledgeUnit "
                            f"({exc.error_count()} error(s))") from None
        if unit.id in ids:
            raise MintError(f"{path}: duplicate unit id {unit.id!r}")
        ids.add(unit.id)
        units.append((item, unit))
    return LoadedRun(path, hashlib.sha256(raw).hexdigest(), data, tuple(units))


def default_run_id(run: LoadedRun) -> str:
    """Deterministic: the same extraction file always mints under the same run ID."""
    return f"run-{run.sha256[:16]}"


# ── the ExtractEvent ─────────────────────────────────────────────────────


async def _ensure_extract_event(
    ctx: CorpusStorageContext,
    shard_iri: str,
    model: str,
    *,
    signing_key: Ed25519PrivateKey | None,
    did: str,
    first_extractor_did: str | None = None,
) -> str:
    """Append the shard's one ExtractEvent (idempotent by op ID); returns the outcome.

    ``first_extractor_did`` is the stored shard's extractor on the already-present
    path: only that DID may sign the shard's ExtractEvent (``not_extractor``
    otherwise). Any failure of the append is reported ``failed:<Type>``, never raised:
    the shard is already written, and a re-run appends the missing event.
    """
    if signing_key is None:
        return EVENT_UNSIGNED_SKIPPED
    if first_extractor_did is not None and first_extractor_did != did:
        return EVENT_NOT_EXTRACTOR
    try:
        return await _append_extract_event(ctx, shard_iri, model, signing_key=signing_key,
                                           did=did)
    except Exception as exc:  # noqa: BLE001 - reported per unit; the run continues
        return f"{EVENT_FAILED_PREFIX}{type(exc).__name__}"


async def _append_extract_event(
    ctx: CorpusStorageContext,
    shard_iri: str,
    model: str,
    *,
    signing_key: Ed25519PrivateKey,
    did: str,
) -> str:
    from folio_insights.governance.cli._signing import sign_and_verify_event
    from folio_insights.governance.events import ExtractEvent
    from folio_insights.identity.cache import InMemoryDidDocCache
    from folio_insights.shards import AttestedSignature

    op = extract_event_op_id(shard_iri)
    if await ctx.committed_governance_op(op) is not None:
        return EVENT_EXISTING
    now = datetime.now(UTC)
    key_id = f"{did}#{did.removeprefix('did:key:')}"
    event = ExtractEvent(
        corpus=ctx.corpus,
        signature=AttestedSignature(did=did, action="extract", signed_at=now,
                                    signing_key_id=key_id),
        shard_iri=shard_iri,
        extractor_model=model,
    )
    signature = await sign_and_verify_event(
        event, signing_key=signing_key, did=did, action="extract", signing_key_id=key_id,
        did_doc_snapshot_at=None, now=now, cache=InMemoryDidDocCache(),
    )
    await ctx.governance.append(event.model_copy(update={"signature": signature}), op_id=op)
    return EVENT_APPENDED


def _storage_refusals() -> tuple[type[BaseException], ...]:
    from folio_insights.models.framework import MalformedFrameworkId, UnregisteredFramework
    from folio_insights.revision.acyclicity import DependencyCycle
    from folio_insights.shards.iri_registry import ShardIRICollision
    from folio_insights.storage.errors import (
        OperationIdConflict,
        PiiRejected,
        ShaclViolation,
        ShardIdentityViolation,
        ShardRecordInvalid,
    )

    return (ShaclViolation, PiiRejected, ShardRecordInvalid, ShardIdentityViolation,
            OperationIdConflict, DependencyCycle, UnregisteredFramework, MalformedFrameworkId,
            ShardIRICollision)


# ── the run ──────────────────────────────────────────────────────────────


async def mint_run(
    root: Path | str,
    corpus: str,
    extraction_json: Path | str,
    *,
    sources_dir: Path | str,
    llm: LLMPort | None,
    source_visibility: str,
    signing_key: Ed25519PrivateKey | None = None,
    extractor_did: str | None = None,
    llm_context: LLMRunContext | None = None,
    run_id: str | None = None,
    source_namespace: str | None = None,
    framework_id: str | None = None,
    framework_default: str | None = None,
    oracle: IriOracle | None = None,
    field_floors: FieldFloors | None = None,
    llm_fallbacks: bool = True,
    dry_run: bool = False,
    iri_registry: Path | str | None = None,
    config: StorageConfig | None = None,
    score_rubric: bool = True,
    support: SupportPolicy | None = None,
    require_iri_oracle: bool = True,
) -> MintReport:
    """Mint ``extraction_json``'s eligible units into ``corpus`` (module docstring).

    ``llm`` is the LLM port (``None``: every eligible unit is refused
    ``field_inference_unavailable``); calls use ``llm_context`` when given (it is
    installed for the run), else the current context. ``extractor_did`` is the
    ``first_extractor_did`` when no signing key is given (with a key it must be
    the key's did:key, or omitted). ``framework_id`` is the sources' explicit
    framework (v1-style IDs are migrated with warnings; default: the run's own
    ``framework_id`` field, if any); ``framework_default`` the corpus default.
    ``oracle`` checks every carried IRI's existence and branch before the write,
    types tag ancestry for BFO and scores RUB-EXTRACT-03; a non-dry run without one
    is refused (``MintRefused("iri_oracle_required")``) unless ``require_iri_oracle``
    is false, which the report flags ``iri_unchecked``. ``support`` is the
    claim-support policy (``minting.support``; default lexical floor 0.6, NLI off);
    an NLI check that cannot run refuses the run (``MintRefused("nli_unavailable")``).
    ``dry_run`` evaluates eligibility and identity only: no LLM call, no write.
    """
    from contextlib import nullcontext

    from folio_insights.llm.context import current_context, use_context

    check_visibility(root, corpus, source_visibility)  # R5: before anything else
    if oracle is None and require_iri_oracle and not dry_run:
        raise MintRefused(
            "iri_oracle_required",
            "a mint needs an IRI oracle (--oracle folio or --oracle FILE) to check that every "
            "carried IRI exists in its claimed branch; pass --no-iri-oracle to mint without "
            "the check (recorded in the report as an unchecked risk). Nothing was called or "
            "written.",
        )
    run = load_run(extraction_json)
    if not Path(sources_dir).is_dir():
        raise MintError(f"sources directory not found: {sources_dir}")
    did = _extractor_identity(signing_key, extractor_did)
    namespace = source_namespace or str(run.data.get("corpus") or "")
    if not namespace:
        raise MintError("the extraction run names no corpus; pass a source namespace")
    try:
        policy = (support or SupportPolicy()).resolve_scorer()
    except SupportUnavailable as exc:
        raise MintRefused(
            "nli_unavailable",
            f"the NLI support check was requested but cannot run ({exc}); it is never "
            "skipped silently. Nothing was called or written.",
        ) from None

    with use_context(llm_context) if llm_context is not None else nullcontext():
        try:
            return await _mint(
                Path(root), corpus, run,
                sources_dir=Path(sources_dir), llm=llm, llm_ctx=llm_context or current_context(),
                source_visibility=source_visibility, signing_key=signing_key, did=did,
                run_id=run_id or default_run_id(run), namespace=namespace,
                framework_id=framework_id or _run_framework_id(run),
                framework_default=framework_default, oracle=oracle,
                floors=field_floors or FieldFloors(), llm_fallbacks=llm_fallbacks,
                dry_run=dry_run,
                registry_path=Path(iri_registry) if iri_registry else Path(root) / REGISTRY_FILENAME,
                config=config, score_rubric=score_rubric, support=policy,
            )
        except SupportUnavailable as exc:
            raise MintRefused(
                "nli_unavailable",
                f"the NLI support check failed during minting ({exc}); completed writes "
                "remain, and no further units will be minted. Re-run after restoring the scorer.",
            ) from None


def _extractor_identity(signing_key: Ed25519PrivateKey | None, extractor_did: str | None) -> str:
    if signing_key is not None:
        from folio_insights.kernel.seed import did_for_signing_key

        derived = did_for_signing_key(signing_key)
        if extractor_did and extractor_did != derived:
            raise MintError("the extractor DID is not the did:key of the signing key")
        return derived
    if not extractor_did:
        raise MintError("an unsigned mint needs an extractor DID (--extractor-did) to record "
                        "as each shard's first_extractor_did")
    if not extractor_did.startswith("did:"):
        raise MintError(f"extractor DID must be a DID; got {extractor_did!r}")
    return extractor_did


def _run_framework_id(run: LoadedRun) -> str | None:
    for source in (run.data, run.summary):
        value = source.get("framework_id")
        if isinstance(value, str) and value:
            return value
    return None


async def _mint(
    root: Path,
    corpus: str,
    run: LoadedRun,
    *,
    sources_dir: Path,
    llm: LLMPort | None,
    llm_ctx: LLMRunContext,
    source_visibility: str,
    signing_key: Ed25519PrivateKey | None,
    did: str,
    run_id: str,
    namespace: str,
    framework_id: str | None,
    framework_default: str | None,
    oracle: IriOracle | None,
    floors: FieldFloors,
    llm_fallbacks: bool,
    dry_run: bool,
    registry_path: Path,
    config: StorageConfig | None,
    score_rubric: bool,
    support: SupportPolicy,
) -> MintReport:
    from folio_insights.frameworks.detector import (
        FrameworkDetector,
        PortFrameworkLLM,
        SourceMetadata,
    )
    from folio_insights.frameworks.registry import open_framework_checked_context
    from folio_insights.governance.authorize import Deny, authorize
    from folio_insights.kernel.catalog import is_kernel_iri
    from folio_insights.kernel.seed import extract_signature
    from folio_insights.llm.port import TaskLLM
    from folio_insights.models.framework import UnregisteredFramework
    from folio_insights.rubric.adapters import SourceResolver
    from folio_insights.shards.iri_registry import ShardIRIRegistry
    from folio_insights.shards.minting import mint_shard_iri
    from folio_insights.storage.journal import JOURNAL_FILENAME, committed_corpora

    report = MintReport(
        run_id=run_id, corpus=corpus, extraction=run.path.name,
        source_visibility=source_visibility, extractor_did=did,
        signed=signing_key is not None, dry_run=dry_run,
        iri_oracle="none" if oracle is None else type(oracle).__name__,
        support_policy={"method": support.method, "min_recall": support.min_recall,
                        **({"nli_threshold": support.nli_threshold,
                            "scorer": getattr(support.scorer, "name", None)}
                           if support.nli else {})},
    )
    if signing_key is None and not dry_run:
        report.flags.append(FLAG_UNATTESTED)
        report.notes.append("no signing key: shards are unsigned and ExtractEvents were "
                            "skipped (the governance log accepts only signed, authorized "
                            "events); first_extractor_did is unattested")
    if oracle is None:
        report.flags.append(FLAG_IRI_UNCHECKED)
        report.notes.append("no IRI oracle: carried IRIs were not checked to exist in their "
                            "claimed FOLIO branch (unchecked risk)")
    evidence = RunEvidence.from_extraction(run.data)
    resolver = SourceResolver(sources_dir)
    registry = ShardIRIRegistry(registry_path)
    storage_refusals = _storage_refusals()

    ctx: CorpusStorageContext | None = None
    guard = None
    if not dry_run or corpus in committed_corpora(root / JOURNAL_FILENAME):
        ctx, guard = await open_framework_checked_context(root, corpus, config=config)
    try:
        if ctx is not None and signing_key is not None:
            decision = await authorize(did, "extract", corpus, log=ctx.governance)
            if isinstance(decision, Deny):
                raise MintRefused(
                    "extractor_unauthorized",
                    f"{did} may not extract in corpus {corpus!r} ({decision.reason}); grant it "
                    "the extractor role first. Nothing was called or written.",
                )
        from folio_insights.models.framework import FrameworkRegistry

        registry_view = guard.registry if guard is not None else FrameworkRegistry.with_defaults()
        try:
            detector = FrameworkDetector(
                registry_view, corpus_default=framework_default,
                llm=PortFrameworkLLM(TaskLLM("framework_detector", port=llm))
                if (llm is not None and llm_fallbacks) else None,
            )
        except UnregisteredFramework as exc:
            raise MintError(f"framework default {framework_default!r} is not registered in "
                            f"corpus {corpus!r}: {exc}") from None
        classifier = strict_classifier(
            resolver=OracleBranchResolver(oracle) if oracle is not None else None,
            llm=_bfo_llm(llm) if (llm is not None and llm_fallbacks) else None,
        )

        seen: set[str] = set()
        detections: dict[str, _Detection] = {}
        halted: RunHalted | None = None

        def refuse(unit_id: str, refusal: Refused, support_metrics: Any = None) -> None:
            measured = refusal.support or support_metrics
            report.units.append(UnitOutcome(
                unit_id, REFUSED, code=refusal.code, detail=refusal.detail,
                reasons=refusal.reasons,
                support=measured.as_dict() if measured is not None else None,
            ))

        for raw, unit in run.units:
            stored = "anchor_score" in raw or "anchor_verified" in raw
            outcome = evaluate(unit, resolver.resolve_path, run=evidence, seen=seen,
                               stored_anchor=stored, oracle=oracle, support=support)
            if isinstance(outcome, Refused):
                refuse(unit.id, outcome)
                continue
            eligible: Eligible = outcome
            metrics = eligible.support.as_dict() if eligible.support is not None else None
            source_uri = source_uri_for(namespace, eligible.source_key)
            shard_iri, provenance = mint_shard_iri(source_uri, eligible.verified_span)

            refs = sorted({r for r in unit.cross_references if r.startswith(SHARD_IRI_PREFIX)})
            missing = [r for r in refs if ctx is None or await ctx.shards.get(r) is None]
            if missing:
                refuse(unit.id, Refused.single(
                    DEPENDENCY_UNRESOLVED,
                    f"{len(missing)} cross-referenced shard IRI(s) are not in the corpus",
                ), eligible.support)
                continue

            existing = await ctx.shards.get(shard_iri) if ctx is not None else None
            if existing is not None:
                event = (EVENT_UNSIGNED_SKIPPED if dry_run else await _ensure_extract_event(
                    ctx, shard_iri, existing.extractor_model, signing_key=signing_key, did=did,
                    first_extractor_did=existing.first_extractor_did))
                report.units.append(UnitOutcome(
                    unit.id, ALREADY_PRESENT, shard_iri=shard_iri,
                    extract_event=None if dry_run else event,
                    extraction_prompt_hash=existing.extraction_prompt_hash,
                    anchor_method=eligible.method, support=metrics,
                ))
                continue
            if dry_run:
                report.units.append(UnitOutcome(unit.id, ELIGIBLE, shard_iri=shard_iri,
                                                anchor_method=eligible.method, support=metrics))
                continue
            if halted is not None:
                refuse(unit.id, Refused.single(
                    FIELD_INFERENCE_UNAVAILABLE,
                    f"the LLM run halted earlier ({getattr(halted, 'kind', type(halted).__name__)})",
                ), eligible.support)
                continue

            try:
                if eligible.source_key not in detections:
                    detections[eligible.source_key] = await _detect(
                        detector, llm_ctx, SourceMetadata(framework_id=framework_id,
                                                          title=eligible.source_key))
                detected = detections[eligible.source_key]
                detection, framework_refusal = detected.detection, detected.refusal
                if detection is not None:
                    report.framework_migration_warnings.extend(detection.migration_warnings)
                if framework_refusal is not None:
                    refuse(unit.id, framework_refusal, eligible.support)
                    continue
                n_before = len(llm_ctx.records)
                fields = await infer_fields(unit, eligible, port=llm, context=llm_ctx,
                                            floors=floors)
                if isinstance(fields, Refused):
                    refuse(unit.id, fields, eligible.support)
                    continue
                invented = _fields_specifics_refusal(fields.values, eligible.verified_span)
                if invented is not None:
                    refuse(unit.id, invented, eligible.support)
                    continue
                bfo = await classify_bfo(classifier, eligible, fields.values["speech_act"],
                                         subject=unit.text)
            except RunHalted as exc:
                halted = exc
                refuse(unit.id, Refused.single(
                    FIELD_INFERENCE_UNAVAILABLE,
                    f"the LLM run halted ({getattr(exc, 'kind', type(exc).__name__)})",
                ), eligible.support)
                continue
            if isinstance(bfo, Refused):
                refuse(unit.id, bfo, eligible.support)
                continue

            # The unit's own calls (fields, BFO fallback) plus every call the per-source
            # framework detection made, whichever unit happened to trigger it (R4).
            calls = [r for r in llm_ctx.records[n_before:] if r.status == "ok"]
            minter_hashes = {MINT_FIELDS.hash, *detected.template_hashes,
                             *(r.template_hash for r in calls)}
            routes = {f"{fields.provider}:{fields.model}", *detected.routes,
                      *(f"{r.usage.provider}:{r.usage.model}" for r in calls)}
            model = extractor_model(unit, routes, run.summary)
            p_hash = prompt_hash(unit, minter_hashes)
            confidence = min(eligible.match, detection.confidence, fields.min_confidence)
            try:
                registered = await registry.register(source_uri, eligible.verified_span)
                if registered != shard_iri:  # pragma: no cover - the recipe is one function
                    raise RuntimeError("the IRI registry minted a different IRI")
                shard = build_shard(
                    unit, eligible,
                    shard_iri=shard_iri, provenance_hash=provenance, source_uri=source_uri,
                    fields=fields.values, framework_id=detection.framework_id,
                    bfo_category=bfo.category, extractor_did=did, extractor_model=model,
                    extraction_prompt_hash=p_hash, confidence=confidence,
                    extracted_at=datetime.now(UTC),
                    depends_on=dependency_fields(refs, is_kernel=is_kernel_iri),
                    valid_time_start=detection.valid_time.start if detection.valid_time else None,
                    valid_time_end=detection.valid_time.end if detection.valid_time else None,
                )
                if signing_key is not None:
                    shard = shard.model_copy(update={"signatures": [
                        extract_signature(shard, signing_key=signing_key, did=did)
                    ]})
                await ctx.ingest_shards([shard], op_id=mint_op_id(run_id, eligible, unit))
            except storage_refusals as exc:
                refuse(unit.id, Refused.single(f"{STORAGE_REFUSED}:{type(exc).__name__}",
                                               "the framework-checked storage context refused "
                                               "the shard; nothing was written for this unit"),
                       eligible.support)
                continue
            event = await _ensure_extract_event(ctx, shard_iri, model,
                                                signing_key=signing_key, did=did)
            report.units.append(UnitOutcome(
                unit.id, MINTED, shard_iri=shard_iri, extract_event=event,
                extraction_prompt_hash=p_hash, anchor_method=eligible.method,
                support=metrics,
            ))
    finally:
        if ctx is not None:
            await ctx.close()

    if llm_ctx.records:
        report.cost = llm_ctx.usage_summary()
    if score_rubric and not dry_run:
        report.rubric = await rubric_section(root, corpus, report.shard_iris(),
                                             sources_dir=sources_dir, oracle=oracle)
    return report


@dataclass(frozen=True)
class _Detection:
    """One source's framework detection and the LLM calls it made (R4: part of every
    unit's prompt identity and route set, not only the unit that triggered it)."""

    detection: Any
    refusal: Refused | None
    template_hashes: frozenset[str]
    routes: frozenset[str]


async def _detect(detector: Any, llm_ctx: LLMRunContext, metadata: Any) -> _Detection:
    n_before = len(llm_ctx.records)
    detection, refusal = await detect_framework(detector, metadata)
    calls = [r for r in llm_ctx.records[n_before:] if r.status == "ok"]
    return _Detection(
        detection, refusal,
        frozenset(r.template_hash for r in calls if r.template_hash),
        frozenset(f"{r.usage.provider}:{r.usage.model}" for r in calls),
    )


#: The inferred fields whose specifics must occur in the verified slice. ``sense`` and
#: ``reference`` restate the claim; an LLM that adds a citation, number or name there
#: invents exactly as a distiller would. (``logical_form_imputed`` is a formula and the
#: remaining fields are enums.)
SPECIFICS_CHECKED_FIELDS: tuple[str, ...] = ("sense", "reference")


def _fields_specifics_refusal(values: Mapping[str, str], span: str) -> Refused | None:
    reasons = []
    for name in SPECIFICS_CHECKED_FIELDS:
        missing = unsupported_specifics_only(values.get(name, ""), span)
        if missing:
            reasons.append((name, missing))
    if not reasons:
        return None
    from folio_insights.minting.eligibility import Reason

    return Refused.of(
        Reason(UNSUPPORTED_SPECIFICS,
               f"the inferred {name} states specifics the verified passage lacks: "
               + ", ".join(missing))
        for name, missing in reasons
    )


def _bfo_llm(port: LLMPort) -> Any:
    from folio_insights.bfo.classifier import PortBfoLLM
    from folio_insights.llm.port import TaskLLM

    return PortBfoLLM(TaskLLM("bfo_classifier", port=port))


__all__ = [
    "LOCAL_ONLY_DIRNAME",
    "NON_PUBLIC",
    "PUBLIC",
    "REGISTRY_FILENAME",
    "SOURCE_VISIBILITIES",
    "LoadedRun",
    "MintError",
    "MintRefused",
    "check_visibility",
    "default_run_id",
    "is_local_only",
    "load_run",
    "local_only_marker",
    "mark_local_only",
    "mint_run",
]
