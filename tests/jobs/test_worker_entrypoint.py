"""The standalone worker entrypoint runs in the lean worker image (Phase 10 U2).

``Dockerfile.worker`` installs only the reasoning subset (no pydantic, no instructor, no
openai). ``python -m folio_insights.worker`` must still start, recover expired leases and exit
cleanly with ``--until-idle``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from folio_insights.jobs import JobStatus, SQLiteJobQueue

REPO = Path(__file__).resolve().parents[2]

_LEAN = r"""
import importlib.abc, runpy, sys

class _Lean(importlib.abc.MetaPathFinder):
    BLOCKED = ("pydantic", "pydantic_settings", "instructor", "openai", "httpx", "fastapi")
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in self.BLOCKED:
            raise ImportError(f"{name} is not installed in the worker image")
        return None

sys.meta_path.insert(0, _Lean())
sys.argv = ["folio_insights.worker", *sys.argv[1:]]
runpy.run_module("folio_insights.worker", run_name="__main__")
"""


def test_worker_starts_and_recovers_leases_without_web_tier_packages(tmp_path: Path) -> None:
    db = tmp_path / "queue.sqlite3"
    queue = SQLiteJobQueue(db, clock=lambda: 1_000.0)
    job, _ = queue.enqueue("extract", corpus_id="c1")
    queue.lease("dead-api-worker", lease_seconds=1.0)  # its lease expired long ago (real clock)

    env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY")}
    env["PYTHONPATH"] = f"{REPO / 'src'}{os.pathsep}{REPO}"
    proc = subprocess.run(
        [sys.executable, "-c", _LEAN, "--db", str(db), "--until-idle", "--poll-interval", "0.05"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    assert "lease recovery only" in proc.stderr
    assert SQLiteJobQueue(db).get(job.id).status is JobStatus.QUEUED  # reclaimed for a real worker


def test_default_queue_path_follows_the_corpus_storage_root(monkeypatch, tmp_path) -> None:
    from folio_insights.governance.cli._state import resolve_corpus_root
    from folio_insights.jobs import default_queue_path

    monkeypatch.delenv("FOLIO_INSIGHTS_QUEUE_DB", raising=False)
    monkeypatch.setenv("FOLIO_INSIGHTS_CORPUS_ROOT", str(tmp_path / "root"))
    assert default_queue_path() == resolve_corpus_root(None) / "queue" / "jobs.sqlite3"
    monkeypatch.delenv("FOLIO_INSIGHTS_CORPUS_ROOT")
    assert default_queue_path() == resolve_corpus_root(None) / "queue" / "jobs.sqlite3"
    monkeypatch.setenv("FOLIO_INSIGHTS_QUEUE_DB", str(tmp_path / "q.sqlite3"))
    assert default_queue_path() == tmp_path / "q.sqlite3"
