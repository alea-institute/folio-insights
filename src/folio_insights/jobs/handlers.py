"""Handler registry for the standalone worker process (``python -m folio_insights.worker``).

The standalone worker runs the worker tier: jobs that need the HermiT/JVM reasoning image and
no LLM key (Phase 9 cluster validation registers its kinds here when it lands). It never holds a
user's API key -- jobs submitted with a per-request key run on the API process's embedded worker,
which is the only process holding that key in memory (KTD3).

With no worker-tier kinds registered yet, the standalone worker still does useful work: it
heartbeats its presence and reclaims expired leases, so a job orphaned by a crashed API process
is re-queued (or parked as ``needs_credentials``) even while no API process is running.
"""

from __future__ import annotations

from folio_insights.jobs.worker import JobHandler

WORKER_HANDLERS: dict[str, JobHandler] = {}
