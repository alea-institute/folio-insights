"""Provider-reported token usage and the usage ledger (KTD8).

The port returns one :class:`Usage` per call; :class:`UsageLedger` books each call, with its
exact cost, in the queue database's ``llm_usage`` table.

Usage is accounting, not estimation: every number here is what the provider's response said.
When instructor re-asks after a malformed reply, the provider bills every attempt, so the usage
of a call is the sum across its attempts (instructor accumulates it on the final completion, or
on the retry exception when every attempt failed).
"""

from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Usage:
    """Tokens one port call consumed, as the provider reported them."""

    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    #: Portion of ``input_tokens`` served from the provider's prompt cache (if reported).
    cached_input_tokens: int = 0
    attempts: int = 1

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @classmethod
    def from_openai_usage(
        cls, provider: str, model: str, usage: Any, *, attempts: int = 1
    ) -> Usage:
        """Read an OpenAI-shaped ``CompletionUsage`` (every supported endpoint returns one)."""
        if usage is None:
            return cls(provider=provider, model=model, attempts=attempts)
        details = getattr(usage, "prompt_tokens_details", None)
        cached = int(getattr(details, "cached_tokens", 0) or 0) if details is not None else 0
        return cls(
            provider=provider,
            model=model,
            input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            cached_input_tokens=cached,
            attempts=attempts,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class UsageRecord:
    """One port call as the run context and the cost ledger see it."""

    task: str
    template_id: str
    template_hash: str
    usage: Usage
    status: str = "ok"  # "ok" | "error"
    error_kind: str = ""

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["usage"] = self.usage.to_dict()
        return out


# ---- the usage ledger (U3) ----------------------------------------------------------------------

LEDGER_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_usage (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              TEXT NOT NULL,
    job_id              TEXT,
    corpus_id           TEXT NOT NULL DEFAULT '',
    task                TEXT NOT NULL,
    provider            TEXT NOT NULL,
    model               TEXT NOT NULL,
    template_id         TEXT NOT NULL,
    template_hash       TEXT NOT NULL,
    input_tokens        INTEGER NOT NULL,
    output_tokens       INTEGER NOT NULL,
    cached_input_tokens INTEGER NOT NULL,
    attempts            INTEGER NOT NULL,
    status              TEXT NOT NULL,
    error_kind          TEXT NOT NULL DEFAULT '',
    cost_usd            TEXT,
    price_table_version TEXT NOT NULL,
    created_at          REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS llm_usage_by_run ON llm_usage (run_id);
CREATE INDEX IF NOT EXISTS llm_usage_by_corpus ON llm_usage (corpus_id, created_at);
"""


class UsageLedger:
    """Per-call usage and cost rows in the queue database (table ``llm_usage``).

    One row per port call: task, provider, model, template identity, the provider-reported
    tokens, and the exact cost (a decimal string; ``NULL`` when the model is unpriced). Phase 12
    exports these rows as OBS-03 metrics. No prompt text, unit text or credential is stored.
    """

    def __init__(self, path: str | os.PathLike[str], *, clock: Any = time.time) -> None:
        # Created lazily on the first booked call, so a run that never calls an LLM touches
        # no database.
        self.path = Path(path)
        self._clock = clock
        self._ready = False

    def _ensure(self) -> None:
        if self._ready:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=30.0, isolation_level=None)
        try:
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(LEDGER_SCHEMA)
        finally:
            conn.close()
        self._ready = True

    def _connect(self) -> sqlite3.Connection:
        self._ensure()
        conn = sqlite3.connect(self.path, timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def record(
        self,
        record: UsageRecord,
        *,
        run_id: str,
        cost: Decimal | None,
        price_table_version: str,
        job_id: str | None = None,
        corpus_id: str = "",
    ) -> None:
        u = record.usage
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """INSERT INTO llm_usage (run_id, job_id, corpus_id, task, provider, model,
                       template_id, template_hash, input_tokens, output_tokens,
                       cached_input_tokens, attempts, status, error_kind, cost_usd,
                       price_table_version, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, job_id, corpus_id, record.task, u.provider, u.model, record.template_id,
                 record.template_hash, u.input_tokens, u.output_tokens, u.cached_input_tokens,
                 u.attempts, record.status, record.error_kind,
                 None if cost is None else str(cost), price_table_version, self._clock()),
            )
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def rows(self, run_id: str) -> list[dict[str, Any]]:
        if not self._ready and not self.path.exists():
            return []
        conn = self._connect()
        try:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM llm_usage WHERE run_id = ? ORDER BY id", (run_id,))]
        finally:
            conn.close()

    def run_total(self, run_id: str) -> Decimal:
        """Exact spend of a run so far (unpriced rows count as zero; see ``summary``)."""
        return sum((Decimal(r["cost_usd"]) for r in self.rows(run_id) if r["cost_usd"] is not None),
                   Decimal(0))

    def summary(self, run_id: str) -> dict[str, Any]:
        """Run report: per (task, provider, model) tokens and exact cost, plus totals."""
        groups: dict[tuple[str, str, str], dict[str, Any]] = {}
        unpriced = 0
        for r in self.rows(run_id):
            g = groups.setdefault((r["task"], r["provider"], r["model"]), {
                "calls": 0, "input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0,
                "cost_usd": Decimal(0)})
            g["calls"] += 1
            for k in ("input_tokens", "output_tokens", "cached_input_tokens"):
                g[k] += r[k]
            if r["cost_usd"] is None:
                unpriced += 1
            else:
                g["cost_usd"] += Decimal(r["cost_usd"])
        by_task = [
            {"task": t, "provider": p, "model": m, **{**v, "cost_usd": str(v["cost_usd"])}}
            for (t, p, m), v in sorted(groups.items())
        ]
        return {
            "run_id": run_id,
            "calls": sum(g["calls"] for g in groups.values()),
            "total_cost_usd": str(self.run_total(run_id)),
            "unpriced_calls": unpriced,
            "by_task": by_task,
        }
