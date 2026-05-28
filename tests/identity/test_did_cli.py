"""``folio-insights did`` CLI tests (Plan 06-03 Task 3 + Task 4).

Click ``CliRunner`` against a tmp ``HOME`` (monkeypatch ``Path.home``) so the
local keystore lands in an isolated dir, not the real ``~/.folio-insights/``.

Coverage:

* ``did --help`` lists all five subcommands; the group is reachable from the
  root ``folio-insights --help``.
* ``did generate`` against a tmp keystore prints a ``did:key:z…`` string
  and is idempotent (second invocation prints the SAME did:key).
* ``did preview`` against a synthesized shard JSON prints a hash + diff.
* ``did sign`` then ``did verify`` round-trip succeeds.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from folio_insights.cli import cli
from folio_insights.identity.cli import did_group
from folio_insights.shards import SimpleAssertionShard
from tests.shards.conftest import _sample_shard

pytestmark = pytest.mark.identity


# ── HOME isolation fixture ───────────────────────────────────────────────────


@pytest.fixture
def tmp_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ``Path.home`` + ``identity.keys.KEY_PATH`` to a tmp dir per test.

    The keystore module captures ``Path.home()`` at import time into
    ``KEY_DIR``/``KEY_PATH`` module-level constants — so monkey-patching
    ``Path.home`` alone is not enough for the default-path branch. We patch
    BOTH ``KEY_DIR``/``KEY_PATH`` directly so every CLI command's
    default-path branch lands under ``tmp_path``.
    """
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    # The keys module bound KEY_DIR/KEY_PATH at import-time; override them.
    from folio_insights.identity import keys as _keys

    new_key_dir = tmp_path / ".folio-insights"
    new_key_path = new_key_dir / "signer.jwk"
    monkeypatch.setattr(_keys, "KEY_DIR", new_key_dir)
    monkeypatch.setattr(_keys, "KEY_PATH", new_key_path)
    # The CLI module imported KEY_PATH at module-load; patch its binding too.
    from folio_insights.identity import cli as _cli

    monkeypatch.setattr(_cli, "KEY_PATH", new_key_path)
    return tmp_path


# ── helpers ─────────────────────────────────────────────────────────────────


def _write_shard_json(tmp_path: Path) -> Path:
    """Build a SimpleAssertionShard and dump it to JSON; return the path."""
    shard = _sample_shard(SimpleAssertionShard)
    shard_path = tmp_path / "shard.json"
    shard_path.write_text(shard.model_dump_json(), encoding="utf-8")
    return shard_path


# ── --help — group + root reachability ──────────────────────────────────────


def test_did_help_lists_all_five_subcommands() -> None:
    """``did --help`` exits 0 and mentions all five subcommands."""
    runner = CliRunner()
    result = runner.invoke(did_group, ["--help"])
    assert result.exit_code == 0, result.output
    for cmd in ("generate", "bind", "sign", "verify", "preview"):
        assert cmd in result.output, f"`did --help` missing subcommand {cmd!r}"


def test_root_cli_help_includes_did_group() -> None:
    """``folio-insights --help`` lists the ``did`` group (reachable from root)."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0, result.output
    assert "did" in result.output


def test_root_cli_did_help_works() -> None:
    """``folio-insights did --help`` exits 0 with all five subcommands."""
    runner = CliRunner()
    result = runner.invoke(cli, ["did", "--help"])
    assert result.exit_code == 0, result.output
    for cmd in ("generate", "bind", "sign", "verify", "preview"):
        assert cmd in result.output


# ── did generate — produces a did:key, idempotent ───────────────────────────


def test_did_generate_prints_didkey(tmp_home: Path) -> None:
    """``did generate`` against an empty tmp keystore prints a did:key:z…"""
    runner = CliRunner()
    result = runner.invoke(did_group, ["generate"])
    assert result.exit_code == 0, result.output
    output = result.output.strip()
    assert output.startswith("did:key:z"), f"Unexpected output: {output!r}"


def test_did_generate_is_idempotent(tmp_home: Path) -> None:
    """A second ``did generate`` against the same keystore prints the SAME did:key."""
    runner = CliRunner()
    first = runner.invoke(did_group, ["generate"])
    second = runner.invoke(did_group, ["generate"])
    assert first.exit_code == 0
    assert second.exit_code == 0
    assert first.output.strip() == second.output.strip()


def test_did_generate_rejects_non_key_method(tmp_home: Path) -> None:
    """Click rejects an unsupported --method up-front (Choice gate)."""
    runner = CliRunner()
    result = runner.invoke(did_group, ["generate", "--method", "web"])
    assert result.exit_code != 0
    # Click's Choice rejects invalid values BEFORE the command body runs.
    assert "Invalid value" in result.output or "invalid choice" in result.output.lower()


# ── did preview — prints content hash + human-readable line ─────────────────


def test_did_preview_renders_hash_and_diff(tmp_home: Path, tmp_path: Path) -> None:
    """``did preview --action extract --shard-json …`` prints hash + diff."""
    shard_path = _write_shard_json(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        did_group,
        ["preview", "--action", "extract", "--shard-json", str(shard_path)],
    )
    assert result.exit_code == 0, result.output
    assert "content_hash:" in result.output
    assert "action:" in result.output
    assert "extract" in result.output
    assert "what:" in result.output


# ── did sign / verify — round-trip ──────────────────────────────────────────


def test_did_sign_then_verify_round_trip(tmp_home: Path, tmp_path: Path) -> None:
    """``did sign --yes`` produces a signature; ``did verify`` confirms it."""
    runner = CliRunner()
    # Step 1: generate a keypair so `sign` has a key to load.
    gen = runner.invoke(did_group, ["generate"])
    assert gen.exit_code == 0, gen.output

    # Step 2: write a shard JSON to disk.
    shard_path = _write_shard_json(tmp_path)

    # Step 3: sign it (--yes skips the confirm).
    sign = runner.invoke(
        did_group,
        ["sign",
         "--action", "extract",
         "--shard-json", str(shard_path),
         "--yes"],
    )
    assert sign.exit_code == 0, sign.output
    # Extract the JSON signature from stdout (everything after the preview
    # block — `--yes` still prints the preview, then the JSON).
    # The preview ends at "what:" line; the JSON starts at the first `{`.
    json_start = sign.output.find("{")
    assert json_start >= 0, f"No JSON found in sign output: {sign.output!r}"
    sig_json = sign.output[json_start:]
    sig_path = tmp_path / "sig.json"
    sig_path.write_text(sig_json, encoding="utf-8")
    # Sanity: the JSON parses and carries the expected shape.
    sig_dict = json.loads(sig_json)
    assert sig_dict["action"] == "extract"
    assert sig_dict["signature"]  # non-empty

    # Step 4: verify the signature against the same shard.
    verify = runner.invoke(
        did_group,
        ["verify",
         "--shard-json", str(shard_path),
         "--signature-json", str(sig_path)],
    )
    assert verify.exit_code == 0, verify.output
    assert "PASS" in verify.output


def test_did_sign_aborts_when_operator_declines(
    tmp_home: Path, tmp_path: Path
) -> None:
    """Without --yes, declining the confirm exits 2 and prints no signature."""
    runner = CliRunner()
    runner.invoke(did_group, ["generate"])  # ensure keystore exists
    shard_path = _write_shard_json(tmp_path)
    result = runner.invoke(
        did_group,
        ["sign", "--action", "extract", "--shard-json", str(shard_path)],
        input="n\n",
    )
    assert result.exit_code == 2, result.output
    # No JSON body printed — only the preview + abort message.
    assert "{" not in result.output.split("Aborted")[-1]
