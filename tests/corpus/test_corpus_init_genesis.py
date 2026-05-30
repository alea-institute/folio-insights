"""``corpus init`` genesis bootstrap CLI tests (CORPUS-05 + D-10 + D-19).

Verifies the four core invariants:
  1. ``corpus init <name> --admin-did <did> --key-path <key>`` (where the key
     derives ``<did>``) writes a genesis row 0 RoleAssertionEvent with
     ``role=corpus_admin`` and ``subject_did=admin_did`` (self-signed). The
     authorize() call's action="corpus_init" (D-19 — no CLI exemption).
  2. A second invocation against the same corpus log Denies with
     ``corpus_already_initialized``.
  3. A mismatched --admin-did + --key-path pair (signer DID != admin_did) is
     refused at the CLI layer (defense in depth before authorize()).
  4. A missing --admin-did flag is refused by Click (required option).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from folio_insights.cli import cli

pytestmark = pytest.mark.governance


# ── HOME isolation fixture (mirrors tests/identity/test_did_cli.py) ──


@pytest.fixture(autouse=True)
def reset_governance_log():
    """Reset the process-local GOVERNANCE_LOG singleton between tests.

    The corpus CLI shares an InMemoryGovernanceLog singleton across CliRunner
    invocations in the same Python process; without per-test reset, a prior
    test's genesis row leaks into this test's first invocation.
    """
    from folio_insights.governance.cli import _state
    from folio_insights.governance.log import InMemoryGovernanceLog

    _state.GOVERNANCE_LOG = InMemoryGovernanceLog()
    yield
    _state.GOVERNANCE_LOG = InMemoryGovernanceLog()


@pytest.fixture
def tmp_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ``Path.home`` + ``identity.keys.KEY_PATH`` to a tmp dir per test."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    from folio_insights.identity import keys as _keys

    new_key_dir = tmp_path / ".folio-insights"
    new_key_path = new_key_dir / "signer.jwk"
    monkeypatch.setattr(_keys, "KEY_DIR", new_key_dir)
    monkeypatch.setattr(_keys, "KEY_PATH", new_key_path)
    from folio_insights.identity import cli as _idcli

    monkeypatch.setattr(_idcli, "KEY_PATH", new_key_path)
    return tmp_path


def _make_test_key(tmp_path: Path, name: str) -> tuple[Path, str]:
    """Generate a test ed25519 key + return (key_path, did:key)."""
    from folio_insights.identity.keys import generate_keypair

    key_path = tmp_path / f"{name}.jwk"
    did = generate_keypair(key_path)
    return key_path, did


# ── Test 1: positive genesis row 0 ──


def test_corpus_init_writes_genesis_row(tmp_home: Path, tmp_path: Path) -> None:
    """corpus init <name> --admin-did <did> --key-path <matching key>
    succeeds and emits JSON with position=0 + role=corpus_admin + subject=admin_did."""
    key_path, alice_did = _make_test_key(tmp_path, "alice")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "corpus",
            "init",
            "test-corpus",
            "--admin-did",
            alice_did,
            "--key-path",
            str(key_path),
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, f"stdout={result.output}\nstderr={result.stderr_bytes}"
    payload = json.loads(result.output)
    assert payload["position"] == 0
    assert payload["role"] == "corpus_admin"
    assert payload["subject_did"] == alice_did
    # Self-signed: signature.did == subject_did at genesis.
    assert payload["signature"]["did"] == alice_did


# ── Test 2: second invocation Denies ──


def test_corpus_init_second_invocation_denied(tmp_home: Path, tmp_path: Path) -> None:
    """Second corpus init against a non-empty log MUST exit non-zero with
    ``corpus_already_initialized`` from authorize()."""
    key_path, alice_did = _make_test_key(tmp_path, "alice")
    runner = CliRunner()

    # The CLI uses a process-local InMemoryGovernanceLog instance; the SECOND
    # invocation MUST run against the SAME log instance for the carve-out to
    # see the row. The CLI module pins the log at import time — so two CLI
    # invocations in the same Python process share the log singleton.
    first = runner.invoke(
        cli,
        [
            "corpus",
            "init",
            "test-corpus",
            "--admin-did",
            alice_did,
            "--key-path",
            str(key_path),
        ],
    )
    assert first.exit_code == 0, first.output

    second = runner.invoke(
        cli,
        [
            "corpus",
            "init",
            "test-corpus",
            "--admin-did",
            alice_did,
            "--key-path",
            str(key_path),
        ],
    )
    assert second.exit_code != 0
    combined = (second.output or "") + (second.stderr if hasattr(second, "stderr") else "")
    assert "corpus_already_initialized" in combined, (
        f"expected corpus_already_initialized in CLI output; got: {combined!r}"
    )


# ── Test 3: mismatched --admin-did + --key-path ──


def test_corpus_init_mismatched_admin_did_refused(
    tmp_home: Path, tmp_path: Path
) -> None:
    """If --admin-did differs from the DID derived from --key-path, the CLI
    refuses (defense in depth) OR authorize() returns ``genesis_mismatch``."""
    key_path, bob_did = _make_test_key(tmp_path, "bob")
    fake_alice = "did:key:zAliceNotMatchingBobsKey"
    assert fake_alice != bob_did

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "corpus",
            "init",
            "test-corpus-mismatch",
            "--admin-did",
            fake_alice,
            "--key-path",
            str(key_path),
        ],
    )
    assert result.exit_code != 0
    combined = (result.output or "") + (
        result.stderr if hasattr(result, "stderr") else ""
    )
    # Either the CLI bind check fires ("does not match") OR authorize()
    # returns genesis_mismatch.
    assert ("does not match" in combined) or ("genesis_mismatch" in combined), (
        f"expected mismatch diagnostic; got: {combined!r}"
    )


# ── Test 4: missing --admin-did refused by Click ──


def test_corpus_init_requires_admin_did_flag(tmp_home: Path, tmp_path: Path) -> None:
    """Per RESEARCH Open Question 1, --admin-did is REQUIRED (no default)."""
    key_path, _ = _make_test_key(tmp_path, "alice")
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["corpus", "init", "test-corpus", "--key-path", str(key_path)],
    )
    # Click returns exit code 2 for missing-required-option.
    assert result.exit_code != 0
