"""Subscription-only evaluation judges (KTD3/KTD4), separate from pipeline judges.

The coordinator owns durable checkpoints/annotations and retries missing items. This
port returns validated partial coverage and sanitized failure codes, never CLI stderr.
Run it only in evaluator custody: packets and reasons may contain held-out evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import signal
import subprocess
import tempfile
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Literal, Protocol

from pydantic import ConfigDict, model_validator

from folio_insights.measurement.annotations import Annotation, AnchorVerification
from folio_insights.measurement.judge_prompts import render_prompt
from folio_insights.measurement.schema import (
    Genre,
    JudgeIdentity,
    MeasurementModel,
    Nonempty,
    SourceSnapshot,
    SupportingSpan,
)

_IRI = re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]*:[^\s]")
_SCHEMA = Path(__file__).with_name("judge.schema.json")


def _reject_iris(value) -> None:
    if isinstance(value, str) and _IRI.search(value):
        raise ValueError(
            "model output must use opaque selections, never resource identifiers"
        )
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_iris(key)
            _reject_iris(item)
    if isinstance(value, (list, tuple)):
        for item in value:
            _reject_iris(item)


class JudgeModel(MeasurementModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class JudgeSpan(SupportingSpan):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ConceptCandidate(JudgeModel):
    concept_id: Nonempty
    label: Nonempty
    branch: Nonempty

    @model_validator(mode="after")
    def check_selections(self):
        _reject_iris(self.model_dump())
        return self


class JudgeItem(JudgeModel):
    item_id: Nonempty
    source_id: Nonempty
    kind: Literal["prediction", "gold", "omission", "tag"]
    proposition_id: Nonempty
    text: Nonempty
    span: JudgeSpan
    concept_ids: tuple[Nonempty, ...] = ()

    @model_validator(mode="after")
    def check_ids(self):
        _reject_iris(
            (self.item_id, self.source_id, self.proposition_id, *self.concept_ids)
        )
        return self


class JudgePacket(JudgeModel):
    sources: tuple[SourceSnapshot, ...]
    items: tuple[JudgeItem, ...]
    predictions: tuple[JudgeItem, ...]
    catalog: tuple[ConceptCandidate, ...] = ()

    @model_validator(mode="after")
    def check_context(self):
        for ids in (
            [s.source_id for s in self.sources],
            [i.item_id for i in self.items],
            [i.item_id for i in self.predictions],
            [c.concept_id for c in self.catalog],
        ):
            if len(set(ids)) != len(ids):
                raise ValueError("duplicate packet identifier")
        sources = {s.source_id: s for s in self.sources}
        concepts = {c.concept_id for c in self.catalog}
        if any(p.kind != "prediction" for p in self.predictions):
            raise ValueError("prediction context may contain only prediction items")
        for item in (*self.items, *self.predictions):
            if item.source_id not in sources:
                raise ValueError("item source is missing")
            item.span.source_slice(sources[item.source_id].text)
            if not set(item.concept_ids) <= concepts:
                raise ValueError("item selections must be in the candidate catalog")
        return self

    def select(self, item_ids: tuple[str, ...]) -> JudgePacket:
        if len(item_ids) != len(set(item_ids)) or not set(item_ids) <= {
            i.item_id for i in self.items
        }:
            raise ValueError("selection must contain unique known item IDs")
        items = tuple(i for i in self.items if i.item_id in item_ids)
        sources = tuple(
            s for s in self.sources if s.source_id in {i.source_id for i in items}
        )
        predictions = tuple(
            p for p in self.predictions if p.source_id in {s.source_id for s in sources}
        )
        return JudgePacket(
            sources=sources, items=items, predictions=predictions, catalog=self.catalog
        )

    @property
    def sha256(self) -> str:
        return _digest(
            json.dumps(self.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        )


class ProposedOmission(JudgeModel):
    source_id: Nonempty
    span: JudgeSpan


class JudgeVerdict(JudgeModel):
    item_id: Nonempty
    verdict: Literal["correct", "wrong", "uncertain"]
    reason: Nonempty
    omission: ProposedOmission | None
    concept_ids: tuple[Nonempty, ...]

    @model_validator(mode="after")
    def check_no_resources(self):
        _reject_iris(self.model_dump())
        return self


class VerdictBatch(JudgeModel):
    judgments: tuple[JudgeVerdict, ...]


class JudgeResult(MeasurementModel):
    provider: Literal["codex", "claude"]
    status: Literal["complete", "incomplete"]
    identity: JudgeIdentity
    input_sha256: Nonempty
    prompt_sha256: Nonempty
    judgments: tuple[JudgeVerdict, ...] = ()
    missing_item_ids: tuple[str, ...] = ()
    unresolved_concept_ids: tuple[str, ...] = ()
    error: str | None = None


class JudgePort(Protocol):
    def judge(
        self, packet: JudgePacket, *, cancelled: threading.Event | None = None
    ) -> JudgeResult: ...


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _subscription_env() -> dict[str, str]:
    # An allowlist removes all provider keys, proxies, helpers and cloud overrides,
    # including future provider-specific env vars. HOME retains CLI subscription auth.
    allowed = {
        "HOME",
        "PATH",
        "USER",
        "LOGNAME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TERM",
        "TMPDIR",
        "CODEX_HOME",
        "CLAUDE_CONFIG_DIR",
        "XDG_CONFIG_HOME",
    }
    return {k: v for k, v in os.environ.items() if k in allowed}


class _CLIUnavailable(Exception):
    def __init__(self, code: str):
        self.code = code


class _SubscriptionJudge:
    provider: Literal["codex", "claude"]
    required_flags: tuple[str, ...]

    def __init__(
        self, *, model: str, executable: str | None = None, timeout: float = 120
    ):
        if not model.strip() or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("model and positive finite timeout are required")
        self.model = model
        self.executable = executable or self.provider
        self.timeout = timeout

    def _probe(self, cwd: str, env: dict[str, str]) -> str:
        prefix = [self.executable] + (["exec"] if self.provider == "codex" else [])
        for args, is_help in (
            ([*prefix, "--help"], True),
            ([self.executable, "--version"], False),
        ):
            completed = subprocess.run(
                args,
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=self.timeout,
                check=False,
            )
            if completed.returncode:
                raise _CLIUnavailable("cli-unavailable")
            if is_help:
                if any(flag not in completed.stdout for flag in self.required_flags):
                    raise _CLIUnavailable("unsupported-cli")
            else:
                version = completed.stdout.strip()
                if not version:
                    raise _CLIUnavailable("unsupported-cli")
        return version

    def _invoke(
        self,
        args: list[str],
        prompt: str,
        cwd: str,
        env: dict[str, str],
        cancelled: threading.Event | None,
    ) -> str:
        process = subprocess.Popen(
            args,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            start_new_session=True,
        )
        deadline = time.monotonic() + self.timeout
        initial = prompt
        try:
            while True:
                if cancelled is not None and cancelled.is_set():
                    raise _CLIUnavailable("cancelled")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise _CLIUnavailable("timeout")
                try:
                    stdout, _ = process.communicate(
                        initial, timeout=min(0.05, remaining)
                    )
                    if process.returncode:
                        raise _CLIUnavailable("nonzero-exit")
                    return stdout
                except subprocess.TimeoutExpired:
                    initial = None
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.communicate()

    def judge(
        self, packet: JudgePacket, *, cancelled: threading.Event | None = None
    ) -> JudgeResult:
        prompt = render_prompt(packet.model_dump(mode="json"))
        version = "unavailable"
        missing = tuple(i.item_id for i in packet.items)
        result = dict(
            provider=self.provider,
            input_sha256=packet.sha256,
            prompt_sha256=_digest(prompt),
        )
        try:
            if cancelled is not None and cancelled.is_set():
                raise _CLIUnavailable("cancelled")
            with tempfile.TemporaryDirectory(prefix="folio-judge-") as cwd:
                env = _subscription_env()
                version = self._probe(cwd, env)
                if not packet.items:
                    return JudgeResult(
                        **result,
                        status="complete",
                        identity=JudgeIdentity(cli_version=version, model=self.model),
                    )
                args = self._arguments(Path(cwd))
                stdout = self._invoke(args, prompt, cwd, env, cancelled)
                batch = VerdictBatch.model_validate_json(
                    self._read_response(Path(cwd), stdout)
                )
                return self._validate_batch(packet, batch, result, version)
        except _CLIUnavailable as exc:
            error = exc.code
        except subprocess.TimeoutExpired:
            error = "timeout"
        except KeyboardInterrupt:
            error = "cancelled"
        except OSError:
            error = "cli-unavailable"
        except (ValueError, TypeError, KeyError):
            error = "invalid-output"
        return JudgeResult(
            **result,
            status="incomplete",
            error=error,
            missing_item_ids=missing,
            identity=JudgeIdentity(cli_version=version, model=self.model),
        )

    def _validate_batch(self, packet, batch, result, version) -> JudgeResult:
        expected = {i.item_id: i for i in packet.items}
        counts = Counter(j.item_id for j in batch.judgments)
        sources = {s.source_id: s for s in packet.sources}
        valid = []
        invalid = set(counts) != set(expected) or any(n != 1 for n in counts.values())
        for judgment in batch.judgments:
            if judgment.item_id not in expected or counts[judgment.item_id] != 1:
                continue
            omission = judgment.omission
            if omission:
                if omission.source_id != expected[judgment.item_id].source_id:
                    invalid = True
                    continue
                try:
                    omission.span.source_slice(sources[omission.source_id].text)
                except ValueError:
                    invalid = True
                    continue
            valid.append(judgment)
        by_id = {j.item_id: j for j in valid}
        missing = tuple(i.item_id for i in packet.items if i.item_id not in by_id)
        concepts = {c.concept_id for c in packet.catalog}
        unresolved = tuple(
            sorted({c for j in valid for c in j.concept_ids if c not in concepts})
        )
        return JudgeResult(
            **result,
            identity=JudgeIdentity(cli_version=version, model=self.model),
            status="incomplete" if invalid or unresolved else "complete",
            judgments=tuple(
                by_id[i.item_id] for i in packet.items if i.item_id in by_id
            ),
            missing_item_ids=missing,
            unresolved_concept_ids=unresolved,
            error="invalid-coverage"
            if invalid
            else "unresolved-concepts"
            if unresolved
            else None,
        )

    def _arguments(self, cwd: Path) -> list[str]:
        raise NotImplementedError

    def _read_response(self, cwd: Path, stdout: str) -> str:
        raise NotImplementedError


class CodexJudge(_SubscriptionJudge):
    provider = "codex"
    required_flags = (
        "--model",
        "--sandbox",
        "--ephemeral",
        "--skip-git-repo-check",
        "--ignore-user-config",
        "--ignore-rules",
        "--output-schema",
        "--output-last-message",
        "--disable",
        "--config",
    )

    def _arguments(self, cwd: Path) -> list[str]:
        schema = cwd / "schema.json"
        schema.write_bytes(_SCHEMA.read_bytes())
        return [
            self.executable,
            "exec",
            "--model",
            self.model,
            "--sandbox",
            "read-only",
            "--ephemeral",
            "--skip-git-repo-check",
            "--ignore-user-config",
            "--ignore-rules",
            "--disable",
            "shell_tool",
            "--disable",
            "exec_tool",
            "--disable",
            "apply_patch_freeform",
            "--config",
            'web_search="disabled"',
            "--output-schema",
            str(schema),
            "--output-last-message",
            str(cwd / "verdict.json"),
            "-",
        ]

    def _read_response(self, cwd: Path, stdout: str) -> str:
        return (cwd / "verdict.json").read_text()


class ClaudeJudge(_SubscriptionJudge):
    provider = "claude"
    required_flags = (
        "-p",
        "--model",
        "--output-format",
        "--json-schema",
        "--tools",
        "--no-session-persistence",
        "--strict-mcp-config",
        "--mcp-config",
        "--setting-sources",
        "--settings",
        "--safe-mode",
        "--disable-slash-commands",
        "--permission-mode",
    )

    def _arguments(self, cwd: Path) -> list[str]:
        return [
            self.executable,
            "-p",
            "--safe-mode",
            "--model",
            self.model,
            "--output-format",
            "json",
            "--json-schema",
            _SCHEMA.read_text(),
            "--tools",
            "",
            "--no-session-persistence",
            "--strict-mcp-config",
            "--mcp-config",
            '{"mcpServers":{}}',
            "--setting-sources",
            "",
            "--settings",
            '{"disableAllHooks":true}',
            "--disable-slash-commands",
            "--permission-mode",
            "dontAsk",
        ]

    def _read_response(self, cwd: Path, stdout: str) -> str:
        envelope = json.loads(stdout)
        if (
            envelope["type"] != "result"
            or envelope["subtype"] != "success"
            or envelope["is_error"] is not False
        ):
            raise ValueError("Claude did not return a successful structured result")
        return json.dumps(envelope["structured_output"])


class SampleStratum(MeasurementModel):
    genre: Genre
    source_id: Nonempty
    kind: Literal["prediction", "gold", "omission", "tag"]
    denominator: int
    sampled: int


class ClaudeSample(MeasurementModel):
    seed: int
    item_ids: tuple[str, ...]
    denominator: int
    base_sample_count: int
    strata: tuple[SampleStratum, ...]

    realized_count: int
    coverage: float | None


def claude_sample(
    packet: JudgePacket, codex_judgments: tuple[JudgeVerdict, ...], *, seed: int
) -> ClaudeSample:
    if seed < 0:
        raise ValueError("sampling seed must be nonnegative")
    sources = {s.source_id: s for s in packet.sources}
    groups = {}
    for item in packet.items:
        key = (sources[item.source_id].genre, item.source_id, item.kind)
        groups.setdefault(key, []).append(item.item_id)
    ids = {i.item_id for i in packet.items}
    if not {j.item_id for j in codex_judgments} <= ids:
        raise ValueError("Codex judgments reference unrequested items")
    selected = set()
    for key, members in sorted(groups.items()):
        ordered = sorted(
            members, key=lambda item: _digest(json.dumps([seed, *key, item]))
        )
        selected.update(ordered[: math.ceil(len(members) / 5)])
    base_count = len(selected)
    selected.update(j.item_id for j in codex_judgments if j.verdict == "uncertain")
    return ClaudeSample(
        seed=seed,
        item_ids=tuple(sorted(selected)),
        denominator=len(ids),
        base_sample_count=base_count,
        realized_count=len(selected),
        coverage=len(selected) / len(ids) if ids else None,
        strata=tuple(
            SampleStratum(
                genre=key[0],
                source_id=key[1],
                kind=key[2],
                denominator=len(members),
                sampled=len(selected.intersection(members)),
            )
            for key, members in sorted(groups.items())
        ),
    )


class AdjudicationItem(MeasurementModel):
    item_id: Nonempty
    reasons: tuple[str, ...]
    codex: JudgeVerdict | None
    claude: JudgeVerdict | None


def adjudication_items(
    packet: JudgePacket, codex: JudgeResult, claude: JudgeResult, sample: ClaudeSample
) -> tuple[AdjudicationItem, ...]:
    if (
        codex.provider != "codex"
        or claude.provider != "claude"
        or codex.input_sha256 != packet.sha256
        or claude.input_sha256 != packet.select(sample.item_ids).sha256
    ):
        raise ValueError("judgments must belong to the same independent input packets")
    first = {j.item_id: j for j in codex.judgments}
    second = {j.item_id: j for j in claude.judgments}
    queue = []
    for item in packet.items:
        a, b = first.get(item.item_id), second.get(item.item_id)
        reasons = []
        if a is None:
            reasons.append("missing-codex")
        if item.item_id in sample.item_ids and b is None:
            reasons.append("missing-claude")
        if (a and a.verdict == "uncertain") or (b and b.verdict == "uncertain"):
            reasons.append("uncertain")
        if a and b:
            if a.verdict != b.verdict:
                reasons.append("verdict-difference")
            if a.omission != b.omission:
                reasons.append("omission-difference")
            if set(a.concept_ids) != set(b.concept_ids):
                reasons.append("concept-difference")
        if reasons:
            queue.append(
                AdjudicationItem(
                    item_id=item.item_id, reasons=tuple(reasons), codex=a, claude=b
                )
            )
    return tuple(queue)


class AnchorAccuracy(MeasurementModel):
    provider: Literal["codex", "claude"]
    genre: Genre | None
    label: Literal["judge agreement, unanchored", "human-anchored"]
    verification_id: str | None
    correct: int
    denominator: int
    evaluated: int
    accuracy: float | None


def anchor_accuracy(
    packet: JudgePacket,
    result: JudgeResult,
    labels: tuple[Annotation, ...],
    *,
    verification: AnchorVerification | None,
) -> AnchorAccuracy:
    if result.input_sha256 != packet.sha256:
        raise ValueError("judge result does not belong to the anchor packet")
    if verification is None:
        return AnchorAccuracy(
            provider=result.provider,
            genre=None,
            label="judge agreement, unanchored",
            verification_id=None,
            correct=0,
            denominator=0,
            evaluated=0,
            accuracy=None,
        )
    by_id = {a.annotation_id: a for a in labels}
    if len(by_id) != len(labels) or len(set(verification.annotation_ids)) != len(
        verification.annotation_ids
    ):
        raise ValueError("anchor labels must be unique")
    sources = {s.source_id: s for s in packet.sources}
    items = {i.item_id: i for i in packet.items}
    chosen = []
    for annotation_id in verification.annotation_ids:
        a = by_id.get(annotation_id)
        if a is None or a.author_kind != "human":
            raise ValueError("anchor requires verified human labels")
        if (
            a.genre != verification.genre
            or a.source_id not in sources
            or sources[a.source_id].genre != verification.genre
            or a.source_sha256 != sources[a.source_id].sha256
            or a.item_id not in items
            or items[a.item_id].source_id != a.source_id
        ):
            raise ValueError("anchor labels do not match the source/genre/item context")
        chosen.append(a)
    if len({a.item_id for a in chosen}) != len(chosen):
        raise ValueError("anchor requires one human label per item")
    judgments = {j.item_id: j for j in result.judgments}
    evaluated = sum(a.item_id in judgments for a in chosen)
    correct = sum(
        a.item_id in judgments and judgments[a.item_id].verdict == a.verdict
        for a in chosen
    )
    return AnchorAccuracy(
        provider=result.provider,
        genre=verification.genre,
        label="human-anchored",
        verification_id=verification.verification_id,
        correct=correct,
        denominator=len(chosen),
        evaluated=evaluated,
        accuracy=correct / len(chosen) if chosen and evaluated == len(chosen) else None,
    )
