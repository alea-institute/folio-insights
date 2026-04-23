"""Gate 5 — bit-identical digest (REQ-OBS-04, D-08).

Two assertion modes:

  (1) LOCAL: two back-to-back Dagger builds with the same
      SOURCE_DATE_EPOCH must produce identical digests. This proves the
      local pipeline itself is deterministic. Always runs (when Docker +
      Dagger are available).

  (2) RAILWAY: the deployed image digest (pulled from Railway's registry)
      must equal the locally-built digest. This proves the end-to-end
      deploy preserves reproducibility. Skipped when RAILWAY_TOKEN is
      absent.

Plan 00-05 renamed the CI driver package from ``dagger/`` to ``ci/`` to
avoid shadowing the dagger-io SDK. The subprocess invocation here uses
``python -m ci.build`` accordingly.

Diagnostic: if Mode 1 fails (back-to-back local builds drift), the culprit
is one of the 10 Gate 5 techniques in RESEARCH.md — most commonly:
  1. SOURCE_DATE_EPOCH not plumbed into the Dockerfile (check ARG+ENV)
  2. apt-get/pip cache left in image (check --no-cache-dir, rm -rf)
  3. pip without --require-hashes (check requirements.lock usage)
  4. ``COPY . .`` instead of ordered explicit COPY (check Dockerfiles)
"""
from __future__ import annotations

import os
import re
import subprocess

import pytest

# ttl.sh stdout lines look like:
#   "WEB: ttl.sh/fi-web:<tag> @ ttl.sh/fi-web:<tag>@sha256:<digest>"
#   "WORKER: ttl.sh/fi-worker:<tag> @ ttl.sh/fi-worker:<tag>@sha256:<digest>"
_DIGEST_LINE_RE = re.compile(r"@sha256:([0-9a-f]{64})")


def _inspect_digest(image_ref: str) -> str | None:
    """Run ``docker inspect --format '{{.Id}}'``.

    Returns the image ID (``sha256:...``) or ``None`` if the image is absent
    locally.
    """
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.Id}}", image_ref],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _dagger_build(tag: str, which: str = "web") -> str:
    """Invoke ``python -m ci.build --no-deploy --no-lint --no-test --tag <tag>``.

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
        # Force --no-deploy even if the caller's shell has a RAILWAY_TOKEN set.
        "RAILWAY_TOKEN": "",
    }
    result = subprocess.run(
        [
            "python", "-m", "ci.build",
            "--no-deploy", "--no-lint", "--no-test",
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
def test_local_dagger_builds_bit_identical_web() -> None:
    """Mode 1 (always): two local Dagger builds produce identical web digests."""
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
def test_local_dagger_builds_bit_identical_worker() -> None:
    """Mode 1 (always): two local Dagger builds produce identical worker digests."""
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


@pytest.mark.gate5
@pytest.mark.slow
@pytest.mark.skipif(
    not os.environ.get("RAILWAY_TOKEN"),
    reason="RAILWAY_TOKEN not set — Railway deploy not available",
)
@pytest.mark.parametrize("image", ["fi-web", "fi-worker"])
def test_local_matches_railway_deployed_digest(image: str) -> None:
    """Mode 2 (Railway available): local-build digest == Railway-pulled digest.

    Assumes a previous Dagger run published to ``ttl.sh/{image}:gate5-a``
    (Mode 1 runs this). The Railway side pulls from the project's registry
    URL (``$RAILWAY_REGISTRY``, defaults to ``registry.railway.app``).
    """
    which = "web" if image == "fi-web" else "worker"
    local_tag = f"ttl.sh/{image}:gate5-{which}-a"
    local_digest = _inspect_digest(local_tag)
    if not local_digest:
        pytest.skip(
            f"Local {image} image not present at {local_tag}; "
            f"run Mode 1 tests first to populate it."
        )

    railway_registry = os.environ.get("RAILWAY_REGISTRY", "registry.railway.app")
    subprocess.run(
        ["docker", "pull", f"{railway_registry}/{image}:latest"],
        capture_output=True, text=True, check=True, timeout=300,
    )
    railway_digest = _inspect_digest(f"{railway_registry}/{image}:latest")

    assert local_digest == railway_digest, (
        f"Gate 5 RAILWAY FAIL: {image} drift between local and Railway.\n"
        f"  local:   {local_digest}\n  railway: {railway_digest}\n"
        "Record delta in 00-DECISION.md per D-08 (pivot triggers: "
        "investigate SDK version mismatch, registry-side mutation, or "
        "BuildKit variant)."
    )
