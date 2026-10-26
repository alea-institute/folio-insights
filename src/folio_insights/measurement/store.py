"""Evaluator-local, content-addressed artifacts and transactional item checkpoints.

Keep this directory in evaluator custody. It contains gold and detailed judgments;
only separately sanitized aggregate receipts belong in evidence commits.
"""
from __future__ import annotations

import fcntl
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from pydantic import Field

from folio_insights.measurement.judges import JudgeResult, JudgeVerdict
from folio_insights.measurement.matching import content_digest
from folio_insights.measurement.schema import EvaluationInputs, MeasurementModel, Sha256


class RunReport(MeasurementModel):
    run_id: Sha256
    inputs: EvaluationInputs
    status: Literal["running", "incomplete", "adjudication", "complete"] = "running"
    stage: Literal["extraction", "codex", "claude", "scoring", "finished"] = "extraction"
    errors: dict[str, str] = Field(default_factory=dict)
    artifacts: dict[str, Sha256] = Field(default_factory=dict)
    extractions: dict[str, Sha256] = Field(default_factory=dict)
    missing_item_ids: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    annotation_ids: tuple[str, ...] = ()
    annotation_links: dict[str, str] = Field(default_factory=dict)
    sample: dict | None = None
    adjudication: tuple[dict, ...] = ()
    scores: dict | None = None


class RunStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "runs.sqlite3"
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS artifacts (
                    sha256 TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY, checkpoint TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS attempts (
                    run_id TEXT NOT NULL, provider TEXT NOT NULL, sha256 TEXT NOT NULL,
                    PRIMARY KEY(run_id, provider, sha256));
                CREATE TABLE IF NOT EXISTS judgments (
                    run_id TEXT NOT NULL, provider TEXT NOT NULL, item_id TEXT NOT NULL,
                    payload TEXT NOT NULL, PRIMARY KEY(run_id, provider, item_id));
            """)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.db_path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def lock(self, run_id: str):
        # Serialize the whole resumable operation, including annotation writes.
        if len(run_id) != 64 or any(c not in "0123456789abcdef" for c in run_id):
            raise ValueError("invalid run ID")
        with (self.root / f"{run_id}.lock").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def put(self, payload: object) -> str:
        digest = content_digest(payload)
        with self._db() as db:
            db.execute("INSERT OR IGNORE INTO artifacts VALUES (?, ?)",
                       (digest, json.dumps(payload, ensure_ascii=False, sort_keys=True)))
        return digest

    def artifact(self, digest: str):
        with self._db() as db:
            row = db.execute("SELECT payload FROM artifacts WHERE sha256=?", (digest,)).fetchone()
        if row is None:
            raise ValueError("missing measurement artifact")
        data = json.loads(row[0])
        if content_digest(data) != digest:
            raise ValueError("measurement artifact digest mismatch")
        return data

    def load(self, run_id: str) -> RunReport | None:
        with self._db() as db:
            row = db.execute("SELECT checkpoint FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return RunReport.model_validate_json(row[0]) if row else None

    def save(self, report: RunReport) -> RunReport:
        with self._db() as db:
            db.execute("INSERT INTO runs VALUES (?, ?) ON CONFLICT(run_id) DO UPDATE SET "
                       "checkpoint=excluded.checkpoint", (report.run_id, report.model_dump_json()))
        return report

    def record_result(self, run_id: str, result: JudgeResult, *, keep_judgments: bool) -> str:
        digest = self.put(result.model_dump(mode="json"))
        with self._db() as db:
            db.execute("INSERT OR IGNORE INTO attempts VALUES (?, ?, ?)",
                       (run_id, result.provider, digest))
            if keep_judgments:
                for judgment in result.judgments:
                    db.execute("INSERT INTO judgments VALUES (?, ?, ?, ?)",
                               (run_id, result.provider, judgment.item_id, judgment.model_dump_json()))
        return digest

    def judgments(self, run_id: str, provider: str) -> tuple[JudgeVerdict, ...]:
        with self._db() as db:
            rows = db.execute("SELECT payload FROM judgments WHERE run_id=? AND provider=? "
                              "ORDER BY item_id", (run_id, provider)).fetchall()
        return tuple(JudgeVerdict.model_validate_json(row[0]) for row in rows)

    def results(self, run_id: str) -> tuple[JudgeResult, ...]:
        with self._db() as db:
            rows = db.execute("SELECT sha256 FROM attempts WHERE run_id=? ORDER BY rowid",
                              (run_id,)).fetchall()
        return tuple(JudgeResult.model_validate_json(json.dumps(self.artifact(row[0])))
                     for row in rows)
