"""Phase 03 GlossShard (REQ SHARD-05; PRD §6.2.4).

Covers exit criterion 2 (Gloss parses + validates) + CONTEXT D-05: glosses IRI
format validation (urn:folio:shard/<16-hex> OR http(s)://...), no self-glossing,
non-empty gloss_text, 5-value GlossKind enumeration.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from folio_insights.shards import GlossShard

from tests.shards.conftest import _sample_shard

pytestmark = pytest.mark.shards

_GLOSS_KINDS = ["clarificatoria", "extensiva", "restrictiva", "dissentiens", "historica"]


@pytest.mark.parametrize("kind", _GLOSS_KINDS)
def test_each_gloss_kind_constructs(kind: str) -> None:
    """D-05: all 5 GlossKind values construct successfully."""
    shard = _sample_shard(GlossShard, gloss_kind=kind)
    assert shard.gloss_kind == kind


def test_invalid_gloss_kind_rejected() -> None:
    """D-05: GlossKind Literal[5] rejects unknown values."""
    with pytest.raises(ValidationError):
        _sample_shard(GlossShard, gloss_kind="marginalia")


@pytest.mark.parametrize("iri", [
    "urn:folio:shard/0123456789abcdef",
    "urn:folio:shard/fedcba9876543210",
    "https://example.com/shard/1",
    "http://example.com/shard/2",
    "https://folio.example.com/legacy/shard/abc",
])
def test_valid_glosses_iri_accepted(iri: str) -> None:
    """D-05: valid IRI shapes (urn:folio:shard/<16-hex> OR http(s)://...) accepted."""
    shard = _sample_shard(GlossShard, glosses=iri)
    assert shard.glosses == iri


@pytest.mark.parametrize("iri", [
    "",
    "urn:folio:shard/zzzzzzzzzzzzzzzz",     # non-hex
    "urn:folio:shard/0123",                  # too short
    "urn:folio:shard/0123456789abcdef0",     # too long (17 chars)
    "ftp://example.com/shard/1",             # wrong scheme
    "urn:other:shard/0123456789abcdef",      # wrong urn namespace
    "shard/0123456789abcdef",                # missing scheme
    # REVIEW IN-02 (Phase 03): boundary case — http(s) regex requires ≥1 non-ws char
    # AFTER the scheme. "https://" alone must reject; this locks the [^\s]+ guard.
    "https://",
])
def test_invalid_glosses_iri_rejected(iri: str) -> None:
    """D-05: malformed IRI shapes raise ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        _sample_shard(GlossShard, glosses=iri)
    msg = str(exc_info.value)
    assert "glosses" in msg or "urn:folio:shard" in msg


def test_self_glossing_rejected() -> None:
    """D-05: glosses == self.shard_iri raises (no self-glossing)."""
    # Construct a fixture shard, then attempt to mutate glosses to its own shard_iri.
    shard = _sample_shard(GlossShard)
    iri = shard.shard_iri
    with pytest.raises(ValidationError) as exc_info:
        _sample_shard(GlossShard, glosses=iri)
    msg = str(exc_info.value)
    assert "self" in msg.lower() or "glosses" in msg


@pytest.mark.parametrize("text", ["", "   ", "\t\n"])
def test_empty_gloss_text_rejected(text: str) -> None:
    """D-05: gloss_text must not be empty/whitespace-only."""
    with pytest.raises(ValidationError) as exc_info:
        _sample_shard(GlossShard, gloss_text=text)
    msg = str(exc_info.value)
    assert "gloss_text" in msg


def test_gloss_round_trip() -> None:
    """GlossShard round-trips via model_dump + model_validate."""
    original = _sample_shard(GlossShard)
    rehydrated = GlossShard.model_validate(original.model_dump())
    assert rehydrated == original
