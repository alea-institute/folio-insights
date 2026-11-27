"""Exercise the perf marker through pytest without running a timed benchmark."""

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("opt_in", [False, True], ids=["default", "enabled"])
def test_perf_opt_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, opt_in: bool
) -> None:
    if opt_in:
        monkeypatch.setenv("FOLIO_INSIGHTS_PERF", "1")
    else:
        monkeypatch.delenv("FOLIO_INSIGHTS_PERF", raising=False)
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)

    probe = tmp_path / "test_perf_probe.py"
    probe.write_text(
        "import pytest\n\n"
        "@pytest.mark.perf\n"
        "def test_perf_probe():\n"
        "    pass\n\n"
        "def test_unmarked_probe():\n"
        "    pass\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest", "-v", "-rs", "-p", "no:cacheprovider",
            "-p", "tests.conftest", "-c", "pyproject.toml", "--strict-markers", str(probe),
        ],
        cwd=Path(__file__).resolve().parents[1],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout
    assert "::test_unmarked_probe PASSED" in result.stdout, result.stdout
    outcome = "PASSED" if opt_in else "SKIPPED"
    assert f"::test_perf_probe {outcome}" in result.stdout, result.stdout
    if not opt_in:
        assert "FOLIO_INSIGHTS_PERF=1" in result.stdout, result.stdout
