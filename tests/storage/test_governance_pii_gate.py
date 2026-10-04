"""Governance events pass the PII gate before the journal append (governance plan U3).

Regression for a known gap: ``_append_governance`` verified signatures and ran
the Phase 11 hook, but never ran the configured PII gate that shards and
proposal-ledger operations pass. A signed event carrying a synthetic SSN or
phone number in a free-text field, or in its op_id, must be refused before
anything is appended, and the sensitive token must never reach disk.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from folio_insights.governance.events import ContestEvent
from folio_insights.storage import CorpusStorageContext, PiiGate, PiiRejected, StorageConfig

from tests.storage.conftest import _unsigned, at, genesis, sign_event

pytestmark = pytest.mark.storage

SHARD = "https://folio-insights.test/shard/synthetic-1"


def _contest(admin, text: str) -> ContestEvent:
    event = ContestEvent(
        corpus="corpus-a",
        signature=_unsigned(admin.did, "contest", at(5)),
        shard_iri=SHARD,
        voter_did=admin.did,
        position_text=text,
    )
    return sign_event(event, admin, at(5))


def _assert_not_on_disk(root: Path, needle: str) -> None:
    for path in root.rglob("*"):
        if path.is_file():
            assert needle.encode() not in path.read_bytes(), f"{needle!r} found in {path}"


@pytest.mark.parametrize(
    ("text", "token", "pattern"),
    [
        ("Synthetic position: call (212) 555-0142.", "555-0142", "us_phone"),
        ("Synthetic position: SSN 123-45-6789.", "123-45-6789", "ssn"),
    ],
)
async def test_signed_governance_event_with_pii_is_refused_before_append(
    storage_root: Path, admin, text: str, token: str, pattern: str
) -> None:
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        await ctx.governance.append(genesis("corpus-a", admin))
        head = (await ctx.status()).journal_head
        with pytest.raises(PiiRejected) as info:
            await ctx.governance.append(_contest(admin, text))
        assert info.value.pattern_name == pattern
        assert token not in str(info.value)
        assert "position_text" in str(info.value)
        assert (await ctx.status()).journal_head == head
        assert await ctx.governance.latest_position("corpus-a") == 0
    _assert_not_on_disk(storage_root, token)


async def test_governance_op_id_is_scanned(storage_root: Path, admin) -> None:
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        with pytest.raises(PiiRejected) as info:
            await ctx.governance.append(
                genesis("corpus-a", admin), op_id="genesis-for (212) 555-0142"
            )
        assert info.value.pattern_name == "us_phone"
        assert (await ctx.status()).journal_head == -1
    _assert_not_on_disk(storage_root, "555-0142")


async def test_signatures_and_clean_events_still_pass(storage_root: Path, admin) -> None:
    """The gate does not trip on signature material, DIDs or timestamps."""
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        committed = await ctx.governance.append(genesis("corpus-a", admin))
        assert committed.position == 0


async def test_disabled_gate_is_an_explicit_choice_for_events(storage_root: Path, admin) -> None:
    """With the gate explicitly disabled the same signed event is accepted, so
    the refusals above come from the gate and not from authorization."""
    config = StorageConfig(pii_gate=PiiGate(patterns=()))
    async with await CorpusStorageContext.open(storage_root, "corpus-a", config=config) as ctx:
        await ctx.governance.append(genesis("corpus-a", admin))
        committed = await ctx.governance.append(
            _contest(admin, "Synthetic position: SSN 123-45-6789.")
        )
        assert committed.position == 1
