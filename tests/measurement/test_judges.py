"""Subscription judge boundary, exercised only through offline CLI executables."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from folio_insights.measurement.annotations import (
    Annotation,
    AnchorVerification,
)
from folio_insights.measurement.judges import (
    ClaudeJudge,
    CodexJudge,
    ConceptCandidate,
    JudgeItem,
    JudgePacket,
    VerdictBatch,
    adjudication_items,
    anchor_accuracy,
    claude_sample,
)
from folio_insights.measurement.schema import SourceSnapshot

FIXTURES = Path(__file__).parent / "fixtures" / "fake_judges"


def packet(count=10, *, kind="prediction", source_id="source-1", genre="opinions"):
    text = "A party must give notice."
    source = SourceSnapshot(
        source_id=source_id,
        group_id=source_id,
        title="Synthetic rule",
        genre=genre,
        subgenre="test",
        jurisdiction="federal",
        synthetic=True,
        partition="tuning",
        text=text,
        sha256=hashlib.sha256(text.encode()).hexdigest(),
    )
    items = tuple(
        JudgeItem(
            item_id=f"{source_id}-{kind}-{i}",
            source_id=source_id,
            kind=kind,
            proposition_id=f"p{i}",
            text="The party owes notice.",
            span={"start": 0, "end": len(text)},
            concept_ids=("c1",),
        )
        for i in range(count)
    )
    return JudgePacket(
        sources=(source,),
        items=items,
        predictions=items if kind == "prediction" else (),
        catalog=(
            ConceptCandidate(
                concept_id="c1", label="Obligation", branch="Deontic Specification"
            ),
        ),
    )


def verdict(item, **changes):
    return dict(
        item_id=item.item_id,
        verdict="correct",
        reason="Supported by the source.",
        omission=None,
        concept_ids=["c1"],
        **changes,
    )


def response(data, changes=None):
    return {
        "judgments": [
            verdict(i) | (changes or {}).get(i.item_id, {}) for i in data.items
        ]
    }


@pytest.fixture
def fake_cli(tmp_path, monkeypatch):
    root = tmp_path / "bin"
    root.mkdir()
    for name in ("codex", "claude"):
        shutil.copyfile(FIXTURES / "cli.py", root / name)
        (root / name).chmod(0o755)
    monkeypatch.setenv("PATH", str(root) + ":/usr/bin:/bin")
    home = tmp_path / "home"
    home.mkdir()
    for name in ("HOME", "CODEX_HOME", "CLAUDE_CONFIG_DIR", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(name, str(home))

    def configure(data, **changes):
        values = {name: {"response": response(data)} for name in ("codex", "claude")}
        for name, settings in changes.items():
            values[name].update(settings)
        (root / "control.json").write_text(json.dumps(values))
        return root

    return configure


def calls(root):
    return [
        json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines()
    ]


@pytest.mark.parametrize(
    "adapter,provider,auth_status,auth_exit,allowed",
    [
        (CodexJudge, "codex", "Logged in using API key", 0, False),
        (CodexJudge, "codex", "Logged in using ChatGPT", 0, True),
        (CodexJudge, "codex", "Unknown login method", 0, False),
        (CodexJudge, "codex", "Logged in using ChatGPT", 1, False),
        (
            ClaudeJudge,
            "claude",
            json.dumps(
                {
                    "loggedIn": True,
                    "authMethod": "api_key",
                    "apiKeySource": "/login managed key",
                }
            ),
            0,
            False,
        ),
        (
            ClaudeJudge,
            "claude",
            json.dumps(
                {
                    "loggedIn": True,
                    "authMethod": "claude.ai",
                    "apiProvider": "firstParty",
                    "subscriptionType": "max",
                }
            ),
            0,
            True,
        ),
        (ClaudeJudge, "claude", "unknown status", 0, False),
        (
            ClaudeJudge,
            "claude",
            json.dumps(
                {
                    "loggedIn": True,
                    "authMethod": "claude.ai",
                    "apiProvider": "firstParty",
                    "subscriptionType": "max",
                }
            ),
            1,
            False,
        ),
        (
            ClaudeJudge,
            "claude",
            json.dumps(
                {
                    "loggedIn": True,
                    "authMethod": "api_key_helper",
                    "apiKeySource": "apiKeyHelper",
                }
            ),
            0,
            False,
        ),
        (
            ClaudeJudge,
            "claude",
            json.dumps(
                {
                    "loggedIn": True,
                    "authMethod": "claude.ai",
                    "apiProvider": "firstParty",
                    "subscriptionType": "max",
                    "apiKeySource": "apiKeyHelper",
                }
            ),
            0,
            False,
        ),
        (
            ClaudeJudge,
            "claude",
            json.dumps(
                {
                    "loggedIn": True,
                    "authMethod": "api_key",
                    "apiKeySource": "ANTHROPIC_API_KEY",
                }
            ),
            0,
            False,
        ),
        (
            ClaudeJudge,
            "claude",
            json.dumps(
                {
                    "loggedIn": True,
                    "authMethod": "third_party",
                    "apiProvider": "bedrock",
                }
            ),
            0,
            False,
        ),
        (
            ClaudeJudge,
            "claude",
            json.dumps(
                {
                    "loggedIn": False,
                    "authMethod": "claude.ai",
                    "subscriptionType": "max",
                }
            ),
            0,
            False,
        ),
        (
            ClaudeJudge,
            "claude",
            json.dumps(
                {
                    "loggedIn": True,
                    "authMethod": "claude.ai",
                    "apiProvider": "firstParty",
                    "subscriptionType": None,
                }
            ),
            0,
            False,
        ),
    ],
)
def test_saved_auth_must_explicitly_identify_subscription(
    fake_cli, adapter, provider, auth_status, auth_exit, allowed
):
    data = packet(1)
    root = fake_cli(
        data, **{provider: {"auth_status": auth_status, "auth_exit": auth_exit}}
    )
    result = adapter(model="recorded-model").judge(data)
    assert result.status == ("complete" if allowed else "incomplete")
    if allowed:
        assert len(calls(root)) == 1
    else:
        assert result.error == "subscription-auth-required"
        assert result.missing_item_ids == (data.items[0].item_id,)
        assert not (root / "calls.jsonl").exists()
    probes = [
        json.loads(line) for line in (root / "probes.jsonl").read_text().splitlines()
    ]
    assert {
        "provider": provider,
        "args": ["login", "status"]
        if provider == "codex"
        else ["auth", "status", "--json"],
    } in probes


@pytest.mark.parametrize("capability", ["auth_help", "status_help"])
def test_claude_without_offline_auth_introspection_is_refused(fake_cli, capability):
    data = packet(1)
    root = fake_cli(data, claude={capability: "unsupported"})
    result = ClaudeJudge(model="recorded-model").judge(data)
    assert result.status == "incomplete"
    assert result.error == "subscription-auth-unverifiable"
    assert not (root / "calls.jsonl").exists()


@pytest.mark.parametrize(
    "adapter,provider", [(CodexJudge, "codex"), (ClaudeJudge, "claude")]
)
def test_cli_modes_stdin_isolation_and_subscription_only_environment(
    fake_cli, monkeypatch, adapter, provider
):
    data = packet(1)
    root = fake_cli(data)
    forbidden = [
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "AZURE_OPENAI_API_KEY",
        "AWS_PROFILE",
        "AWS_ACCESS_KEY_ID",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_CODE_USE_FOUNDRY",
        "OPENROUTER_API_KEY",
        "CODEX_CONFIG",
        "HTTP_PROXY",
        "ANTHROPIC_AUTH_TOKEN",
    ]
    # Simulate a contaminated parent mapping without setting provider credentials.
    monkeypatch.setattr(
        "folio_insights.measurement.judges.os.environ",
        dict(os.environ) | {name: "forbidden-fixture-override" for name in forbidden},
    )
    result = adapter(model="recorded-model").judge(data)
    assert result.status == "complete"
    assert result.missing_item_ids == ()
    assert result.identity.cli_version == provider + " fixture-1"
    assert result.identity.model == "recorded-model"
    assert len(result.prompt_sha256) == len(result.input_sha256) == 64
    (call,) = calls(root)
    assert not set(forbidden) & call["env"].keys()
    assert Path(call["cwd"]) != Path.cwd()
    assert not Path(call["cwd"]).exists()
    prompt = json.loads(call["stdin"])
    assert prompt["packet"]["sources"][0]["text"] == data.sources[0].text
    assert prompt["packet"]["items"][0]["span"] == {"start": 0, "end": 25}
    assert "No model may write an IRI" in prompt["instructions"]
    args = call["args"]
    assert args[args.index("--model") + 1] == "recorded-model"
    if provider == "codex":
        assert args[0] == "exec" and args[-1] == "-"
        assert args[args.index("--sandbox") + 1] == "read-only"
        assert {
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--output-schema",
            "--skip-git-repo-check",
        } <= set(args)
        assert (
            "shell_tool" in args
            and "exec_tool" in args
            and "apply_patch_freeform" in args
        )
    else:
        assert "-p" in args
        assert args[args.index("--tools") + 1] == ""
        assert args[args.index("--setting-sources") + 1] == ""
        assert {
            "--safe-mode",
            "--no-session-persistence",
            "--strict-mcp-config",
        } <= set(args)
        assert args[args.index("--output-format") + 1] == "json"
        assert json.loads(args[args.index("--mcp-config") + 1]) == {"mcpServers": {}}
        assert json.loads(args[args.index("--settings") + 1])["disableAllHooks"] is True


def test_two_of_ten_plus_uncertain_are_independent_and_deduplicated(fake_cli):
    data = packet()
    original = claude_sample(data, (), seed=7)
    assert len(original.item_ids) == 2
    outside = next(i.item_id for i in data.items if i.item_id not in original.item_ids)
    changes = {
        i: {"verdict": "uncertain", "reason": "Private Codex rationale."}
        for i in (original.item_ids[0], outside)
    }
    root = fake_cli(data, codex={"response": response(data, changes)})
    codex = CodexJudge(model="recorded-model").judge(data)
    sample = claude_sample(data, codex.judgments, seed=7)
    assert set(sample.item_ids) == {*original.item_ids, outside}
    assert sample.denominator == 10 and sample.realized_count == 3
    assert sample.coverage == 0.3 and sample.strata[0].sampled == 3
    assert claude_sample(data, tuple(reversed(codex.judgments)), seed=7) == sample
    subset = data.select(sample.item_ids)
    fake_cli(subset)
    claude = ClaudeJudge(model="recorded-model").judge(subset)
    assert claude.status == "complete"
    claude_call = calls(root)[-1]
    assert "Private Codex rationale" not in claude_call["stdin"]
    assert json.loads(claude_call["stdin"])["packet"] == subset.model_dump(mode="json")
    assert len(json.loads(claude_call["stdin"])["packet"]["items"]) == 3
    queue = adjudication_items(data, codex, claude, sample)
    assert {i.item_id for i in queue} == set(changes)
    assert all(i.codex.reason == "Private Codex rationale." for i in queue)


def test_every_nonempty_genre_source_kind_stratum_is_sampled():
    packets = [
        packet(n, source_id=s, genre=g, kind=k)
        for n, s, g, k in [
            (10, "a", "opinions", "prediction"),
            (1, "b", "briefs", "gold"),
            (1, "b", "briefs", "omission"),
            (1, "b", "briefs", "tag"),
        ]
    ]
    sources = {s.source_id: s for p in packets for s in p.sources}
    data = JudgePacket(
        sources=tuple(sources.values()),
        items=tuple(i for p in packets for i in p.items),
        predictions=tuple(i for p in packets for i in p.predictions),
        catalog=packets[0].catalog,
    )
    sample = claude_sample(data, (), seed=0)
    assert sample.denominator == 13 and sample.realized_count == 5
    assert sorted(s.sampled for s in sample.strata) == [1, 1, 1, 2]
    reversed_data = data.model_copy(update={"items": tuple(reversed(data.items))})
    assert claude_sample(reversed_data, (), seed=0) == sample


@pytest.mark.parametrize(
    "adapter,provider", [(CodexJudge, "codex"), (ClaudeJudge, "claude")]
)
@pytest.mark.parametrize(
    "fault",
    [
        "iri",
        "iri-field",
        "malformed",
        "missing",
        "duplicate",
        "unexpected",
        "timeout",
        "nonzero",
        "bad-span",
        "wrong-source",
        "blank-reason",
        "unknown-field",
        "wrong-type",
    ],
)
def test_invalid_or_unavailable_judgments_remain_incomplete(
    fake_cli, adapter, provider, fault
):
    data = packet(2)
    payload = response(data)
    settings = {}
    first = payload["judgments"][0]
    if fault == "iri":
        first["concept_ids"] = ["https://folio.openlegalstandard.org/fake"]
    elif fault == "iri-field":
        first["iri"] = "anything"
    elif fault == "malformed":
        settings = {"raw": "{invalid", "raw_envelope": "{invalid"}
    elif fault == "missing":
        payload["judgments"].pop()
    elif fault == "duplicate":
        payload["judgments"].append(first.copy())
    elif fault == "unexpected":
        first["item_id"] = "unrequested"
    elif fault == "timeout":
        settings = {"sleep": 2}
    elif fault == "nonzero":
        settings = {"exit": 9}
    elif fault == "bad-span":
        first["omission"] = {"source_id": "source-1", "span": {"start": 0, "end": 900}}
    elif fault == "wrong-source":
        first["omission"] = {"source_id": "other", "span": {"start": 0, "end": 4}}
    elif fault == "blank-reason":
        first["reason"] = " "
    elif fault == "unknown-field":
        first["score"] = 1
    elif fault == "wrong-type":
        first["item_id"] = 7
    fake_cli(data, **{provider: {"response": payload, **settings}})
    result = adapter(model="recorded-model", timeout=0.2).judge(data)
    assert result.status == "incomplete" and result.error
    assert result.missing_item_ids
    assert not any(j.item_id == "unrequested" for j in result.judgments)
    if fault == "missing":
        assert result.missing_item_ids == (data.items[1].item_id,)
        assert (
            len(result.judgments) == 1
        )  # U5 can checkpoint valid items and retry missing ones.
    if fault == "duplicate":
        assert data.items[0].item_id in result.missing_item_ids


def test_unknown_concept_is_unresolved_and_never_expanded(fake_cli):
    data = packet(1)
    fake_cli(
        data,
        codex={
            "response": response(
                data, {data.items[0].item_id: {"concept_ids": ["not-in-catalog"]}}
            )
        },
    )
    result = CodexJudge(model="recorded-model").judge(data)
    assert result.status == "incomplete"
    assert result.unresolved_concept_ids == ("not-in-catalog",)
    assert result.judgments[0].concept_ids == ("not-in-catalog",)
    assert "iri" not in result.model_dump_json().lower()


def test_grounded_omissions_and_disagreements_preserve_both_judges(fake_cli):
    data = packet(2)
    root = fake_cli(data)
    codex = CodexJudge(model="recorded-model").judge(data)
    sample = claude_sample(data, codex.judgments, seed=2)
    chosen = sample.item_ids[0]
    subset = data.select(sample.item_ids)
    fake_cli(
        subset,
        claude={
            "response": response(
                subset,
                {
                    chosen: {
                        "omission": {
                            "source_id": "source-1",
                            "span": {"start": 0, "end": 24},
                        },
                        "concept_ids": [],
                        "verdict": "wrong",
                        "reason": "Missed duty.",
                    }
                },
            )
        },
    )
    claude = ClaudeJudge(model="recorded-model").judge(subset)
    assert claude.status == "complete"
    (queue,) = adjudication_items(data, codex, claude, sample)
    assert set(queue.reasons) == {
        "verdict-difference",
        "omission-difference",
        "concept-difference",
    }
    assert queue.codex.verdict == "correct" and queue.claude.verdict == "wrong"
    assert queue.claude.reason == "Missed duty."
    assert len(calls(root)) == 2


def test_missing_sample_and_unsampled_codex_uncertainty_stay_pending(fake_cli):
    data = packet(2)
    fake_cli(
        data,
        codex={
            "response": response(
                data, {data.items[1].item_id: {"verdict": "uncertain"}}
            )
        },
    )
    codex = CodexJudge(model="recorded-model").judge(data)
    sample = claude_sample(data, codex.judgments, seed=1)
    fake_cli(data.select(sample.item_ids), claude={"exit": 1})
    claude = ClaudeJudge(model="recorded-model").judge(data.select(sample.item_ids))
    queue = adjudication_items(data, codex, claude, sample)
    assert {q.item_id for q in queue} == set(sample.item_ids)
    assert all("missing-claude" in q.reasons for q in queue)


def test_capability_failure_and_missing_executable_do_not_invoke_judging(fake_cli):
    data = packet(1)
    root = fake_cli(data, codex={"help": "exec --sandbox --ephemeral"})
    assert CodexJudge(model="recorded-model").judge(data).error == "unsupported-cli"
    assert not (root / "calls.jsonl").exists()
    assert (
        CodexJudge(model="recorded-model", executable=str(root / "absent"))
        .judge(data)
        .error
        == "cli-unavailable"
    )


def test_cancellation_is_incomplete(fake_cli):
    data = packet(1)
    root = fake_cli(data)
    cancelled = threading.Event()
    cancelled.set()
    result = CodexJudge(model="recorded-model").judge(data, cancelled=cancelled)
    assert result.error == "cancelled" and result.status == "incomplete"
    assert not (root / "calls.jsonl").exists()


@pytest.mark.parametrize(
    "adapter,provider", [(CodexJudge, "codex"), (ClaudeJudge, "claude")]
)
@pytest.mark.parametrize("leader_exits", [True, False])
@pytest.mark.parametrize("reason", ["timeout", "cancelled"])
def test_descendant_holding_stdout_cannot_delay_cleanup(
    fake_cli, adapter, provider, leader_exits, reason
):
    data = packet(1)
    root = fake_cli(
        data,
        **{provider: {"descendant": True, "leader_exits": leader_exits, "sleep": 2}},
    )
    cancelled = threading.Event()

    def cancel_when_descendant_is_ready():
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if (root / "descendant.pid").exists():
                if leader_exits:
                    # Let the leader exit and communicate() observe it before
                    # cancellation; otherwise this only exercises a live leader.
                    time.sleep(0.1)
                cancelled.set()
                return
            time.sleep(0.005)

    watcher = threading.Thread(target=cancel_when_descendant_is_ready)
    if reason == "cancelled":
        watcher.start()
    started = time.monotonic()
    try:
        result = adapter(model="recorded-model", timeout=0.25).judge(
            data, cancelled=cancelled
        )
        elapsed = time.monotonic() - started
    finally:
        if reason == "cancelled":
            watcher.join(timeout=3)
    assert result.status == "incomplete" and result.error == reason
    assert result.missing_item_ids == (data.items[0].item_id,)
    assert elapsed < 1.25, f"cleanup took {elapsed:.2f}s for a 0.25s timeout"
    assert (root / "descendant.term").exists()
    # Linux may retain an orphan as a zombie until its reaper runs. It must no
    # longer execute or hold a pipe, even if the original leader already exited.
    pid = (root / "descendant.pid").read_text()
    proc = Path(f"/proc/{pid}/stat")
    reaped_by = time.monotonic() + 0.1
    try:
        while proc.read_text().split()[2] != "Z" and time.monotonic() < reaped_by:
            time.sleep(0.005)
        assert proc.read_text().split()[2] == "Z"
    except FileNotFoundError:
        pass


@pytest.mark.parametrize(
    "adapter,provider", [(CodexJudge, "codex"), (ClaudeJudge, "claude")]
)
@pytest.mark.parametrize("stage", ["version", "auth"])
def test_local_probe_descendants_also_have_bounded_cleanup(
    fake_cli, adapter, provider, stage
):
    probe = (
        ["--version"]
        if stage == "version"
        else (
            ["login", "status"] if provider == "codex" else ["auth", "status", "--json"]
        )
    )
    data = packet(1)
    root = fake_cli(data, **{provider: {"hang_probe": probe, "leader_exits": True}})
    started = time.monotonic()
    result = adapter(model="recorded-model", timeout=0.25).judge(data)
    elapsed = time.monotonic() - started
    assert result.status == "incomplete" and result.error == "timeout"
    assert elapsed < 1.25, f"probe cleanup took {elapsed:.2f}s"
    assert (root / "descendant.term").exists()
    assert not (root / "calls.jsonl").exists()


@pytest.mark.parametrize(
    "envelope",
    [
        {
            "type": "result",
            "subtype": "error_max_turns",
            "is_error": True,
            "structured_output": {"judgments": []},
        },
        {"type": "result", "subtype": "success", "is_error": False, "result": "{}"},
    ],
)
def test_claude_requires_successful_structured_output(fake_cli, envelope):
    data = packet(1)
    fake_cli(data, claude={"raw_envelope": json.dumps(envelope)})
    assert ClaudeJudge(model="recorded-model").judge(data).status == "incomplete"


def test_packet_and_model_output_contracts_are_closed_and_offset_grounded():
    data = packet(1)
    for changes in (
        {"item_id": 1},
        {"codex_reason": "leak"},
        {"span": {"start": 0, "end": 900}},
        {"concept_ids": ["http://invented"]},
        {"source_id": "absent"},
    ):
        body = data.model_dump(mode="json")
        body["items"][0].update(changes)
        with pytest.raises(ValidationError):
            JudgePacket.model_validate(body)
    schema = json.loads(
        (
            Path(__file__).parents[2]
            / "src/folio_insights/measurement/judge.schema.json"
        ).read_text()
    )
    assert schema == VerdictBatch.model_json_schema()
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["JudgeVerdict"]["additionalProperties"] is False


def test_anchor_accuracy_needs_damien_verification_and_reports_denominators(fake_cli):
    data = packet(2)
    fake_cli(data)
    result = CodexJudge(model="recorded-model").judge(data)
    labels = tuple(
        Annotation(
            idempotency_key=f"key-{i}",
            source_id="source-1",
            source_sha256=data.sources[0].sha256,
            genre="opinions",
            run_id="anchor-run",
            item_id=item.item_id,
            partition="tuning",
            action="judge-verdict",
            verdict="correct" if i == 0 else "wrong",
            reason="Human review.",
            annotation_id=f"a{i}",
            author_kind="human",
            author_identity="damien",
            created_at="2026-10-26T12:00:00Z",
        )
        for i, item in enumerate(data.items)
    )
    unanchored = anchor_accuracy(data, result, labels, verification=None)
    assert unanchored.label == "judge agreement, unanchored"
    assert unanchored.accuracy is None
    verification = AnchorVerification(
        idempotency_key="anchor-key",
        genre="opinions",
        anchor_set_id="anchor-1",
        anchor_sha256="a" * 64,
        gold_revision="gold-v1",
        annotation_ids=("a0", "a1"),
        reason="Verified.",
        verification_id="v1",
        author_kind="human",
        author_identity="damien",
        created_at="2026-10-26T12:00:00Z",
    )
    anchored = anchor_accuracy(data, result, labels, verification=verification)
    assert anchored.label == "human-anchored"
    assert (anchored.correct, anchored.denominator, anchored.evaluated) == (1, 2, 2)
    assert anchored.accuracy == 0.5 and anchored.verification_id == "v1"
    incomplete = anchor_accuracy(
        data,
        result.model_copy(update={"judgments": result.judgments[:1]}),
        labels,
        verification=verification,
    )
    assert incomplete.denominator == 2 and incomplete.evaluated == 1
    assert incomplete.accuracy is None
    forged = labels[0].model_copy(
        update={"author_kind": "judge", "author_identity": "codex"}
    )
    with pytest.raises(ValueError, match="human"):
        anchor_accuracy(data, result, (forged, labels[1]), verification=verification)


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({}, set()),
        ({"concept_ids": []}, {"concept-difference"}),
        (
            {"omission": {"source_id": "source-1", "span": {"start": 0, "end": 4}}},
            {"omission-difference"},
        ),
        ({"verdict": "uncertain"}, {"uncertain", "verdict-difference"}),
    ],
)
def test_each_independent_disagreement_requires_adjudication(
    fake_cli, changes, expected
):
    data = packet(1)
    fake_cli(data)
    codex = CodexJudge(model="recorded-model").judge(data)
    sample = claude_sample(data, codex.judgments, seed=0)
    fake_cli(
        data, claude={"response": response(data, {data.items[0].item_id: changes})}
    )
    claude = ClaudeJudge(model="recorded-model").judge(data)
    queue = adjudication_items(data, codex, claude, sample)
    assert (set(queue[0].reasons) if queue else set()) == expected


def test_sampling_realized_coverage_is_in_serialized_receipt():
    sampled = claude_sample(packet(), (), seed=5)
    receipt = sampled.model_dump(mode="json")
    assert receipt["realized_count"] == 2
    assert receipt["coverage"] == 0.2


@pytest.mark.parametrize(
    "adapter,provider", [(CodexJudge, "codex"), (ClaudeJudge, "claude")]
)
def test_cancellation_of_running_cli_returns_missing_coverage(
    fake_cli, adapter, provider
):
    data = packet(1)
    fake_cli(data, **{provider: {"sleep": 2}})
    cancelled = threading.Event()
    timer = threading.Timer(0.3, cancelled.set)
    timer.start()
    try:
        result = adapter(model="recorded-model", timeout=5).judge(
            data, cancelled=cancelled
        )
    finally:
        timer.cancel()
        timer.join()
    assert result.error == "cancelled"
    assert result.missing_item_ids == (data.items[0].item_id,)


def test_sampled_coverage_item_retains_all_prediction_context_for_its_source():
    data = packet()
    coverage = data.items[0].model_copy(
        update={"item_id": "coverage-1", "kind": "gold"}
    )
    data = JudgePacket(
        sources=data.sources,
        items=(*data.items, coverage),
        catalog=data.catalog,
        predictions=data.items,
    )
    subset = data.select(("coverage-1",))
    assert subset.items == (coverage,)
    assert subset.predictions == data.predictions
    assert len(subset.predictions) == 10
    assert "judgments" not in subset.model_dump_json()
