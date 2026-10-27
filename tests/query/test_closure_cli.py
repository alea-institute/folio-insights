"""The closure CLI accepts only an explicit public signed artifact."""
from __future__ import annotations

import asyncio
import json

import pytest
from click.testing import CliRunner

from folio_insights.closure.declarations import load_declarations
from folio_insights.query.cli import query_group
from folio_insights.storage import CorpusStorageContext
from tests.query.test_closure_declarations import declaration, seeded
from tests.storage.conftest import fresh_signing_clock  # noqa: F401


def prepare(tmp_path):
    root = tmp_path / "storage"

    async def seed():
        ctx, admin = await seeded(root)
        try:
            return await declaration(ctx, admin)
        finally:
            await ctx.close()

    signed = asyncio.run(seed())
    artifact = tmp_path / "declaration.json"
    artifact.write_text(signed.model_dump_json())
    return root, artifact, signed


def invoke(root, artifact, *extra):
    return CliRunner().invoke(query_group, [
        "declare", "--corpus", "corpus-a", "--corpus-root", str(root),
        "--declaration", str(artifact), *extra,
    ])


def test_cli_persists_and_retries_signed_artifact(tmp_path):
    root, artifact, signed = prepare(tmp_path)
    first = invoke(root, artifact)
    assert first.exit_code == 0, first.output
    assert json.loads(first.output) == {
        "status": "committed", "op_id": signed.op_id, "ledger_position": 0,
    }
    assert invoke(root, artifact, "--op-id", signed.op_id).output == first.output

    async def verify():
        async with await CorpusStorageContext.open(root, "corpus-a") as ctx:
            assert (await load_declarations(ctx)).active == (signed,)
            assert await ctx.proposals.head() == 0

    asyncio.run(verify())


@pytest.mark.parametrize("problem", ["operation", "corpus", "signature", "malformed"])
def test_cli_refuses_without_appending(tmp_path, problem):
    root, artifact, signed = prepare(tmp_path)
    args = []
    if problem == "operation":
        args = ["--op-id", "another-operation"]
    elif problem == "corpus":
        artifact.write_text(signed.model_copy(update={"corpus": "another-corpus"}).model_dump_json())
    elif problem == "signature":
        artifact.write_text(signed.model_copy(update={"signature": "invalid"}).model_dump_json())
    else:
        artifact.write_text('{"private": "must never be shown"}')
    result = invoke(root, artifact, *args)
    assert result.exit_code == 1
    assert "must never be shown" not in result.output

    async def verify():
        async with await CorpusStorageContext.open(root, "corpus-a") as ctx:
            assert await ctx.proposals.head() == -1

    asyncio.run(verify())


def test_cli_never_creates_an_unknown_corpus_or_accepts_key_flags(tmp_path):
    root, artifact, _signed = prepare(tmp_path)
    unknown_root = tmp_path / "absent"
    result = invoke(unknown_root, artifact)
    assert result.exit_code == 1 and "does not exist" in result.output
    assert not unknown_root.exists()
    help_result = CliRunner().invoke(query_group, ["declare", "--help"])
    assert help_result.exit_code == 0
    assert "--key" not in help_result.output and "--private" not in help_result.output
