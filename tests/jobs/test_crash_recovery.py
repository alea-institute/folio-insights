"""Crash and restart recovery, as real child processes killed with SIGKILL (Phase 10 U2).

* Worker kill: a worker dies mid-stage; a new worker leases the job after the lease expires and
  resumes from the last stage checkpoint. The completed stage never runs twice and its output
  is not duplicated.
* API restart: the API process (with its embedded worker) dies mid-job; the restarted API
  finishes the job.
* API restart with a per-request key: the key lived only in the dead process's memory, so the
  job parks as ``needs_credentials``; the user re-supplies the key to the restarted API and the
  job completes. Neither the queue database, the outputs, the checkpoints nor either process's
  logs ever contain the key.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from folio_insights.jobs import JobStatus, SQLiteJobQueue

REPO = Path(__file__).resolve().parents[2]
PY = sys.executable
FAKE_KEY = "AIzaTestFAKEKEYrestart0123456789abcdef"
LEASE = "1.0"


def _env(tmp: Path, **extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if not k.endswith("_API_KEY") and not k.startswith("LLM_")}
    env.update({
        "PYTHONPATH": f"{REPO / 'src'}{os.pathsep}{REPO}",
        "FOLIO_INSIGHTS_QUEUE_DB": str(tmp / "queue.sqlite3"),
        "FOLIO_INSIGHTS_CORPUS_ROOT": str(tmp / "corpora"),
        "FOLIO_INSIGHTS_JOB_LEASE_SECONDS": LEASE,
        "FAKE_PIPELINE_LOG": str(tmp / "stages.log"),
        "FAKE_PIPELINE_RELEASE": str(tmp / "release"),
        "PYTHONUNBUFFERED": "1",
    })
    env.update(extra)
    return env


def _wait_for(predicate, timeout: float = 60.0, what: str = "condition") -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {what}")


def _lines(tmp: Path) -> list[str]:
    log = tmp / "stages.log"
    return log.read_text().splitlines() if log.exists() else []


def _kill(proc: subprocess.Popen) -> tuple[str, str]:
    proc.send_signal(signal.SIGKILL)
    out, err = proc.communicate(timeout=30)
    return out, err


def _assert_key_nowhere(tmp: Path, *texts: str) -> None:
    for path in tmp.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            assert FAKE_KEY.encode() not in data and b"FAKEKEY" not in data, path
    for text in texts:
        assert FAKE_KEY not in text and "FAKEKEY" not in text


def test_worker_kill_resumes_from_checkpoint_without_duplicating_output(tmp_path: Path) -> None:
    output = tmp_path / "output"
    (output / "synthetic" / "sources").mkdir(parents=True)
    queue = SQLiteJobQueue(tmp_path / "queue.sqlite3")
    job, _ = queue.enqueue("extract", corpus_id="synthetic", payload={
        "corpus_name": "synthetic", "output_dir": str(output),
        "source_dir": str(output / "synthetic" / "sources"), "llm": {"provider": "ollama"}})
    worker_cmd = [PY, "-m", "folio_insights.worker", "--handlers", "tests.jobs.fake_pipeline:HANDLERS",
                  "--lease-seconds", LEASE, "--poll-interval", "0.05"]

    first = subprocess.Popen(worker_cmd, cwd=tmp_path, env=_env(tmp_path), text=True,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _wait_for(lambda: "fake_slow:start" in _lines(tmp_path), what="the slow stage to start")
    assert queue.get(job.id).status is JobStatus.RUNNING
    _kill(first)  # mid-stage, no chance to clean up

    (tmp_path / "release").touch()
    time.sleep(float(LEASE) + 0.3)  # let the dead worker's lease expire
    second = subprocess.run(worker_cmd + ["--until-idle"], cwd=tmp_path, env=_env(tmp_path),
                            text=True, capture_output=True, timeout=120)
    assert second.returncode == 0, second.stderr[-2000:]

    done = queue.get(job.id)
    assert done.status is JobStatus.SUCCEEDED, done.error
    assert done.attempts == 2
    lines = _lines(tmp_path)
    assert lines.count("fake_ingest") == 1, lines  # resumed from its checkpoint
    assert lines.count("fake_slow:start") == 2 and lines.count("fake_slow:done") == 1
    units = json.loads((output / "synthetic" / "extraction.json").read_text())["units"]
    assert len(units) == 3  # stage output not duplicated
    messages = [e.message for e in queue.events(job.id)]
    assert any("lease expired" in m for m in messages)
    assert "Resumed fake_ingest from checkpoint" in messages


def _api(tmp: Path, mode: str, *args: str, env_extra: dict | None = None) -> list[str]:
    return [PY, "-m", "tests.jobs.api_proc", mode, "--output", str(tmp / "output"),
            "--corpus", "synthetic", *args]


@pytest.mark.parametrize("with_key", [False, True], ids=["keyless-provider", "per-request-key"])
def test_api_restart_continues_the_job(tmp_path: Path, with_key: bool) -> None:
    (tmp_path / "output").mkdir()
    env = _env(tmp_path, **({"USER_KEY": FAKE_KEY, "FAKE_LLM_KEY": FAKE_KEY} if with_key else {}))
    submit_args = ["--provider", "google", "--key-env", "USER_KEY"] if with_key else []
    api1 = subprocess.Popen(_api(tmp_path, "submit", *submit_args), cwd=tmp_path, env=env,
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _wait_for(lambda: "fake_slow:start" in _lines(tmp_path), what="the job to reach the slow stage")
    out1, err1 = _kill(api1)
    submitted = json.loads(out1.splitlines()[0])
    assert submitted["submit"] == 202 and submitted["body"]["status"] == "pending"
    if with_key:
        assert "provider:auth_ok" in _lines(tmp_path)  # the header key reached the provider

    queue = SQLiteJobQueue(tmp_path / "queue.sqlite3")
    job = queue.latest_for("extract", "synthetic")
    assert job.status is JobStatus.RUNNING and job.requires_credentials is with_key

    (tmp_path / "release").touch()
    resume_args = ["--key-env", "USER_KEY"] if with_key else []
    api2 = subprocess.run(_api(tmp_path, "resume", *resume_args), cwd=tmp_path, env=env,
                          text=True, capture_output=True, timeout=180)
    assert api2.returncode == 0, api2.stderr[-3000:]
    final = json.loads(api2.stdout.strip().splitlines()[-1])["final"]
    assert final["status"] == "completed", final

    settled = queue.get(job.id)
    statuses_seen = [e.message for e in queue.events(job.id)]
    if with_key:
        # The restart dropped the in-memory key: the job waited for it, then resumed.
        assert any("re-supply" in m for m in statuses_seen), statuses_seen
        assert any("API key re-supplied" in m for m in statuses_seen)
    else:
        assert any("lease expired, job re-queued" in m for m in statuses_seen)
    lines = _lines(tmp_path)
    assert lines.count("fake_ingest") == 1, lines
    assert settled.result["total_units"] == 3
    _assert_key_nowhere(tmp_path, out1, err1, api2.stdout, api2.stderr)
