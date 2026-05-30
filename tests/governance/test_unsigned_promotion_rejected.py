"""Unsigned promotion rejected end-to-end via CLI (orig EC3 amended bar; D-03).

``governance promote <shard_iri> --status=demonstrable --cite <iri>`` invoked
WITHOUT a valid --key-path that produces a signing key MUST exit non-zero
with a diagnostic about missing/invalid signing key (or unauthorized). Closes
the original EC3 bar at the CLI surface (D-03 — Phase 7 ships CLI + library,
no web UI).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from folio_insights.cli import cli

pytestmark = pytest.mark.governance


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


def test_unsigned_promotion_rejected_end_to_end(
    tmp_home: Path, tmp_path: Path
) -> None:
    """A `governance promote` call WITHOUT a loadable signing key path exits
    non-zero. Either:
      * --key-path points at a nonexistent file → FileNotFoundError-derived
        click error;
      * the loaded key derives a DID that has no active role in the corpus →
        authorize() returns Deny(reason="no_active_role").

    Either path satisfies the orig EC3 bar: an unsigned promotion CANNOT
    succeed via the CLI.
    """
    runner = CliRunner()
    bogus_key = tmp_path / "nonexistent.jwk"
    assert not bogus_key.exists()

    result = runner.invoke(
        cli,
        [
            "governance",
            "promote",
            "fi:shard:abc",
            "--status",
            "demonstrable",
            "--cite",
            "fi:shard:cited",
            "--corpus",
            "test-corpus",
            "--key-path",
            str(bogus_key),
        ],
    )
    assert result.exit_code != 0
    combined = (result.output or "") + (
        result.stderr if hasattr(result, "stderr") else ""
    )
    lower = combined.lower()
    # Any of: missing key, unauthorized, no active role, invalid signature,
    # FileNotFoundError, "not found".
    assert any(
        m in lower
        for m in (
            "no signing key",
            "unauthorized",
            "no_active_role",
            "invalidsignature",
            "no active role",
            "not found",
            "filenotfounderror",
            "signing key",
            "denied",
        )
    ), f"expected unsigned/unauthorized diagnostic; got: {combined!r}"
