"""Gate 4 — SSR cold-page latency (REQ-QUALITY-04, D-07).

D-07 thresholds:

- **<200 ms P95** — hard target, pass.
- **200–400 ms P95** — accept-with-SLO (xfail); document SLO relaxation and
  applied tuning passes in MEASUREMENTS.md.
- **>400 ms P95** — pivot-trigger: deferred-hydration fallback for THAT
  surface (SPA shell + client-side fetch). NOT a full adapter swap; D-07
  scopes the fallback per-surface.

Measurement: ``hyperfine`` drives ``curl`` against each of the 3 D-09
surfaces. We compute P95 manually from ``hyperfine``'s JSON ``times`` array
because hyperfine as of 1.18 does not emit P95 directly.

Prerequisites:

- ``hyperfine`` on PATH (Debian: ``apt install hyperfine``; macOS:
  ``brew install hyperfine``; cross-platform: ``cargo install hyperfine``).
- SvelteKit adapter-node server running (set ``FOLIO_WEB_ORIGIN`` env, e.g.
  ``http://localhost:3000``).
- FastAPI backend running (routed via the adapter-node server's ``fetch``).

Run:

    FOLIO_WEB_ORIGIN=http://localhost:3000 uv run pytest \\
        tests/bench/test_gate4_ssr.py -m gate4 -v
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

GATE4_HARD_TARGET_MS = 200
GATE4_SLO_CEILING_MS = 400

# 3 sample IDs — any hex IRI suffix works for Phase 0 stubs (they echo the id
# back into canned JSON).
SAMPLE_IDS = ["a1b2c3d4e5f60708", "deadbeefcafe0001", "0123456789abcdef"]

# D-09 surfaces
SURFACES = [
    ("shards", "Shard surface"),
    ("polysemy", "Polysemy surface"),
    ("timeline", "Timeline surface"),
]


def _hyperfine_p95_ms(url: str, runs: int = 50, warmup: int = 3) -> float:
    """Run hyperfine, parse times[] from JSON, compute P95 in ms."""
    cmd = [
        "hyperfine",
        "--warmup",
        str(warmup),
        "--runs",
        str(runs),
        "--export-json",
        "-",
        "--style",
        "none",
        f"curl -s -o /dev/null {url}",
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, check=True, timeout=600
    )
    data = json.loads(result.stdout)
    times_s = data["results"][0]["times"]  # list of seconds
    times_ms = sorted(t * 1000 for t in times_s)
    # Nearest-rank P95
    idx = int(0.95 * len(times_ms))
    if idx >= len(times_ms):
        idx = len(times_ms) - 1
    return times_ms[idx]


@pytest.mark.gate4
@pytest.mark.slow
@pytest.mark.skipif(
    shutil.which("hyperfine") is None,
    reason=(
        "hyperfine not on PATH — install via `apt install hyperfine` "
        "or `cargo install hyperfine`"
    ),
)
@pytest.mark.parametrize(
    "surface,label", SURFACES, ids=[s[0] for s in SURFACES]
)
@pytest.mark.parametrize("sample_id", SAMPLE_IDS, ids=lambda x: x[:8])
def test_gate4_cold_page_p95(surface: str, label: str, sample_id: str) -> None:
    """Each surface × 3 IDs = 9 measurements. P95 <200ms hard, ≤400ms accept per D-07."""
    origin = os.environ.get("FOLIO_WEB_ORIGIN")
    if not origin:
        pytest.skip(
            "FOLIO_WEB_ORIGIN not set. Start adapter-node server and set env, "
            "e.g. `FOLIO_WEB_ORIGIN=http://localhost:3000 pytest ...`"
        )

    url = f"{origin}/{surface}/{sample_id}"
    p95_ms = _hyperfine_p95_ms(url)
    print(f"Gate 4: {label} /{surface}/{sample_id[:8]}... P95 = {p95_ms:.1f} ms")

    assert p95_ms <= GATE4_SLO_CEILING_MS, (
        f"Gate 4 PIVOT TRIGGER: {surface} P95 {p95_ms:.1f}ms > 400ms ceiling. "
        f"Record in 00-DECISION.md per D-07 (deferred-hydration fallback for "
        f"this surface)."
    )
    if p95_ms > GATE4_HARD_TARGET_MS:
        pytest.xfail(
            f"Gate 4 accept-with-SLO: {surface} P95 {p95_ms:.1f}ms > 200ms target, "
            f"≤400ms ceiling. Document SLO relaxation + tuning passes applied "
            f"in 00-07-MEASUREMENTS.md (D-07)."
        )
