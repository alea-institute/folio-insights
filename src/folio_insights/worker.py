"""Worker entrypoint: the durable-queue consumer (Phase 10 U2).

``python -m folio_insights.worker`` (the ``Dockerfile.worker`` CMD) leases jobs from the SQLite
queue (``$FOLIO_INSIGHTS_QUEUE_DB``, else ``<corpus storage root>/queue/jobs.sqlite3``), runs the
handlers registered for the worker tier, heartbeats its leases, and re-queues jobs whose worker
died. It replaces the Phase 0 idle stub; there is no Arq or Redis (KTD6).

Options::

    --db PATH              queue database (default: see above)
    --handlers MOD:ATTR    handler registry to load (repeatable; default:
                           folio_insights.jobs.handlers:WORKER_HANDLERS)
    --lease-seconds N      lease length; heartbeats renew it every N/3 seconds (default 60)
    --poll-interval N      idle poll interval in seconds (default 2)
    --paused-ttl N         cancel paused jobs idle longer than N seconds as "expired" (R18;
                           default $FOLIO_INSIGHTS_JOB_PAUSED_TTL_SECONDS else 86400; <= 0 off)
    --until-idle           exit when no runnable job is left (tests, one-shot drains)

The standalone worker never holds an LLM key, and never reads one from its environment.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import logging
import signal
from collections.abc import Sequence

logger = logging.getLogger(__name__)

DEFAULT_HANDLERS = "folio_insights.jobs.handlers:WORKER_HANDLERS"


def _load_handlers(specs: Sequence[str]) -> dict:
    handlers: dict = {}
    for spec in specs:
        module_name, _, attr = spec.partition(":")
        registry = getattr(importlib.import_module(module_name), attr or "WORKER_HANDLERS")
        handlers.update(registry)
    return handlers


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="folio_insights.worker", description=__doc__.split("\n")[0])
    parser.add_argument("--db", default=None, help="queue database path")
    parser.add_argument("--handlers", action="append", default=None,
                        help=f"handler registry MODULE:ATTR (default {DEFAULT_HANDLERS})")
    parser.add_argument("--lease-seconds", type=float, default=60.0)
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--paused-ttl", type=float, default=None)
    parser.add_argument("--until-idle", action="store_true")
    return parser


async def _serve(args: argparse.Namespace) -> None:
    from folio_insights.jobs.queue import SQLiteJobQueue
    from folio_insights.jobs.secrets import SecretStore
    from folio_insights.jobs.worker import JobWorker

    queue = SQLiteJobQueue(args.db)
    handlers = _load_handlers(args.handlers or [DEFAULT_HANDLERS])
    from folio_insights.llm.cost import job_meter_factory  # stdlib-only: fine in the lean image

    worker = JobWorker(
        queue,
        handlers,
        secret_store=SecretStore(),  # empty: this process never holds a user's key
        lease_seconds=args.lease_seconds,
        poll_interval=args.poll_interval,
        meter_factory=job_meter_factory,
        paused_ttl_seconds=args.paused_ttl,  # None -> $FOLIO_INSIGHTS_JOB_PAUSED_TTL_SECONDS
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):  # pragma: no cover - non-POSIX
            pass
    logger.info("worker %s consuming %s (kinds: %s)", worker.owner, queue.path,
                ", ".join(worker.kinds) or "none registered; lease recovery only")
    await worker.run(stop, until_idle=args.until_idle)


def main(argv: Sequence[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    asyncio.run(_serve(args))


if __name__ == "__main__":
    main()
