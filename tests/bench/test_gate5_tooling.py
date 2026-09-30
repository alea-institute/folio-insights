"""Gate 5's tooling check: skip in ordinary runs, fail when the gate is required."""
from __future__ import annotations

import pytest

from tests.bench import test_gate5_digest as gate5


def _no_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gate5.shutil, "which", lambda name: None)


def test_missing_docker_skips_ordinary_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_docker(monkeypatch)
    monkeypatch.delenv("GATE5_REQUIRED", raising=False)
    with pytest.raises(pytest.skip.Exception, match="docker not on PATH"):
        gate5._require_build_tooling()


def test_missing_docker_fails_required_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_docker(monkeypatch)
    monkeypatch.setenv("GATE5_REQUIRED", "1")
    with pytest.raises(pytest.fail.Exception, match="Gate 5 required but cannot build"):
        gate5._require_build_tooling()


def test_unreachable_daemon_is_missing_tooling(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Probe:
        returncode = 1

    monkeypatch.setattr(gate5.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(gate5.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(gate5.subprocess, "run", lambda *a, **k: _Probe())
    assert gate5._missing_build_tooling() == "docker daemon not reachable"
