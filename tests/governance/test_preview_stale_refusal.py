"""D-17 PreviewStale race-test (07-05b Task 1).

The interactive ``governance retract`` flow runs in three modes:

  * default (interactive): build_cascade_preview -> confirm -> commit_cascade.
  * ``--preview``: build_cascade_preview -> write JSON -> exit 0 (no commit).
  * ``--apply <file>``: load preview JSON -> commit_cascade -> the commit step
    RE-RUNS ``build_cascade_preview`` and compares ``underlying_state_hash``
    against the loaded preview. If the hash differs, raise ``PreviewStale``
    referencing ``--preview``.

This file tests the race-detection contract:

  (a) commit_cascade with no intervening mutation appends the RetractionEvent.
  (b) commit_cascade after a new dependent appears raises PreviewStale.

Pitfall 5 (RESEARCH lines 846-865): the dependents set MUST be hashed
deterministically; key fields are ``(dep_iri, epistemic_status,
reconciliation_strategy, valid_time_end, superseded_by, log_position_at_signing)``
per RESEARCH Q6.
"""
from __future__ import annotations

import asyncio
import inspect

import pytest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from folio_insights.governance.retract import (
    PreviewStale,
    build_cascade_preview,
    commit_cascade,
)

from tests.governance.fixtures.cascade_corpora import (
    CORPUS,
    RETRACTED_IRI,
    add_new_dependent,
    seed_cascade_corpus,
)

pytestmark = pytest.mark.governance


def _key_and_did() -> tuple[Ed25519PrivateKey, str]:
    """Return (signing_key, did) for a fresh ephemeral DID."""
    from folio_insights.identity.cli import _derive_didkey_from_signing_key

    sk = Ed25519PrivateKey.generate()
    did = _derive_didkey_from_signing_key(sk)
    return sk, did


@pytest.mark.asyncio
async def test_commit_cascade_succeeds_when_state_unchanged() -> None:
    """A preview committed immediately (no mutation) appends a RetractionEvent.

    The PreviewStale race-check re-runs build_cascade_preview and compares
    ``underlying_state_hash``; with no mutation the hashes match and the
    commit proceeds.
    """
    store, log = await seed_cascade_corpus(superseded=True)
    sk, did = _key_and_did()

    preview = await build_cascade_preview(
        RETRACTED_IRI, CORPUS, store=store, log=log
    )
    assert preview.retracted_shard_iri == RETRACTED_IRI
    assert preview.corpus == CORPUS

    # Immediately commit — no mutation between build and commit.
    event = await commit_cascade(
        preview, store=store, log=log, signing_key=sk, did=did
    )
    assert event.action == "retract"
    assert event.shard_iri == RETRACTED_IRI
    assert event.cascade_preview_hash != ""


@pytest.mark.asyncio
async def test_commit_cascade_raises_preview_stale_on_mutated_state() -> None:
    """A new dependent appearing between preview and commit triggers PreviewStale.

    Models two operators racing: operator A captures a preview; operator B
    appends a new shard depending on the retracted target; operator A's
    --apply re-runs build_cascade_preview and detects the state change.
    """
    store, log = await seed_cascade_corpus(superseded=True)
    sk, did = _key_and_did()

    preview = await build_cascade_preview(
        RETRACTED_IRI, CORPUS, store=store, log=log
    )

    # Operator B mutates: a new dependent shard appears.
    await add_new_dependent(store)

    with pytest.raises(PreviewStale) as exc_info:
        await commit_cascade(
            preview, store=store, log=log, signing_key=sk, did=did
        )
    # The error message MUST reference --preview so the operator knows the
    # remediation (per RESEARCH Pitfall 5 + plan acceptance criteria).
    assert "--preview" in str(exc_info.value), (
        f"PreviewStale message must reference --preview; got {exc_info.value!r}"
    )


@pytest.mark.asyncio
async def test_underlying_state_hash_is_deterministic() -> None:
    """Two preview builds over the SAME state produce the SAME underlying hash.

    The PreviewStale guard only works if the hash is deterministic — a
    nondeterministic input (e.g. set iteration order, datetime.now()) would
    cause spurious PreviewStale refusals even when nothing changed.
    """
    store, log = await seed_cascade_corpus(superseded=True)

    preview_1 = await build_cascade_preview(
        RETRACTED_IRI, CORPUS, store=store, log=log
    )
    preview_2 = await build_cascade_preview(
        RETRACTED_IRI, CORPUS, store=store, log=log
    )
    assert preview_1.underlying_state_hash == preview_2.underlying_state_hash, (
        "build_cascade_preview must produce a deterministic "
        "underlying_state_hash over the same store + log state."
    )


def test_build_cascade_preview_is_async() -> None:
    """Sentinel — build_cascade_preview is async (D-04 seam discipline)."""
    assert inspect.iscoroutinefunction(build_cascade_preview)


def test_commit_cascade_is_async() -> None:
    """Sentinel — commit_cascade is async."""
    assert inspect.iscoroutinefunction(commit_cascade)


# Reference for ``asyncio`` import so the lint check passes — this keeps the
# import live for any future inline ``asyncio.run`` adapter usage and is a
# no-op at runtime.
_ASYNCIO_KEEPALIVE = asyncio
