"""Dedicated end-to-end test for ``folio-insights governance export`` (Issue #4).

This is the SOLE CLI-end-to-end verification owner for D-08 (on-demand Turtle
export). Per the Issue #4 closure (07-RESEARCH), this test ships in its OWN
file rather than folded into ``test_governance_log_exports_as_provo.py`` (the
07-03 seed) so the responsibility is unambiguous: any change to the export
CLI surface MUST update this file.

Covered:
  (a) Positive round-trip — seed 3 events, invoke ``governance export``,
      parse the output Turtle, assert >=3 ``prov:Activity`` triples each
      with a ``prov:wasAttributedTo`` predicate.
  (b) Negative authorization — an unauthorized DID gets a Deny from
      ``authorize()`` and the command exits non-zero.
  (c) AST-first-step — source-scans ``cli/export.py`` to assert
      ``await authorize(...)`` precedes any ``log.iter_events(...)`` call
      (D-19 applies even on the read path).

D-04 boundary: ``cli/export.py`` itself does NOT import rdflib — it
delegates to ``shape_validation.serialize_log_as_turtle`` (the lone exempt
module). This test imports rdflib directly to parse the output Turtle;
tests are exempt from the D-04 boundary.
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
from datetime import UTC, datetime

import pytest
from click.testing import CliRunner
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from rdflib import Graph, Namespace, RDF
from rdflib.namespace import RDF as RDF_NS  # noqa: F401 — explicit alias

from folio_insights.governance.cli import _state as _cli_state
from folio_insights.governance.events import (
    ExtractEvent,
    RoleAssertionEvent,
)
from folio_insights.governance.log import InMemoryGovernanceLog
from folio_insights.shards.envelope import AttestedSignature

pytestmark = pytest.mark.governance

PROV = Namespace("http://www.w3.org/ns/prov#")
FI = Namespace("https://folio-insights.example/")

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_EXPORT_CLI = _REPO_ROOT / "src/folio_insights/governance/cli/export.py"


def _sig(did: str, action: str, signed_at: datetime) -> AttestedSignature:
    return AttestedSignature(
        did=did,
        action=action,  # type: ignore[arg-type]
        signed_at=signed_at,
        signature="",
        over_content_hash="0" * 64,
        signing_key_id=f"{did}#key-1",
        did_doc_snapshot_at=signed_at,
        verified=None,
    )


def _derive_did(sk: Ed25519PrivateKey) -> str:
    from folio_insights.identity.cli import _derive_didkey_from_signing_key

    return _derive_didkey_from_signing_key(sk)


def _reset_log() -> None:
    """Reset the process-local governance log between tests (CliRunner shares it).

    Replaces the singleton (mirrors ``tests/corpus/test_corpus_init_genesis.py``)
    so the CLI's late-binding ``from ._state import GOVERNANCE_LOG`` always
    sees a fresh instance — clearing ``_by_corpus`` on the prior instance
    would only work if the singleton hadn't been replaced by an
    earlier-running test fixture (corpus tests DO replace it).
    """
    _cli_state.GOVERNANCE_LOG = InMemoryGovernanceLog()


async def _seed_admin_and_events(
    corpus: str, admin_did: str
) -> None:
    """Seed a corpus with a genesis admin + 3 ExtractEvents.

    The admin RoleAssertion at position 0 satisfies the authorize() gate
    for subsequent reads (export is an admin-permitted action per the
    extended D-19 action-permission table in 07-05b).
    """
    log = _cli_state.GOVERNANCE_LOG
    genesis_sig = _sig(admin_did, "role_assertion", datetime(2026, 1, 1, tzinfo=UTC))
    await log.append(
        RoleAssertionEvent(
            corpus=corpus,
            signature=genesis_sig,
            subject_did=admin_did,
            role="corpus_admin",
        )
    )
    for i, day in enumerate([2, 3, 4]):
        await log.append(
            ExtractEvent(
                corpus=corpus,
                signature=_sig(
                    admin_did, "extract", datetime(2026, 1, day, tzinfo=UTC)
                ),
                shard_iri=f"fi:shard:seed-{i}",
            )
        )


# ── (a) Positive round-trip ────────────────────────────────────────────────


def test_export_turtle_round_trip(tmp_path: pathlib.Path) -> None:
    """End-to-end: seed 3 events → invoke export → parse Turtle → assert
    ≥3 prov:Activity + prov:wasAttributedTo predicates.
    """
    _reset_log()
    # Generate a fresh key + DID for the operator. Persist to a tempfile so
    # the CLI's --key-path can load it (the CLI does Ed25519PrivateKey via
    # load_signing_key from JWK on disk).
    from folio_insights.identity.keys import generate_keypair

    key_path = tmp_path / "test-fi-key.jwk"
    admin_did = generate_keypair(key_path=key_path)

    asyncio.run(_seed_admin_and_events("export-test", admin_did))

    from folio_insights.cli import cli

    runner = CliRunner()
    out_path = tmp_path / "g.ttl"
    result = runner.invoke(
        cli,
        [
            "governance",
            "export",
            "export-test",
            "-o",
            str(out_path),
            "--key-path",
            str(key_path),
        ],
    )
    assert result.exit_code == 0, (
        f"governance export exited {result.exit_code}; stderr/output:\n"
        f"{result.output}"
    )
    assert out_path.exists(), (
        f"governance export did not write the output Turtle at {out_path}"
    )

    g = Graph()
    g.parse(str(out_path), format="turtle")

    activities = list(g.subjects(RDF.type, PROV.Activity))
    assert len(activities) >= 3, (
        f"expected ≥3 prov:Activity nodes in exported Turtle; got {len(activities)}"
    )

    attribution_count = sum(
        1 for _, p, _ in g.triples((None, PROV.wasAttributedTo, None))
    )
    assert attribution_count >= 3, (
        f"expected ≥3 prov:wasAttributedTo predicates; got {attribution_count}"
    )


# ── (b) Negative — unauthorized DID ────────────────────────────────────────


def test_export_unauthorized_did_exits_nonzero(tmp_path: pathlib.Path) -> None:
    """An export attempt by a DID with no active role exits non-zero.

    The corpus has a genesis admin (NOT the caller's DID); the caller's
    DID has no role, so ``authorize(caller_did, "export", ...)`` returns
    ``Deny(reason="no_active_role")`` and the CLI exits non-zero.
    """
    _reset_log()

    # Genesis admin (NOT the caller).
    admin_sk = Ed25519PrivateKey.generate()
    admin_did = _derive_did(admin_sk)
    asyncio.run(_seed_admin_and_events("unauthorized-test", admin_did))

    # Caller — a different DID with no active role.
    from folio_insights.identity.keys import generate_keypair

    caller_key_path = tmp_path / "caller.jwk"
    _ = generate_keypair(key_path=caller_key_path)

    from folio_insights.cli import cli

    runner = CliRunner()
    out_path = tmp_path / "g.ttl"
    result = runner.invoke(
        cli,
        [
            "governance",
            "export",
            "unauthorized-test",
            "-o",
            str(out_path),
            "--key-path",
            str(caller_key_path),
        ],
    )
    assert result.exit_code != 0, (
        "export with an unauthorized DID MUST exit non-zero. "
        f"Got exit_code={result.exit_code}; output:\n{result.output}"
    )
    # The error surface should mention 'denied' (matches the existing
    # promote/contest/supersede CLI Deny rendering — `unauthorized (denied: ...)`).
    assert "denied" in result.output.lower() or "unauthorized" in result.output.lower(), (
        f"unauthorized export message must mention 'denied' or 'unauthorized'; "
        f"got:\n{result.output}"
    )


# ── (c) AST-first-step — authorize() before iter_events() ─────────────────


def test_export_cli_authorize_precedes_iter_events() -> None:
    """Source-scan: cli/export.py MUST call authorize(...) BEFORE iter_events(...).

    D-19 applies uniformly across the CLI surface, even on read paths.
    """
    assert _EXPORT_CLI.exists(), (
        f"cli/export.py MUST ship in 07-05b Task 2 ({_EXPORT_CLI})"
    )
    source = _EXPORT_CLI.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(_EXPORT_CLI))

    authorize_line: int | None = None
    iter_events_line: int | None = None

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name: str | None = None
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        if name == "authorize" and authorize_line is None:
            authorize_line = node.lineno
        if name == "iter_events" and iter_events_line is None:
            iter_events_line = node.lineno

    assert authorize_line is not None, (
        "cli/export.py does NOT call authorize(). D-19 requires it as the "
        "first awaited step even on read paths."
    )
    if iter_events_line is not None:
        assert authorize_line < iter_events_line, (
            f"cli/export.py calls iter_events (line {iter_events_line}) "
            f"BEFORE authorize (line {authorize_line}). D-19 violation."
        )


def test_export_cli_does_not_import_rdflib() -> None:
    """D-04 boundary: cli/export.py MUST NOT import rdflib directly.

    The export pipeline routes through
    ``shape_validation.serialize_log_as_turtle`` — the lone exempt module.
    """
    source = _EXPORT_CLI.read_text(encoding="utf-8")
    forbidden_imports = [
        "import rdflib",
        "from rdflib",
        "import aiosqlite",
        "from aiosqlite",
        "import pyoxigraph",
        "from pyoxigraph",
    ]
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for forb in forbidden_imports:
            assert not stripped.startswith(forb), (
                f"cli/export.py contains forbidden D-04 import: {stripped!r}. "
                "rdflib is routed via shape_validation.serialize_log_as_turtle."
            )
