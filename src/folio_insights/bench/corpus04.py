"""CORPUS-04 harness: benchmark corpora load, pass SHACL, pass cluster validation.

Phase 13 exit criterion 7 (CORPUS-04) needs three real benchmark corpora:
v1 advocacy, the Federal Rules of Evidence, and the Restatement of Contracts.
For each one, this harness:

1. loads it through storage (``CorpusStorageContext.bulk_load_shards``: the
   PII gate, model validation and the Phase 11 SHACL local tier on every
   record);
2. runs full SHACL validation (``validate_corpus``: every shard and event
   plus the corpus tier) and reads back ``status().full_shacl``;
3. runs cluster validation.

Corpus sources: ``<corpora_dir>/<name>.jsonl``, one shard record per line,
from ``corpora_dir`` or ``$FOLIO_INSIGHTS_CORPUS04_DIR``. A corpus with no
file runs on a deterministic synthetic stand-in, so the pipeline itself is
exercised. A stand-in can never satisfy CORPUS-04, and the report says so.

Cluster validation is the Phase 9.P1 cluster validator (owlready2 + HermiT,
worker tier). It is not built, so that step reports ``unavailable`` and
CORPUS-04 stays ``unmet`` even with real corpora until it lands.

No book-derived or production text is generated here: stand-in records are
synthetic placeholders.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

CORPORA: tuple[str, ...] = ("v1-advocacy", "fre", "restatement-contracts")
ENV_DIR = "FOLIO_INSIGHTS_CORPUS04_DIR"
CLUSTER_UNAVAILABLE = (
    "Phase 9.P1 cluster validator (owlready2 + HermiT, worker tier) is not built"
)


@dataclass(frozen=True)
class CorpusSource:
    name: str
    kind: str                 # "real" | "synthetic"
    records: list[Any]
    path: str | None = None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def synthetic_standin(name: str, shards: int = 300) -> list[dict[str, Any]]:
    """A deterministic synthetic stand-in: every subtype, a supersession pair
    with aligned valid time, signed and unsigned shards. Placeholder text only."""
    from folio_insights.shards import (
        AttestedSignature,
        AuthorityPosition,
        ConflictingAuthoritiesShard,
        DisputedPropositionShard,
        GlossShard,
        HypothesisShard,
        Objection,
        Reply,
        SimpleAssertionShard,
        Triple,
        mint_shard_iri,
    )

    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    out: list[dict[str, Any]] = []
    iris: list[str] = []
    for n in range(shards):
        uri = f"urn:x:standin:{name}"
        span = f"synthetic span {n}"
        iri, prov = mint_shard_iri(uri, span)
        iris.append(iri)
        base: dict[str, Any] = {
            "shard_iri": iri,
            "provenance_hash": prov,
            "source_uri": uri,
            "source_span": span,
            "extracted_at": t0 + timedelta(minutes=n),
            "first_extractor_did": "did:key:zStandinExtractor",
            "triple": Triple(subject=f"s{n}", predicate="p", object=f"o{n}"),
            "sense": f"synthetic sense {n}",
            "reference": f"urn:folio:concept/standin-{n % 17}",
            "logical_form_imputed": f"P{n % 5}(s, o)",
            "layer": ("L0_primitive", "L1_definitional", "L2_composed", "L3_jurisdictional")[n % 4],
            "predication_mode": ("per_se", "per_accidens")[n % 2],
            "fork": ("analytic", "synthetic_a_posteriori", "synthetic_a_priori")[n % 3],
            "epistemic_status": "authority_only",
            "verification_method": "textual_citation",
            "depends_on_shards": [iris[n - 1]] if n and n % 7 == 0 else [],
            "framework_id": f"standin.{name}",
            "speech_act": "holding",
            "extractor_version": "standin-1",
            "extraction_prompt_hash": "0" * 64,
            "extractor_model": "synthetic",
            "confidence": round(0.5 + (n % 50) / 100, 2),
            "bfo_category": "continuant_independent",
            "transaction_time": t0,
        }
        if n % 3 == 0:
            base["signatures"] = [
                AttestedSignature(
                    did="did:key:zStandinReviewer",
                    action="extract",
                    signed_at=t0,
                    signature="c3ludGhldGlj",
                    over_content_hash="a" * 64,
                    signing_key_id="did:key:zStandinReviewer#k",
                )
            ]
        kind = n % 5
        if kind == 1:
            shard: Any = DisputedPropositionShard(
                **base,
                utrum=f"Whether synthetic question {n} holds?",
                objections=[Objection(cites="urn:x:a1", argues="synthetic objection", strength=0.4)],
                sed_contra=Objection(cites="urn:x:a2", argues="synthetic contra", strength=0.7),
                respondeo="synthetic respondeo",
                replies=[Reply(objection_index=0, replies_via="distinguo", argument="synthetic reply")],
            )
        elif kind == 2:
            position = AuthorityPosition(
                authority_iri="urn:x:auth", position="synthetic position",
                jurisdiction="xx", weight="persuasive",
            )
            shard = ConflictingAuthoritiesShard(
                **base, sic=[position], non=[position],
                reconciliation_strategy="unreconciled", reconciliation_note="synthetic note",
            )
        elif kind == 3 and n > 3:
            shard = GlossShard(
                **base, glosses=iris[n - 1], gloss_kind="clarificatoria", gloss_text="synthetic gloss",
            )
        elif kind == 4:
            shard = HypothesisShard(**base, generation_method="inductive")
        else:
            shard = SimpleAssertionShard(**base)
        out.append(shard.model_dump(mode="json"))

    # One aligned supersession pair: old ends where new starts, both linked.
    if len(out) >= 2:
        boundary = (t0 + timedelta(days=30)).isoformat().replace("+00:00", "Z")
        old, new = out[0], out[1]
        old.update(valid_time_end=boundary, superseded_by=new["shard_iri"],
                   epistemic_status="superseded")
        new.update(valid_time_start=boundary, supersedes=old["shard_iri"])
        if new["shard_type"] == "disputed_proposition":
            new["epistemic_status"] = "authority_only"
    return out


def discover(corpora_dir: str | Path | None = None, *, standin_shards: int = 300) -> list[CorpusSource]:
    base = corpora_dir if corpora_dir is not None else os.environ.get(ENV_DIR)
    sources = []
    for name in CORPORA:
        path = Path(base) / f"{name}.jsonl" if base else None
        if path is not None and path.is_file():
            sources.append(CorpusSource(name, "real", _read_jsonl(path), str(path)))
        else:
            sources.append(CorpusSource(name, "synthetic", synthetic_standin(name, standin_shards)))
    return sources


def cluster_validation(_ctx: Any) -> dict[str, Any]:
    """Phase 9.P1 is not built; report that rather than claim a pass."""
    return {"status": "unavailable", "reason": CLUSTER_UNAVAILABLE}


async def run_corpus04(
    root: str | Path,
    *,
    corpora_dir: str | Path | None = None,
    standin_shards: int = 300,
) -> dict[str, Any]:
    """Load, SHACL-validate and cluster-validate each benchmark corpus under
    a storage ``root``; return a report whose ``corpus_04`` is ``met`` only
    when all three are real and every step passed."""
    from folio_insights.storage import CorpusStorageContext

    report: dict[str, Any] = {"corpora": [], "storage_root": str(root)}
    reasons: list[str] = []
    for source in discover(corpora_dir, standin_shards=standin_shards):
        ctx = await CorpusStorageContext.open(Path(root), source.name)
        try:
            started = time.perf_counter()
            loaded = await ctx.bulk_load_shards(source.records, op_id=f"corpus04:{source.name}")
            load_s = time.perf_counter() - started
            started = time.perf_counter()
            validation = await ctx.validate_corpus()
            validate_s = time.perf_counter() - started
            status = await ctx.status()
            cluster = cluster_validation(ctx)
        finally:
            await ctx.close()
        entry = {
            "name": source.name,
            "source": source.kind,
            "path": source.path,
            "records": loaded.records,
            "load_seconds": round(load_s, 3),
            "shacl": {
                "full_shacl": status.full_shacl,
                "conforms": validation.conforms,
                "violations": validation.violations,
                "warnings": validation.warnings,
                "validate_seconds": round(validate_s, 3),
            },
            "cluster_validation": cluster,
        }
        report["corpora"].append(entry)
        if source.kind != "real":
            reasons.append(f"{source.name}: synthetic stand-in (real corpus absent)")
        if status.full_shacl != "pass":
            reasons.append(f"{source.name}: full_shacl={status.full_shacl}")
        if cluster["status"] != "pass":
            reasons.append(f"{source.name}: cluster validation {cluster['status']}")
    report["corpus_04"] = "met" if not reasons else "unmet"
    report["unmet_reasons"] = reasons
    return report


__all__ = [
    "CLUSTER_UNAVAILABLE",
    "CORPORA",
    "ENV_DIR",
    "CorpusSource",
    "cluster_validation",
    "discover",
    "run_corpus04",
    "synthetic_standin",
]
