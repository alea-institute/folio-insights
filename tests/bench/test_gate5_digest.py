"""Gate 5 — bit-identical digest (REQ-OBS-04, D-08).

Two back-to-back Dagger builds with the same SOURCE_DATE_EPOCH must produce
identical digests, which proves the local pipeline is deterministic. Runs when
Docker and the Dagger SDK are available. (A second mode compared against the
Railway-deployed digest; Railway was retired 2026-07-27 and that mode removed.)

Plan 00-05 renamed the CI driver package from ``dagger/`` to ``ci/`` to
avoid shadowing the dagger-io SDK. The subprocess invocation here runs
``ci.build`` as a module under the current interpreter (``sys.executable``),
so a box with only ``python3`` on PATH still works.

Diagnostic: if Mode 1 fails (back-to-back local builds drift), the culprit
is one of the 10 Gate 5 techniques in RESEARCH.md — most commonly:
  1. SOURCE_DATE_EPOCH not plumbed into the Dockerfile (check ARG+ENV)
  2. apt-get/pip cache left in image (check --no-cache-dir, rm -rf)
  3. pip without --require-hashes (check requirements.lock usage)
  4. ``COPY . .`` instead of ordered explicit COPY (check Dockerfiles)
"""
from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys

import pytest

# ttl.sh stdout lines look like:
#   "WEB: ttl.sh/fi-web:<tag> @ ttl.sh/fi-web:<tag>@sha256:<digest>"
#   "WORKER: ttl.sh/fi-worker:<tag> @ ttl.sh/fi-worker:<tag>@sha256:<digest>"
_DIGEST_LINE_RE = re.compile(r"@sha256:([0-9a-f]{64})")


# Two back-to-back Dagger image builds far exceed the suite-wide 30 s
# pytest timeout; each subprocess is itself capped at 1200 s.
_LOCAL_BUILD_TIMEOUT_SECS = 2700


def _missing_build_tooling() -> str | None:
    """Return why Gate 5 cannot build here, or None when it can."""
    if shutil.which("docker") is None:
        return "docker not on PATH"
    if importlib.util.find_spec("dagger") is None:
        return "dagger-io SDK not installed"
    probe = subprocess.run(
        ["docker", "info", "--format", "{{.ServerVersion}}"],
        capture_output=True, text=True, check=False, timeout=30,
    )
    if probe.returncode != 0:
        return "docker daemon not reachable"
    return None


def _require_build_tooling() -> None:
    """Skip when Docker or Dagger is unavailable, unless the gate is required.

    Set ``GATE5_REQUIRED=1`` for a dedicated Gate 5 run: missing tooling then
    fails instead of skipping, so the gate cannot pass without building.
    """
    reason = _missing_build_tooling()
    if reason is None:
        return
    if os.environ.get("GATE5_REQUIRED") == "1":
        pytest.fail(f"Gate 5 required but cannot build: {reason}")
    pytest.skip(f"{reason} — Gate 5 needs Docker and Dagger to build images")


def _dagger_build(tag: str, which: str = "web") -> str:
    """Invoke ``<sys.executable> -m ci.build --no-lint --no-test --tag <tag>``.

    Parses ``WEB:``/``WORKER:`` line from stdout and returns the digest for
    ``which`` (one of ``"web"``, ``"worker"``). Raises ``AssertionError`` if
    the digest cannot be parsed.

    Lint/test are skipped inside this harness: they do not affect published
    image digests, and they'd double the wall-clock cost of every Gate 5 run.

    OTel exporters are explicitly suppressed here so the subprocess does not
    emit trace spans to a nonexistent collector (dagger-io 0.20.x default).
    """
    env = {
        **os.environ,
        # Suppress OTel exporters — Gate 5 runs offline; no collector.
        "OTEL_TRACES_EXPORTER": "none",
        "OTEL_METRICS_EXPORTER": "none",
        "OTEL_LOGS_EXPORTER": "none",
    }
    result = subprocess.run(
        [
            sys.executable, "-m", "ci.build",
            "--no-lint", "--no-test",
            "--tag", tag,
        ],
        capture_output=True, text=True, check=True, timeout=1200, env=env,
    )
    prefix = "WEB:" if which == "web" else "WORKER:"
    for line in result.stdout.splitlines():
        if line.startswith(prefix):
            match = _DIGEST_LINE_RE.search(line)
            if match:
                return "sha256:" + match.group(1)
    raise AssertionError(
        f"Could not parse {which} digest from ci.build output.\n"
        f"stdout:\n{result.stdout}\n---\nstderr (tail):\n{result.stderr[-2000:]}"
    )


@pytest.mark.gate5
@pytest.mark.slow
@pytest.mark.timeout(_LOCAL_BUILD_TIMEOUT_SECS)
def test_local_dagger_builds_bit_identical_web() -> None:
    """Mode 1 (always): two local Dagger builds produce identical web digests."""
    _require_build_tooling()
    digest_a = _dagger_build("gate5-web-a", which="web")
    digest_b = _dagger_build("gate5-web-b", which="web")
    assert digest_a == digest_b, (
        f"Gate 5 LOCAL FAIL (web): back-to-back Dagger builds produced "
        f"different digests.\n"
        f"  a: {digest_a}\n  b: {digest_b}\n"
        "Likely cause: one of the 10 Gate 5 techniques missing (see "
        "RESEARCH.md §Gate 5).\n"
        "  Common culprits: (1) SOURCE_DATE_EPOCH not plumbed into Dockerfile, "
        "(2) apt/pip cache left in image, (3) pip without --require-hashes, "
        "(4) COPY . . without .dockerignore."
    )


@pytest.mark.gate5
@pytest.mark.slow
@pytest.mark.timeout(_LOCAL_BUILD_TIMEOUT_SECS)
def test_local_dagger_builds_bit_identical_worker() -> None:
    """Mode 1 (always): two local Dagger builds produce identical worker digests."""
    _require_build_tooling()
    digest_a = _dagger_build("gate5-worker-a", which="worker")
    digest_b = _dagger_build("gate5-worker-b", which="worker")
    assert digest_a == digest_b, (
        f"Gate 5 LOCAL FAIL (worker): back-to-back Dagger builds produced "
        f"different digests.\n"
        f"  a: {digest_a}\n  b: {digest_b}\n"
        "Likely cause: one of the 10 Gate 5 techniques missing (see "
        "RESEARCH.md §Gate 5). Worker-specific suspects: jlink output path "
        "timestamps, owlready2 sdist compile timestamps (SOURCE_DATE_EPOCH "
        "must reach gcc/musl-dev via pip build-time env)."
    )
