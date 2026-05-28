"""DID-07 / EC5 ``what will I be signing?`` preview tests (Plan 06-03 Task 2 + 4).

Exit Criterion 5 acceptance: the preview renders canonical hash + human-readable
diff for **all 8 signed-action types** in the DID-07 governance subset:
``{extract, promote, demote, contest, supersede, retract, distinguo,
role_assertion}``.

The parametrized test exercises EVERY member of ``GOVERNANCE_ACTIONS`` (the
8-action subset locked in ``identity/preview.py``). For each it asserts the
preview surfaces:

* a 64-hex content_hash (the canonical_content_hash output shape);
* a non-empty human_readable line.

Plus a couple of structural tests around the renderer dispatch.
"""
from __future__ import annotations

import pytest

from folio_insights.identity import (
    GOVERNANCE_ACTIONS,
    SigningPreview,
    build_signing_preview,
)
from folio_insights.shards import SimpleAssertionShard
from folio_insights.shards.envelope import SignedAction
from tests.shards.conftest import _sample_shard

pytestmark = pytest.mark.identity


# ── EC5 — parametrize over the 8 governance actions (the exit criterion) ────


@pytest.mark.parametrize("action", list(GOVERNANCE_ACTIONS))
def test_preview_renders_for_each_governance_action(action: SignedAction) -> None:
    """EC5: ``build_signing_preview`` renders for every DID-07 governance action.

    Asserts the preview is a ``SigningPreview`` with:
    * a 64-hex SHA-256 content_hash (the canonical_content_hash shape);
    * a non-empty human_readable line (the operator sees SOMETHING).
    """
    shard = _sample_shard(SimpleAssertionShard)
    preview = build_signing_preview(action, shard)
    assert isinstance(preview, SigningPreview)
    assert preview.action == action
    # canonical_content_hash returns a SHA-256 hex (64 lowercase hex chars).
    assert len(preview.content_hash) == 64
    assert all(c in "0123456789abcdef" for c in preview.content_hash)
    assert preview.human_readable  # non-empty (Field(min_length=1) enforces)
    assert preview.shard_iri == shard.shard_iri


# ── GOVERNANCE_ACTIONS list pinned at 8 (EC5 contract) ──────────────────────


def test_governance_actions_is_exactly_8() -> None:
    """The DID-07 governance subset is exactly 8 actions (EC5 invariant)."""
    assert len(GOVERNANCE_ACTIONS) == 8
    assert set(GOVERNANCE_ACTIONS) == {
        "extract", "promote", "demote", "contest",
        "supersede", "retract", "distinguo", "role_assertion",
    }


# ── Outside-EC5 actions still render (audit-path / content_edit stub) ───────


@pytest.mark.parametrize(
    "action",
    ["content_edit", "reparent", "reconcile", "resolve_contest"],
)
def test_preview_renders_for_outside_ec5_actions(action: str) -> None:
    """The 4 OUTSIDE-EC5 actions still render — audit-stub paths must work."""
    shard = _sample_shard(SimpleAssertionShard)
    preview = build_signing_preview(action, shard)  # type: ignore[arg-type]
    assert isinstance(preview, SigningPreview)
    assert preview.human_readable


# ── content hash matches the actual canonical hash (signer parity) ─────────


def test_preview_content_hash_equals_canonical_content_hash() -> None:
    """The preview's content_hash IS the canonical_content_hash (signer parity).

    This is the load-bearing guarantee: the operator sees the EXACT value
    the signer will sign over, not a re-hash they have to trust.
    """
    from folio_insights.revision.content_edit import canonical_content_hash

    shard = _sample_shard(SimpleAssertionShard)
    preview = build_signing_preview("extract", shard)
    assert preview.content_hash == canonical_content_hash(shard)


# ── per-action change descriptors flow through to human_readable ────────────


def test_promote_uses_change_descriptor_in_human_readable() -> None:
    """The ``change`` dict propagates into the per-action renderer output."""
    shard = _sample_shard(SimpleAssertionShard)
    preview = build_signing_preview(
        "promote", shard, change={"to": "demonstrable"}
    )
    assert "demonstrable" in preview.human_readable
    assert "PROMOTE" in preview.human_readable


def test_content_edit_diff_shows_old_to_new() -> None:
    """For the edit-shaped action, the preview shows old → new field diff."""
    shard = _sample_shard(SimpleAssertionShard)
    preview = build_signing_preview(
        "content_edit",
        shard,
        change={"field_path": "sense", "old": "alpha", "new": "beta"},
    )
    assert "sense" in preview.human_readable
    assert "alpha" in preview.human_readable
    assert "beta" in preview.human_readable


# ── unknown action raises (defensive — Literal narrows but runtime is str) ──


def test_unknown_action_raises_value_error() -> None:
    """An unknown action string raises ValueError (defensive renderer dispatch)."""
    shard = _sample_shard(SimpleAssertionShard)
    with pytest.raises(ValueError, match="No preview renderer"):
        build_signing_preview("not_an_action", shard)  # type: ignore[arg-type]
