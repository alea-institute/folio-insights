"""CLI tests for folio-insights polysemy subgroup (Plan 01-05).

Pitfall 4 guard: every rich.prompt.Prompt.ask() call in the code path
under test gets ONE corresponding input line with a trailing newline
in the scripted stdin. Missing a line causes silent hangs or bogus
defaults.

Canonical schema guard: DispositionRecord.proposed_fork is REQUIRED
(not Optional). The CLI accept/reject paths commit the detector's
proposed fork (uses_analogousTo=False) unchanged; modify overrides it.

PRINCIPLE-06 guard (test_no_auto_apply_path): no flag named
{auto, yes, batch, accept_all, no_prompt, force} may exist anywhere
in the review subcommand parameter surface.

OQ-5 guard (test_single_llm_provider_flag): single `--llm-provider`
flag; NO `--llm-model`.
"""
from __future__ import annotations

import json
import pathlib
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from folio_insights.polysemy.cli import polysemy
from folio_insights.polysemy.detector import RuleVerdict

pytestmark = pytest.mark.polysemy_spike


@pytest.fixture
def tmp_dispositions(tmp_path: pathlib.Path) -> pathlib.Path:
    return tmp_path / "dispositions.jsonl"


@pytest.fixture
def canned_verdict() -> RuleVerdict:
    """CANONICAL RuleVerdict shape (01-03) — kind/decision/rule_confidence/matched_rules/evidence_score."""
    return RuleVerdict(
        kind="rule",
        decision="polysemy",
        rule_confidence=0.72,
        matched_rules=["R1-R2-R3-pass"],
        evidence_score=0.81,
    )


def _seed_minimal_fixtures(tmp_path: pathlib.Path) -> pathlib.Path:
    """Write enough fixtures for build_prototype_cluster to run.

    Mirrors shape produced by 01-02 fixture_loader but kept minimal here
    so the test doesn't depend on the full >=20-shard curation.
    """
    d = tmp_path / "fixtures"
    d.mkdir()
    frameworks = [
        "CommonLaw", "CommonLaw", "CommonLaw",
        "Restatement", "Restatement", "Restatement",
    ]
    for i, fw in enumerate(frameworks):
        (d / f"shard-{i:02d}.json").write_text(json.dumps({
            "iri": f"fi:Shard_{fw.lower()}{i}",
            "framework": fw,
            "source_doc": f"synthetic-{i}",
            "extracted_text": f"test shard {i}",
            "axiom_summary": f"consideration is X in framework {fw} ({i})",
            "prime_analogate_hint": None,
            "proportional_relation_hint": None,
            "term": "consideration",
        }))
    return d


def _invoke_review(
    runner: CliRunner,
    stdin: str,
    dispositions_path: pathlib.Path,
    fixtures: pathlib.Path,
    canned_verdict: RuleVerdict,
):
    with patch(
        "folio_insights.polysemy.cli.detect_polysemy",
        return_value=canned_verdict,
    ), patch(
        "folio_insights.polysemy.cli.ensure_reviewer_did",
        return_value="did:key:zFake123",
    ):
        return runner.invoke(
            polysemy,
            [
                "review",
                "--fixtures", str(fixtures),
                "--term", "consideration",
                "--dispositions-path", str(dispositions_path),
            ],
            input=stdin,
            catch_exceptions=False,
        )


# ---------------------- flag-surface guards ----------------------


def test_no_auto_apply_path():
    """PRINCIPLE-06: no flag may bypass the Prompt.ask() keystroke gate."""
    review_cmd = polysemy.commands["review"]
    forbidden = {"auto", "yes", "batch", "accept_all", "no_prompt", "force"}
    param_names = {p.name for p in review_cmd.params}
    assert not (forbidden & param_names), (
        f"PRINCIPLE-06 violation: review command exposes forbidden flag(s): "
        f"{forbidden & param_names}"
    )


def test_single_llm_provider_flag():
    """OQ-5 W1: single --llm-provider flag; NO --llm-model."""
    for cmd_name in ("review", "detect"):
        cmd = polysemy.commands[cmd_name]
        names = {p.name for p in cmd.params}
        assert "llm_provider" in names, f"{cmd_name}: missing --llm-provider"
        assert "llm_model" not in names, (
            f"{cmd_name}: --llm-model must not exist (OQ-5 single-flag)"
        )


def test_subgroup_registered_in_root_cli():
    from folio_insights.cli import cli

    assert "polysemy" in cli.commands, (
        "polysemy subgroup is not registered in src/folio_insights/cli.py "
        "(mirror the bench pattern at module bottom)"
    )


# ---------------------- review paths ----------------------


def test_review_accept_path(tmp_dispositions, tmp_path, canned_verdict):
    fixtures_dir = _seed_minimal_fixtures(tmp_path)
    runner = CliRunner()
    # 2 prompts: decision, rationale (blank)
    result = _invoke_review(
        runner, "accept\n\n", tmp_dispositions, fixtures_dir, canned_verdict,
    )
    assert result.exit_code == 0, result.output
    lines = tmp_dispositions.read_text().strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["decision"] == "accept"
    # proposed_fork is REQUIRED (canonical) — accept commits detector's proposal
    assert rec["proposed_fork"] is not None
    assert rec["proposed_fork"]["uses_analogousTo"] is False
    assert rec["proposed_fork"]["cluster_id"] == rec["cluster_id"]
    # detector_verdict is a dict, not a float (B6)
    assert isinstance(rec["detector_verdict"], dict)
    assert rec["detector_verdict"]["kind"] == "rule"


