"""Gate 3 — worker image size (REQ-QUALITY-03, D-06).

D-06 thresholds:

- **<500 MB** — hard target, pass.
- **500–700 MB** — accept-with-SLO (xfail); Phase 10 should consider splitting
  HermiT into a dedicated microservice.
- **>700 MB** — hard fail: record in 00-DECISION.md; microservice-split is
  recommended per D-06 (no stack pivot is triggered by Gate 3 alone).

The test resolves a local worker image tag via (in order):

1. ``FOLIO_WORKER_IMAGE`` env var (preferred — CI sets this from Dagger publish).
2. A short probe list of common dev tags.

If no image is locally available, the test skips with an actionable message.
"""
from __future__ import annotations

import os
import subprocess

import pytest

GATE3_HARD_TARGET_BYTES = 500 * 1024 * 1024
GATE3_SLO_CEILING_BYTES = 700 * 1024 * 1024


def _resolve_worker_image() -> str | None:
    """Find a local worker image tag — prefer ``FOLIO_WORKER_IMAGE`` env."""
    candidate = os.environ.get("FOLIO_WORKER_IMAGE")
    if candidate:
        return candidate
    for tag in (
        "ttl.sh/fi-worker:smoke",
        "fi-worker:verify",
        "fi-worker:smoke",
        "fi-worker:locked",
    ):
        r = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", tag],
            capture_output=True,
            text=True,
            check=False,
        )
        if r.returncode == 0:
            return tag
    return None


@pytest.mark.gate3
@pytest.mark.slow
def test_gate3_worker_image_size() -> None:
    """Worker image <500MB target; ≤700MB accept-with-SLO per D-06."""
    image = _resolve_worker_image()
    if image is None:
        pytest.skip(
            "No worker image found locally. Build first: "
            "`docker buildx build -f Dockerfile.worker -t fi-worker:smoke --load .` "
            "or set FOLIO_WORKER_IMAGE env."
        )

    result = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Size}}", image],
        capture_output=True,
        text=True,
        check=True,
    )
    size_bytes = int(result.stdout.strip())
    size_mb = size_bytes / 1024 / 1024

    print(
        f"Gate 3: {image} = {size_mb:.1f} MB "
        f"(target <500MB, accept ≤700MB per D-06)"
    )

    # Pivot-trigger: >700MB is a hard D-06 fail.
    assert size_bytes <= GATE3_SLO_CEILING_BYTES, (
        f"Gate 3 PIVOT TRIGGER: {image} = {size_mb:.1f}MB > 700MB ceiling. "
        f"Record in 00-DECISION.md per D-06 (microservice-split recommended "
        f"for Phase 10)."
    )

    # Accept-with-SLO: 500-700MB — soft fail via xfail, surface in MEASUREMENTS.
    if size_bytes > GATE3_HARD_TARGET_BYTES:
        pytest.xfail(
            f"Gate 3 accept-with-SLO: {image} = {size_mb:.1f}MB > 500MB target, "
            f"≤700MB ceiling. Document in 00-07-MEASUREMENTS.md; Phase 10 "
            f"considers microservice-split. Tuning exhausted per RESEARCH.md "
            f"§Gate 3 playbook."
        )
