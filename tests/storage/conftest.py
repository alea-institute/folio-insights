"""Phase 13 storage test fixtures: disposable roots and generated identities.

Every signing identity is generated per test run (ed25519 ``did:key``); no
operator key or credential is read. Shards are synthetic
(``tests/shards/conftest.py`` builders). Subprocess helpers run
``tests/storage/_proc.py`` from the repository root.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from folio_insights.governance.events import (
    GovernanceEvent,
    RoleAssertionEvent,
    RoleRevocationEvent,
)
from folio_insights.identity import did_key_from_public
from folio_insights.identity.signer import sign_attestation
from folio_insights.shards import AttestedSignature, ShardEnvelope, SimpleAssertionShard
from folio_insights.storage import CorpusStorageContext, StorageConfig

from tests.shards.conftest import _sample_shard

REPO_ROOT = Path(__file__).resolve().parents[2]


def _signing_anchor() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


# The signing-time anchor ``at()`` offsets from. Governance appends are
# checked against the server clock (R17 / KTD12: ``signed_at`` must be within
# ``SIGNING_SKEW`` of the commit time), so signers here sign "now + a few
# seconds", like a real signer, instead of a fixed past date.
# ``fresh_signing_clock`` re-anchors it at the start of every test; a
# subprocess (``_proc.py``) anchors it at its own import.
T0 = _signing_anchor()


@pytest.fixture(autouse=True)
def fresh_signing_clock() -> None:
    """Re-anchor ``T0`` to the real clock for each test (autouse here;
    modules outside ``tests/storage`` that sign with ``at()`` import it)."""
    global T0
    T0 = _signing_anchor()


@dataclass(frozen=True)
class Identity:
    sk: Ed25519PrivateKey
    did: str

    @property
    def key_id(self) -> str:
        return f"{self.did}#{self.did.removeprefix('did:key:')}"

    def raw_private_hex(self) -> str:
        return self.sk.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        ).hex()

    @classmethod
    def from_raw_hex(cls, raw_hex: str) -> Identity:
        sk = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(raw_hex))
        return cls(sk, _did_for(sk))


def _did_for(sk: Ed25519PrivateKey) -> str:
    raw = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    return did_key_from_public(raw)


def new_identity() -> Identity:
    sk = Ed25519PrivateKey.generate()
    return Identity(sk, _did_for(sk))


def sign_event(event: GovernanceEvent, signer: Identity, signed_at: datetime) -> GovernanceEvent:
    """Sign ``event`` over its canonical payload with a generated identity."""
    placeholder = event.model_copy(
        update={
            "signature": AttestedSignature(
                did=signer.did,
                action=event.action,
                signed_at=signed_at,
                signing_key_id=signer.key_id,
            )
        }
    )
    sig = sign_attestation(
        placeholder.signature_payload().decode("utf-8"),
        signer.sk,
        signer.did,
        event.action,
        signing_key_id=signer.key_id,
        did_doc_snapshot_at=None,
        now=signed_at,
    )
    return placeholder.model_copy(update={"signature": sig})


def _unsigned(did: str, action: str, signed_at: datetime) -> AttestedSignature:
    return AttestedSignature(did=did, action=action, signed_at=signed_at)  # type: ignore[arg-type]


def role_assertion(
    corpus: str, signer: Identity, subject_did: str, role: str, signed_at: datetime
) -> RoleAssertionEvent:
    event = RoleAssertionEvent(
        corpus=corpus,
        signature=_unsigned(signer.did, "role_assertion", signed_at),
        subject_did=subject_did,
        role=role,  # type: ignore[arg-type]
    )
    return sign_event(event, signer, signed_at)  # type: ignore[return-value]


def role_revocation(
    corpus: str, signer: Identity, subject_did: str, role: str, signed_at: datetime
) -> RoleRevocationEvent:
    event = RoleRevocationEvent(
        corpus=corpus,
        signature=_unsigned(signer.did, "role_revocation", signed_at),
        subject_did=subject_did,
        revoked_role=role,  # type: ignore[arg-type]
    )
    return sign_event(event, signer, signed_at)  # type: ignore[return-value]


def genesis(
    corpus: str, admin: Identity, signed_at: datetime | None = None
) -> RoleAssertionEvent:
    return role_assertion(
        corpus, admin, admin.did, "corpus_admin", T0 if signed_at is None else signed_at
    )


def shard(n: int, **overrides: Any) -> ShardEnvelope:
    """A synthetic SimpleAssertionShard with a distinct IRI per ``n``."""
    defaults: dict[str, Any] = {
        "shard_iri": f"urn:folio:shard/{n:032x}",
        "sense": f"synthetic sense {n}",
    }
    defaults.update(overrides)
    return _sample_shard(SimpleAssertionShard, **defaults)


def at(seconds: int) -> datetime:
    return T0 + timedelta(seconds=seconds)


@pytest.fixture
def storage_root(tmp_path: Path) -> Path:
    return tmp_path / "storage"


@pytest.fixture
def admin() -> Identity:
    return new_identity()


@pytest_asyncio.fixture
async def ctx(storage_root: Path) -> AsyncIterator[CorpusStorageContext]:
    context = await CorpusStorageContext.open(storage_root, "corpus-a")
    try:
        yield context
    finally:
        await context.close()


async def open_ctx(
    root: Path, corpus: str = "corpus-a", **config: Any
) -> CorpusStorageContext:
    return await CorpusStorageContext.open(root, corpus, config=StorageConfig(**config))


def run_proc(*args: str, timeout: float = 25.0) -> dict[str, Any]:
    """Run ``python -m tests.storage._proc <args>`` and return its JSON stdout."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(REPO_ROOT / "src"), str(REPO_ROOT), env.get("PYTHONPATH", "")]
    )
    result = subprocess.run(
        [sys.executable, "-m", "tests.storage._proc", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"subprocess {args[0]} exited {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return json.loads(result.stdout.strip().splitlines()[-1])


def start_proc(*args: str) -> subprocess.Popen[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(REPO_ROOT / "src"), str(REPO_ROOT), env.get("PYTHONPATH", "")]
    )
    return subprocess.Popen(
        [sys.executable, "-m", "tests.storage._proc", *args],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
