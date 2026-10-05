"""Provider-reported token usage and the usage ledger (KTD8).

The port returns one :class:`Usage` per call; :class:`UsageLedger` books each call, with its
cost, in the queue database's ``llm_usage`` table.

Usage is accounting, not estimation, wherever the provider reported it: when instructor re-asks
after a malformed reply the provider bills every attempt, so the usage of a call is the sum
across its attempts. An attempt that *may* have been billed but reported nothing (a read
timeout after the request went out, a 5xx, a cancellation, a 2xx without a ``usage`` block) is
counted in :attr:`Usage.unaccounted_attempts`; the cost meter books each such attempt at its
worst case, so the ledger is an upper bound on what the provider can charge.

Stdlib-only: the lean worker image imports it.
"""

from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import asdict, dataclass, field
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
    #: Attempts that may have been billed but returned no usage (booked at worst case).
    unaccounted_attempts: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @classmethod
    def from_openai_usage(
        cls, provider: str, model: str, usage: Any, *, attempts: int = 1,
        unaccounted_attempts: int = 0,
    ) -> Usage:
        """Read an OpenAI-shaped ``CompletionUsage`` (every supported endpoint returns one).

        Output tokens are ``max(completion_tokens, total_tokens - prompt_tokens)``: Gemini bills
        "thinking" tokens that some compatibility responses count in ``total_tokens`` only.
        """
        if usage is None:
            return cls(provider=provider, model=model, attempts=attempts,
                       unaccounted_attempts=unaccounted_attempts)
        details = getattr(usage, "prompt_tokens_details", None)
        cached = int(getattr(details, "cached_tokens", 0) or 0) if details is not None else 0
        prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion = int(getattr(usage, "completion_tokens", 0) or 0)
        total = int(getattr(usage, "total_tokens", 0) or 0)
        return cls(
            provider=provider,
            model=model,
            input_tokens=prompt,
            output_tokens=max(completion, total - prompt),
            cached_input_tokens=cached,
            attempts=attempts,
            unaccounted_attempts=unaccounted_attempts,
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
    #: Worst-case cost booked for :attr:`Usage.unaccounted_attempts` (set by the meter).
    worst_case_usd: Decimal = field(default=Decimal(0))

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["usage"] = self.usage.to_dict()
        out["worst_case_usd"] = str(self.worst_case_usd)
        return out


# ---- the usage ledger (U3) ----------------------------------------------------------------------

LEDGER_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_usage (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id               TEXT NOT NULL,
    job_id               TEXT,
    corpus_id            TEXT NOT NULL DEFAULT '',
    task                 TEXT NOT NULL,
    provider             TEXT NOT NULL,
    model                TEXT NOT NULL,
    template_id          TEXT NOT NULL,
    template_hash        TEXT NOT NULL,
    input_tokens         INTEGER NOT NULL,
    output_tokens        INTEGER NOT NULL,
    cached_input_tokens  INTEGER NOT NULL,
    attempts             INTEGER NOT NULL,
    unaccounted_attempts INTEGER NOT NULL DEFAULT 0,
    status               TEXT NOT NULL,
    error_kind           TEXT NOT NULL DEFAULT '',
    cost_usd             TEXT,
    price_table_version  TEXT NOT NULL,
    created_at           REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS llm_usage_by_run ON llm_usage (run_id);
CREATE INDEX IF NOT EXISTS llm_usage_by_corpus ON llm_usage (corpus_id, created_at);
"""

#: Ledger row status while a call is in flight. Its ``cost_usd`` is the worst case reserved for
#: the attempts sent so far, so a crash mid-call leaves the run charged at that bound.
IN_FLIGHT = "in_flight"


class UsageLedger:
    """Per-call usage and cost rows in the queue database (table ``llm_usage``).

    One row per port call: task, provider, model, template identity, the provider-reported
    tokens, and the cost (a decimal string; ``NULL`` when the model is unpriced). A row is
    written ``in_flight`` before the first request of a call goes out and settled when the call
    ends; :meth:`run_total` counts unsettled rows at their reserved worst case. Phase 12 exports
    these rows as OBS-03 metrics. No prompt text, unit text or credential is stored.
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
            cols = {r[1] for r in conn.execute("PRAGMA table_info(llm_usage)")}
            if "unaccounted_attempts" not in cols:  # ledgers created before this column
                conn.execute("ALTER TABLE llm_usage ADD COLUMN unaccounted_attempts "
                             "INTEGER NOT NULL DEFAULT 0")
        finally:
            conn.close()
        self._ready = True

    def _connect(self) -> sqlite3.Connection:
        self._ensure()
        conn = sqlite3.connect(self.path, timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _write(self, sql: str, params: tuple[Any, ...]) -> int:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(sql, params)
            conn.execute("COMMIT")
            return int(cur.lastrowid or 0)
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def open_in_flight(
        self,
        *,
        run_id: str,
        task: str,
        provider: str,
        model: str,
        template_id: str,
        template_hash: str,
        reserved: Decimal,
        price_table_version: str,
        job_id: str | None = None,
        corpus_id: str = "",
    ) -> int:
        """Write the ``in_flight`` row for a call about to send its first request."""
        return self._write(
            """INSERT INTO llm_usage (run_id, job_id, corpus_id, task, provider, model,
                   template_id, template_hash, input_tokens, output_tokens, cached_input_tokens,
                   attempts, unaccounted_attempts, status, error_kind, cost_usd,
                   price_table_version, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 1, 0, ?, '', ?, ?, ?)""",
            (run_id, job_id, corpus_id, task, provider, model, template_id, template_hash,
             IN_FLIGHT, str(reserved), price_table_version, self._clock()),
        )

    def raise_in_flight(self, row_id: int, reserved: Decimal, attempts: int) -> None:
        """A further attempt went out: raise the row's reserved worst case."""
        self._write("UPDATE llm_usage SET cost_usd = ?, attempts = ? WHERE id = ? AND status = ?",
                    (str(reserved), attempts, row_id, IN_FLIGHT))

    def settle(self, row_id: int, record: UsageRecord, *, cost: Decimal | None) -> None:
        """Replace an ``in_flight`` row with the call's settled usage and cost."""
        u = record.usage
        self._write(
            """UPDATE llm_usage SET input_tokens = ?, output_tokens = ?, cached_input_tokens = ?,
                   attempts = ?, unaccounted_attempts = ?, status = ?, error_kind = ?,
                   cost_usd = ? WHERE id = ?""",
            (u.input_tokens, u.output_tokens, u.cached_input_tokens, u.attempts,
             u.unaccounted_attempts, record.status, record.error_kind,
             None if cost is None else str(cost), row_id),
        )

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
        """Book a settled call in one step (a call that never needed an in-flight row)."""
        u = record.usage
        self._write(
            """INSERT INTO llm_usage (run_id, job_id, corpus_id, task, provider, model,
                   template_id, template_hash, input_tokens, output_tokens,
                   cached_input_tokens, attempts, unaccounted_attempts, status, error_kind,
                   cost_usd, price_table_version, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, job_id, corpus_id, record.task, u.provider, u.model, record.template_id,
             record.template_hash, u.input_tokens, u.output_tokens, u.cached_input_tokens,
             u.attempts, u.unaccounted_attempts, record.status, record.error_kind,
             None if cost is None else str(cost), price_table_version, self._clock()),
        )

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
        """Spend of a run so far, an upper bound: settled cost plus in-flight reservations.

        Unpriced rows count as zero (``summary`` reports them; a capped run refuses them).
        """
        return sum((Decimal(r["cost_usd"]) for r in self.rows(run_id) if r["cost_usd"] is not None),
                   Decimal(0))

    def summary(self, run_id: str) -> dict[str, Any]:
        """Run report: per (task, provider, model) tokens and cost, plus totals."""
        groups: dict[tuple[str, str, str], dict[str, Any]] = {}
        unpriced = in_flight = 0
        for r in self.rows(run_id):
            g = groups.setdefault((r["task"], r["provider"], r["model"]), {
                "calls": 0, "input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0,
                "unaccounted_attempts": 0, "cost_usd": Decimal(0)})
            g["calls"] += 1
            for k in ("input_tokens", "output_tokens", "cached_input_tokens",
                      "unaccounted_attempts"):
                g[k] += r[k]
            in_flight += r["status"] == IN_FLIGHT
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
            "in_flight_calls": in_flight,
            "by_task": by_task,
        }