def test_review_reject_path(tmp_dispositions, tmp_path, canned_verdict):
    fixtures_dir = _seed_minimal_fixtures(tmp_path)
    runner = CliRunner()
    result = _invoke_review(
        runner,
        "reject\nfixtures disagree on axiom\n",
        tmp_dispositions, fixtures_dir, canned_verdict,
    )
    assert result.exit_code == 0, result.output
    rec = json.loads(tmp_dispositions.read_text().strip().splitlines()[0])
    assert rec["decision"] == "reject"
    assert rec["rationale"] == "fixtures disagree on axiom"
    # still the detector's proposal, uses_analogousTo=False
    assert rec["proposed_fork"] is not None
    assert rec["proposed_fork"]["uses_analogousTo"] is False


def test_review_modify_path(tmp_dispositions, tmp_path, canned_verdict):
    fixtures_dir = _seed_minimal_fixtures(tmp_path)
    runner = CliRunner()
    # Prompts in order: decision, prime, proportional, distinction_kind,
    # confirm, rationale
    stdin = (
        "modify\n"
        "urn:folio:term/consideration#restatement\n"
        "bargained-for exchange <-> mutual inducement\n"
        "analogica\n"
        "yes\n"
        "context-specific divergence is genuine\n"
    )
    result = _invoke_review(
        runner, stdin, tmp_dispositions, fixtures_dir, canned_verdict,
    )
    assert result.exit_code == 0, result.output
    assert "fi:analogousTo" in result.output, "Proposed TTL was not rendered"
    rec = json.loads(tmp_dispositions.read_text().strip().splitlines()[0])
    assert rec["decision"] == "modify"
    fork = rec["proposed_fork"]
    assert fork is not None
    assert fork["distinction_kind"] == "analogica"
    assert fork["uses_analogousTo"] is True
    assert fork["prime_analogate"] == "urn:folio:term/consideration#restatement"


def test_review_modify_aborts_on_no_confirm(tmp_dispositions, tmp_path, canned_verdict):
    fixtures_dir = _seed_minimal_fixtures(tmp_path)
    runner = CliRunner()
    stdin = (
        "modify\n"
        "urn:folio:term/consideration#restatement\n"
        "bargained-for exchange <-> mutual inducement\n"
        "analogica\n"
        "no\n"  # abort
    )
    result = _invoke_review(
        runner, stdin, tmp_dispositions, fixtures_dir, canned_verdict,
    )
    assert result.exit_code == 0, result.output
    assert "aborted" in result.output.lower()
    assert not tmp_dispositions.exists() or tmp_dispositions.read_text() == ""


def test_review_invalid_choice_reprompts(tmp_dispositions, tmp_path, canned_verdict):
    fixtures_dir = _seed_minimal_fixtures(tmp_path)
    runner = CliRunner()
    # rich.prompt.Prompt.ask(choices=[...]) re-asks on invalid input.
    # "foo" rejected, "accept" accepted, blank rationale.
    result = _invoke_review(
        runner, "foo\naccept\n\n", tmp_dispositions, fixtures_dir, canned_verdict,
    )
    assert result.exit_code == 0, result.output
    rec = json.loads(tmp_dispositions.read_text().strip().splitlines()[0])
    assert rec["decision"] == "accept"


# ---------------------- detect + audit ----------------------


def test_detect_command_writes_no_dispositions(tmp_path, canned_verdict):
    fixtures_dir = _seed_minimal_fixtures(tmp_path)
    dispositions = tmp_path / "dispositions.jsonl"
    runner = CliRunner()
    with patch(
        "folio_insights.polysemy.cli.detect_polysemy",
        return_value=canned_verdict,
    ):
        result = runner.invoke(
            polysemy,
            ["detect", "--fixtures", str(fixtures_dir), "--term", "consideration"],
            catch_exceptions=False,
        )
    assert result.exit_code == 0, result.output
    assert not dispositions.exists()


def test_audit_command_counts_dispositions(tmp_path):
    dispositions = tmp_path / "dispositions.jsonl"

    def _make_record(
        decision: str,
        cluster_id: str,
        uses_analogous: bool = False,
        dkind: str | None = None,
        rationale: str = "",
    ) -> str:
        # CANONICAL DispositionRecord JSON shape — proposed_fork is REQUIRED
        return json.dumps({
            "schema_version": "1",
            "cluster_id": cluster_id,
            "term": "consideration",
            "proposed_fork": {
                "cluster_id": cluster_id,
                "term": "consideration",
                "frameworks": ["CommonLaw", "Restatement"],
                "uses_analogousTo": uses_analogous,
                "prime_analogate": (
                    "urn:folio:term/consideration#restatement"
                    if uses_analogous else None
                ),
                "proportional_relation": "example" if uses_analogous else None,
                "distinction_kind": dkind,
                "suggested_child_iris": [],
            },
            "decision": decision,
            "rationale": rationale,
            "reviewer_did": "did:key:z1",
            "reviewed_at_iso": f"2026-04-23T00:00:0{cluster_id[-1]}Z",
            "detector_verdict": {
                "kind": "rule",
                "decision": "polysemy",
                "rule_confidence": 0.7,
                "matched_rules": ["R1"],
                "evidence_score": 0.8,
            },
            "signature": None,
            "audit_label": None,
            "audit_agreement": None,
        })

    dispositions.write_text(
        "\n".join([
            _make_record("accept", "a"),
            _make_record("accept", "b"),
            _make_record("reject", "c", rationale="fixture disagree"),
            _make_record("modify", "d", uses_analogous=True, dkind="analogica"),
        ]) + "\n"
    )
    runner = CliRunner()
    result = runner.invoke(
        polysemy,
        ["audit", "--dispositions-path", str(dispositions)],
    )
    assert result.exit_code == 0, result.output
    assert "accept" in result.output
    assert "2" in result.output
