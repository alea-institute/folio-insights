"""PII ingest gate: synthetic SSN, ABA and phone inputs are refused on every
ingest path before the journal append; both stores stay unchanged."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from folio_insights.storage import CorpusStorageContext, PiiGate, PiiRejected, StorageConfig
from folio_insights.storage.journal import JOURNAL_FILENAME
from folio_insights.storage.pii import (
    ABA_ROUTING_PATTERN,
    SSN_PATTERN,
    US_PHONE_PATTERN,
)

from tests.storage.conftest import shard

pytestmark = pytest.mark.storage

# Synthetic values: 123-45-6789 is the canonical SSN example; 555-01xx is the
# fictional exchange; 110000000 is a checksum-valid routing number built for
# this test.
SYNTHETIC_PII = {
    "ssn": "Claimant SSN 123-45-6789 on file.",
    "aba_routing": "Wire to routing 110000000 today.",
    "us_phone": "Call (212) 555-0142 for details.",
}
# The sensitive token inside each sentence (must never reach disk).
SENSITIVE = {"ssn": "123-45-6789", "aba_routing": "110000000", "us_phone": "555-0142"}
PERMITTED = [
    "Rule 404(b) and 42 U.S.C. 1983 apply.",
    "Docket 123456789 is not a routing number.",  # fails the ABA checksum
    "Filed 2026-05-01; see page 212-215.",
    "Version 0.123456789 of the record.",
]


def test_default_patterns() -> None:
    assert SSN_PATTERN.matches(SYNTHETIC_PII["ssn"])
    assert ABA_ROUTING_PATTERN.matches(SYNTHETIC_PII["aba_routing"])
    assert US_PHONE_PATTERN.matches(SYNTHETIC_PII["us_phone"])
    assert US_PHONE_PATTERN.matches("+1 212.555.0142")
    assert not SSN_PATTERN.matches("000-12-3456")  # never-issued area
    gate = PiiGate()
    for text in PERMITTED:
        gate.check({"sense": text})


def test_gate_is_configurable() -> None:
    PiiGate(patterns=()).check({"sense": SYNTHETIC_PII["ssn"]})  # explicitly disabled
    custom = PiiGate.from_mapping({"employee_id": r"\bEMP-\d{6}\b"})
    with pytest.raises(PiiRejected) as info:
        custom.check({"reference": "EMP-123456"})
    assert info.value.pattern_name == "employee_id"
    with pytest.raises(PiiRejected):
        custom.check({"sense": SYNTHETIC_PII["us_phone"]})  # defaults still apply


async def _snapshot(ctx: CorpusStorageContext) -> tuple[int, int, list]:
    status = await ctx.status()
    quads = await ctx.query("SELECT ?s ?p ?o WHERE { ?s ?p ?o } ORDER BY ?s ?p ?o")
    return status.journal_head, status.projection_watermark, [tuple(map(str, r.values())) for r in quads]


def _assert_not_retained(root: Path, needle: str) -> None:
    for path in root.rglob("*"):
        if path.is_file():
            assert needle.encode() not in path.read_bytes(), f"{needle!r} found in {path}"


@pytest.mark.parametrize("pattern_name", sorted(SYNTHETIC_PII))
@pytest.mark.parametrize("path", ["create", "revise", "bulk", "bulk_legacy"])
async def test_pii_refused_on_every_ingest_path(
    storage_root: Path, pattern_name: str, path: str
) -> None:
    text = SYNTHETIC_PII[pattern_name]
    ctx = await CorpusStorageContext.open(storage_root, "corpus-a")
    try:
        existing = shard(1)
        await ctx.shards.put(existing.shard_iri, existing)
        before = await _snapshot(ctx)

        with pytest.raises(PiiRejected) as info:
            if path == "create":
                bad = shard(2, sense=text)
                await ctx.shards.put(bad.shard_iri, bad)
            elif path == "revise":
                bad = shard(1, reference=text)
                await ctx.shards.put(bad.shard_iri, bad)
            elif path == "bulk":
                await ctx.ingest_shards([shard(3), shard(4, source_span=text)])
            else:
                legacy = json.loads(shard(5).model_dump_json())
                del legacy["schema_version"]
                legacy["sense"] = text
                await ctx.ingest_shards([shard(6), json.dumps(legacy).encode()])
        assert info.value.pattern_name == pattern_name
        assert text not in str(info.value)

        assert await _snapshot(ctx) == before
        assert await ctx.shards.get(shard(3).shard_iri) is None
    finally:
        await ctx.close()
    _assert_not_retained(storage_root, SENSITIVE[pattern_name])


async def test_permitted_inputs_persist(storage_root: Path) -> None:
    ctx = await CorpusStorageContext.open(storage_root, "corpus-a")
    try:
        records = [shard(10 + i, sense=text) for i, text in enumerate(PERMITTED)]
        await ctx.ingest_shards(records[:2])
        for r in records[2:]:
            await ctx.shards.put(r.shard_iri, r)
        assert sorted([s.sense async for s in ctx.shards.iter_shards()]) == sorted(PERMITTED)
    finally:
        await ctx.close()


async def test_disabled_gate_is_an_explicit_choice(storage_root: Path) -> None:
    ctx = await CorpusStorageContext.open(
        storage_root, "corpus-a", config=StorageConfig(pii_gate=PiiGate(patterns=()))
    )
    try:
        s = shard(1, sense=SYNTHETIC_PII["ssn"])
        await ctx.shards.put(s.shard_iri, s)
        assert (await ctx.shards.get(s.shard_iri)).sense == SYNTHETIC_PII["ssn"]
    finally:
        await ctx.close()
    assert (storage_root / JOURNAL_FILENAME).exists()


def test_integer_leaves_are_scanned() -> None:
    """Review P2-2: a checksum-valid routing number stored as a JSON integer
    is refused like the same digits in a string; booleans are not integers;
    an integer too large to render is refused (fail closed); the signature and
    digest exemptions still apply to strings only."""
    gate = PiiGate()
    with pytest.raises(PiiRejected, match="aba_routing") as err:
        gate.check({"payload": {"counts": [1, 110000000]}})
    assert "110000000" not in str(err.value)
    assert err.value.field_path == "payload.counts[1]"
    gate.check({"flag": True, "n": 42, "position": 2125550142})
    with pytest.raises(PiiRejected, match="unscannable_integer"):
        gate.check({"n": 1 << 20_000})
    gate.check({"signature": "A" * 86, "payload_hash": "a" * 64})
