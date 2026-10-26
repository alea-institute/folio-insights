"""Subscription judge boundary, exercised only through offline CLI executables."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import tempfile
import threading
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from folio_insights.measurement import judges
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
CODEX_DISABLED_FEATURES = (
    "shell_tool",
    "unified_exec",
    "apps",
    "plugins",
    "remote_plugin",
    "browser_use",
    "browser_use_external",
    "in_app_browser",
    "computer_use",
    "hooks",
    "skill_search",
    "tool_suggest",
    "sleep_tool",
)
CODEX_TEMP_WARNING = (
    "WARNING: proceeding, even though we could not create PATH aliases: "
    'Refusing to create helper binaries under temporary dir "/tmp" '
    "(codex_home: /tmp/folio-judge-example/codex-home)"
)


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


def process_is_running(pid):
    # Orphans can remain as zombies until the host's reaper runs.
    try:
        return Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"
    except FileNotFoundError:
        return False


def wait_until(predicate):
    deadline = time.monotonic() + 5
    while not predicate():
        assert time.monotonic() < deadline, "fake CLI handshake did not complete"
        threading.Event().wait(0.01)


@pytest.fixture
def cli_clock(monkeypatch):
    class Clock:
        started = None

        def monotonic(self):
            # Payload/auth tests must not accidentally exercise startup timeouts.
            return 0.0

        def interrupt_when_ready(
            self, root, reason, *, leader_exits=False, real_timeout=False
        ):
            cancelled = threading.Event()

            def tick():
                if not (root / "ready").exists():
                    return 0.0
                if leader_exits and process_is_running(
                    (root / "leader.pid").read_text()
                ):
                    return 0.0
                if self.started is None:
                    self.started = time.monotonic()
                    if reason == "timeout":
                        return 0.0
                if reason == "cancelled":
                    cancelled.set()
                    return 0.0
                return time.monotonic() - self.started if real_timeout else 1.0

            self.monotonic = tick
            return cancelled

    clock = Clock()
    # Replace only the adapter's time reference, not Python/subprocess clocks.
    monkeypatch.setattr(judges, "time", clock)
    return clock


def acknowledge_descendant_term(root, monkeypatch):
    killpg = os.killpg

    def signal_group(pid, sig):
        killpg(pid, sig)
        if sig == signal.SIGTERM:
            # The fake ignores TERM. Let its handler acknowledge receipt before
            # the adapter's short drain interval can escalate to SIGKILL.
            wait_until(lambda: (root / "descendant.term").exists())

    monkeypatch.setattr(judges.os, "killpg", signal_group)


@pytest.fixture
def fake_cli(tmp_path, monkeypatch, cli_clock):
    root = tmp_path / "bin"
    root.mkdir()
    shutil.copyfile(FIXTURES / "codex-features.txt", root / "codex-features.txt")
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

    # Codex refuses helper binaries beneath /tmp. Keep the fake operator's cache
    # in the allowed fixture tree, isolated and automatically cleaned per test.
    with tempfile.TemporaryDirectory(prefix=".judge-cache-", dir=FIXTURES) as cache:
        monkeypatch.setenv("XDG_CACHE_HOME", cache)
        try:
            yield configure
        finally:
            # Blocking fakes must not leak if a test fails before cleanup.
            if (root / "leader.pid").exists():
                try:
                    os.killpg(int((root / "leader.pid").read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass


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
        pytest.param(
            CodexJudge,
            "codex",
            CODEX_TEMP_WARNING + "\nLogged in using ChatGPT",
            0,
            True,
            id="codex-warning-subscription",
        ),
        pytest.param(
            CodexJudge,
            "codex",
            CODEX_TEMP_WARNING + "\nLogged in using API key",
            0,
            False,
            id="codex-warning-api-key",
        ),
        pytest.param(
            CodexJudge,
            "codex",
            "Unknown extra line\nLogged in using ChatGPT",
            0,
            False,
            id="codex-unknown-extra-line",
        ),
        pytest.param(
            CodexJudge,
            "codex",
            "Logged in using ChatGPT\nLogged in using ChatGPT",
            0,
            False,
            id="codex-duplicate-status",
        ),
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
        assert args == [
            "exec",
            "--model",
            "recorded-model",
            "--sandbox",
            "read-only",
            "--ephemeral",
            "--skip-git-repo-check",
            "--ignore-user-config",
            "--ignore-rules",
            *[arg for name in CODEX_DISABLED_FEATURES for arg in ("--disable", name)],
            "--config",
            'web_search="disabled"',
            "--config",
            "project_doc_max_bytes=0",
            "--config",
            'cli_auth_credentials_store="file"',
            "--output-schema",
            str(Path(call["cwd"]) / "schema.json"),
            "--output-last-message",
            str(Path(call["cwd"]) / "verdict.json"),
            "-",
        ]
        probes = [
            json.loads(line)
            for line in (root / "probes.jsonl").read_text().splitlines()
        ]
        (features,) = [p for p in probes if p["args"] == ["features", "list"]]
        assert features["cwd"] == call["cwd"]
        assert features["env"] == call["env"]
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
    fake_cli, cli_clock, adapter, provider, fault
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
        settings = {"block": True}
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
    root = fake_cli(data, **{provider: {"response": payload, **settings}})
    if fault == "timeout":
        cli_clock.interrupt_when_ready(root, "timeout")
    result = adapter(model="recorded-model", timeout=0.2).judge(data)
    assert result.status == "incomplete" and result.error
    assert result.missing_item_ids
    assert not any(j.item_id == "unrequested" for j in result.judgments)
    if fault == "timeout":
        assert result.error == "timeout"
        assert len(calls(root)) == 1
    else:
        assert result.error != "timeout"
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


def codex_features_with_drift(drift):
    features = (FIXTURES / "codex-features.txt").read_text().splitlines()
    affected = ("unified_exec", "hooks")
    return "\n".join(
        f"{line.split()[0]:<40} {'removed':<18} false"
        if line.split()[0] in affected
        else line
        for line in features
        if drift != "missing" or line.split()[0] not in affected
    )


@pytest.mark.parametrize("drift", ["missing", "removed"])
def test_codex_feature_capability_drift_names_features(fake_cli, drift):
    data = packet(1)
    fake_cli(data, codex={"features": codex_features_with_drift(drift)})
    result = CodexJudge(model="recorded-model").judge(data)
    assert result.status == "incomplete"
    assert result.error == "cli-capability-drift: unified_exec, hooks"
    assert result.missing_item_ids == (data.items[0].item_id,)


@pytest.mark.parametrize("drift", ["missing", "removed"])
def test_codex_feature_capability_failure_never_executes(fake_cli, drift):
    data = packet(1)
    root = fake_cli(data, codex={"features": codex_features_with_drift(drift)})
    CodexJudge(model="recorded-model").judge(data)
    assert not (root / "calls.jsonl").exists()


def test_codex_effective_disable_set_binds_prompt_and_identity(fake_cli, monkeypatch):
    data = packet(1)
    root = fake_cli(data)
    original = CodexJudge(model="recorded-model").judge(data)
    assert original.status == "complete"
    assert (
        "disabled-features=" + ",".join(CODEX_DISABLED_FEATURES) in original.isolation
    )
    monkeypatch.setattr(CodexJudge, "_disabled_features", CODEX_DISABLED_FEATURES[:-1])
    changed = CodexJudge(model="recorded-model").judge(data)
    assert changed.status == "complete"
    assert changed.input_sha256 == original.input_sha256
    assert changed.prompt_sha256 != original.prompt_sha256
    assert changed.judge_identity_sha256 != original.judge_identity_sha256
    for call, result in zip(calls(root), (original, changed), strict=True):
        args = call["args"]
        disabled = [args[i + 1] for i, arg in enumerate(args) if arg == "--disable"]
        assert "disabled-features=" + ",".join(disabled) in result.isolation
        assert json.loads(call["stdin"])["isolation"] == list(result.isolation)


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
    fake_cli, cli_clock, monkeypatch, adapter, provider, leader_exits, reason
):
    data = packet(1)
    root = fake_cli(
        data,
        **{provider: {"descendant": True, "leader_exits": leader_exits}},
    )
    cancelled = cli_clock.interrupt_when_ready(
        root, reason, leader_exits=leader_exits, real_timeout=True
    )
    acknowledge_descendant_term(root, monkeypatch)
    timeout = 0.25
    result = adapter(model="recorded-model", timeout=timeout).judge(
        data, cancelled=cancelled
    )
    assert cli_clock.started is not None
    elapsed = time.monotonic() - cli_clock.started
    assert result.status == "incomplete" and result.error == reason
    assert result.missing_item_ids == (data.items[0].item_id,)
    assert elapsed < timeout + 5, f"cleanup took {elapsed:.2f}s"
    assert (root / "descendant.term").exists()
    assert len(calls(root)) == 1
    pid = (root / "descendant.pid").read_text()
    wait_until(lambda: not process_is_running(pid))


@pytest.mark.parametrize(
    "adapter,provider", [(CodexJudge, "codex"), (ClaudeJudge, "claude")]
)
@pytest.mark.parametrize("stage", ["version", "auth"])
def test_local_probe_descendants_also_have_bounded_cleanup(
    fake_cli, cli_clock, monkeypatch, adapter, provider, stage
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
    cli_clock.interrupt_when_ready(
        root, "timeout", leader_exits=True, real_timeout=True
    )
    acknowledge_descendant_term(root, monkeypatch)
    timeout = 0.25
    result = adapter(model="recorded-model", timeout=timeout).judge(data)
    assert cli_clock.started is not None
    elapsed = time.monotonic() - cli_clock.started
    assert result.status == "incomplete" and result.error == "timeout"
    assert elapsed < timeout + 5, f"probe cleanup took {elapsed:.2f}s"
    assert (root / "descendant.term").exists()
    pid = (root / "descendant.pid").read_text()
    wait_until(lambda: not process_is_running(pid))
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


def anchor_revision(data):
    from folio_insights.measurement.judges import AnchorRevision

    return AnchorRevision(
        anchor_set_id="anchor-1",
        gold_revision="gold-v1",
        packet_sha256=data.sha256,
        item_sha256={
            i.item_id: hashlib.sha256(
                json.dumps(
                    i.model_dump(mode="json"), ensure_ascii=False, sort_keys=True
                ).encode()
            ).hexdigest()
            for i in data.items
        },
    )


def test_anchor_accuracy_needs_damien_verification_and_reports_denominators(fake_cli):
    data = packet(2)
    fake_cli(data)
    revision = anchor_revision(data)
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
        anchor_sha256=revision.sha256,
        gold_revision="gold-v1",
        annotation_ids=("a0", "a1"),
        reason="Verified.",
        verification_id="v1",
        author_kind="human",
        author_identity="damien",
        created_at="2026-10-26T12:00:00Z",
    )
    anchored = anchor_accuracy(
        data,
        result,
        labels,
        verification=verification,
        anchor=revision,
        gold_revision="gold-v1",
    )
    assert anchored.label == "human-anchored"
    assert (anchored.correct, anchored.denominator, anchored.evaluated) == (1, 2, 2)
    assert anchored.accuracy == 0.5 and anchored.verification_id == "v1"
    incomplete = anchor_accuracy(
        data,
        result.model_copy(update={"judgments": result.judgments[:1]}),
        labels,
        verification=verification,
        anchor=revision,
        gold_revision="gold-v1",
    )
    assert incomplete.denominator == 2 and incomplete.evaluated == 1
    assert incomplete.accuracy is None
    forged = labels[0].model_copy(
        update={"author_kind": "judge", "author_identity": "codex"}
    )
    with pytest.raises(ValueError, match="human"):
        anchor_accuracy(
            data,
            result,
            (forged, labels[1]),
            verification=verification,
            anchor=revision,
            gold_revision="gold-v1",
        )


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
    fake_cli, cli_clock, adapter, provider
):
    data = packet(1)
    root = fake_cli(data, **{provider: {"block": True}})
    cancelled = cli_clock.interrupt_when_ready(root, "cancelled")
    result = adapter(model="recorded-model", timeout=5).judge(data, cancelled=cancelled)
    assert result.error == "cancelled"
    assert result.missing_item_ids == (data.items[0].item_id,)
    assert len(calls(root)) == 1


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


@pytest.mark.parametrize(
    "adapter,provider", [(CodexJudge, "codex"), (ClaudeJudge, "claude")]
)
def test_global_instructions_and_memory_are_isolated(fake_cli, adapter, provider):
    data = packet(1)
    root = fake_cli(data, **{provider: {"require_auth_link": provider == "codex"}})
    home = Path(os.environ["HOME"])
    (home / "AGENTS.md").write_text("OPERATOR-AGENTS-POISON")
    (home / "CLAUDE.md").write_text("OPERATOR-CLAUDE-POISON")
    (home / ".claude").mkdir()
    (home / ".claude" / "CLAUDE.md").write_text("OPERATOR-CLAUDE-POISON")
    memory = home / "projects" / "fake-project" / "memory"
    memory.mkdir(parents=True)
    (memory / "MEMORY.md").write_text("OPERATOR-MEMORY-POISON")
    # An empty stand-in, never an actual credential or credential read.
    auth = home / "auth.json"
    auth.touch()
    result = adapter(model="recorded-model").judge(data)
    assert result.status == "complete"
    (call,) = calls(root)
    assert call["discovery"]["instructions"] == []
    assert "POISON" not in json.dumps({k: call[k] for k in ("stdin", "env", "cwd")})
    assert not Path(call["cwd"]).exists()
    if provider == "codex":
        isolated = Path(call["env"]["CODEX_HOME"])
        assert isolated != home and not isolated.exists()
        assert call["discovery"]["config_entries"] == ["auth.json"]
        assert call["discovery"]["auth_link"] == str(auth)
        assert "project_doc_max_bytes=0" in call["args"]
    else:
        assert "--safe-mode" in call["args"]
        settings = json.loads(call["args"][call["args"].index("--settings") + 1])
        assert settings["autoMemoryEnabled"] is False
    assert result.isolation
    identity = {
        "provider": provider,
        "identity": result.identity.model_dump(mode="json"),
        "isolation": list(result.isolation),
    }
    expected = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    assert result.judge_identity_sha256 == expected
    changed = type(result).model_validate(
        result.model_dump(exclude={"judge_identity_sha256"})
        | {"isolation": ("different-policy",)}
    )
    assert changed.judge_identity_sha256 != result.judge_identity_sha256
    assert json.loads(call["stdin"])["isolation"] == list(result.isolation)


@pytest.mark.parametrize("location", ["xdg", "default"])
def test_codex_home_is_private_outside_tmp_and_removed(fake_cli, monkeypatch, location):
    data = packet(1)
    root = fake_cli(data)
    cache = Path(os.environ["XDG_CACHE_HOME"])
    if location == "default":
        home = cache / "operator-home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.delenv("XDG_CACHE_HOME")
        cache = home / ".cache"
    result = CodexJudge(model="recorded-model").judge(data)
    assert result.status == "complete"
    (call,) = calls(root)
    base = cache / "folio-insights" / "judge-homes"
    for key in ("HOME", "CODEX_HOME"):
        isolated = Path(call["env"][key])
        assert not isolated.is_relative_to("/tmp")
        assert isolated.is_relative_to(base)
        assert call["discovery"][key + "_mode"] == 0o700
        assert not isolated.exists()
    assert base.stat().st_mode & 0o777 == 0o700
    assert list(base.iterdir()) == []


@pytest.mark.parametrize(
    "change",
    [
        "text",
        "span",
        "concept_ids",
        "anchor_sha256",
        "gold_revision",
        "item_sha256",
        "missing_anchor",
        "source_sha256",
        "missing_gold_revision",
        "covering_prediction_gold",
        "covering_prediction_omission",
        "catalog_label",
        "catalog_branch",
        "missing_packet_sha256",
        "unchanged",
    ],
)
def test_changed_item_cannot_reuse_human_anchor(fake_cli, change):
    kind = (
        change.removeprefix("covering_prediction_")
        if change.startswith("covering_prediction_")
        else "prediction"
    )
    data = packet(1, kind=kind)
    fake_cli(data)
    revision = anchor_revision(data)
    labels = (
        Annotation(
            idempotency_key="key",
            source_id="source-1",
            source_sha256=data.sources[0].sha256,
            genre="opinions",
            run_id="anchor-run",
            item_id=data.items[0].item_id,
            partition="tuning",
            action="judge-verdict",
            verdict="correct",
            reason="Human review.",
            annotation_id="a0",
            author_kind="human",
            author_identity="damien",
            created_at="2026-10-26T12:00:00Z",
        ),
    )
    verification = AnchorVerification(
        idempotency_key="anchor-key",
        genre="opinions",
        anchor_set_id="anchor-1",
        anchor_sha256=revision.sha256,
        gold_revision="gold-v1",
        annotation_ids=("a0",),
        reason="Verified.",
        verification_id="v1",
        author_kind="human",
        author_identity="damien",
        created_at="2026-10-26T12:00:00Z",
    )
    updates = {
        "text": "A revised claim.",
        "span": {"start": 2, "end": 10},
        "concept_ids": (),
    }
    if change in updates:
        changed = JudgeItem.model_validate(
            data.items[0].model_dump() | {change: updates[change]}
        )
        data = data.model_copy(update={"items": (changed,)})
    elif change == "anchor_sha256":
        verification = verification.model_copy(update={"anchor_sha256": "b" * 64})
    elif change == "source_sha256":
        text = "A party must serve notice."
        source = data.sources[0].model_copy(
            update={
                "text": text,
                "sha256": hashlib.sha256(text.encode()).hexdigest(),
            }
        )
        data = data.model_copy(update={"sources": (source,)})
    elif change == "item_sha256":
        revision = revision.model_copy(
            update={"item_sha256": {data.items[0].item_id: "b" * 64}}
        )
        verification = verification.model_copy(
            update={"anchor_sha256": revision.sha256}
        )
    elif change.startswith("covering_prediction_"):
        assert data.predictions == ()
        covering = data.items[0].model_copy(
            update={"item_id": "covering-prediction", "kind": "prediction"}
        )
        data = data.model_copy(update={"predictions": (covering,)})
    elif change in ("catalog_label", "catalog_branch"):
        field = change.removeprefix("catalog_")
        concept = data.catalog[0].model_copy(update={field: "Changed meaning"})
        data = data.model_copy(update={"catalog": (concept,)})
    elif change == "missing_packet_sha256":
        revision = type(revision).model_validate(
            revision.model_dump(exclude={"packet_sha256"})
        )
        verification = verification.model_copy(
            update={"anchor_sha256": revision.sha256}
        )
    result = CodexJudge(model="recorded-model").judge(data)
    accuracy = anchor_accuracy(
        data,
        result,
        labels,
        verification=verification,
        anchor=None if change == "missing_anchor" else revision,
        gold_revision=None
        if change == "missing_gold_revision"
        else "gold-v2"
        if change == "gold_revision"
        else "gold-v1",
    )
    if change == "unchanged":
        assert accuracy.label == "human-anchored"
        assert accuracy.accuracy == 1.0
        assert accuracy.reason is None
        return
    assert accuracy.label == "judge agreement, unanchored"
    assert accuracy.accuracy is None
    assert accuracy.reason
    if change.startswith("covering_prediction_") or change.startswith("catalog_"):
        assert accuracy.reason == "anchor-packet-context-mismatch"
    elif change == "missing_packet_sha256":
        assert accuracy.reason == "missing-anchor-packet-context"


@pytest.mark.parametrize("adapter", [CodexJudge, ClaudeJudge])
def test_hashed_judge_identity_survives_receipt_round_trip(fake_cli, adapter):
    data = packet(1)
    fake_cli(data)
    result = adapter(model="recorded-model").judge(data)
    restored = type(result).model_validate_json(result.model_dump_json())
    assert restored == result
    receipt = json.loads(result.model_dump_json())
    receipt["isolation"] = ["changed-policy"]
    with pytest.raises(ValidationError, match="identity.*hash"):
        type(result).model_validate_json(json.dumps(receipt))
