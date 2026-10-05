"""Phase 11 SHACL-04: the Dagger pipeline verifies the generated SHACL TTL.

The stage itself needs Docker + Dagger; these tests pin that it exists,
runs the generator's --check, and runs before the test stage, and that the
same command passes on this checkout.
"""
from __future__ import annotations

import inspect
import subprocess
import sys
from pathlib import Path

from ci import build

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_pipeline_runs_the_shapes_check_before_tests() -> None:
    assert build.SHAPES_CHECK_CMD == ["python", "scripts/generate_shapes.py", "--check"]
    source = inspect.getsource(build._run_pipeline)
    assert source.index("_shapes_check(client, sde)") < source.index("_test(client, sde)")
    assert "SHAPES_CHECK_CMD" in inspect.getsource(build._shapes_check)


def test_shapes_check_command_passes_here() -> None:
    cmd = [sys.executable, *build.SHAPES_CHECK_CMD[1:]]
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("OK:")
