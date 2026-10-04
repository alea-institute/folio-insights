"""Proposed-class decisions for the review API, through the proposal ledger.

The append-only proposal ledger (``ctx.proposals``, ``folio_insights.proposals``)
is the only store of record for proposed-class decisions. The review API
records through ``ProposalStore.record_decisions`` and reads the folded
registry; the legacy ``review.db`` table ``proposed_class_decisions`` is
read-only (see ``folio_insights.persistence.review_db``).

Mapping (conservative, see docs/storage-operations.md):

* **Corpus.** The ledger corpus is the API corpus ID verbatim: the
  ``output/<corpus>/`` directory name, and the name ``judge_proposals.py
  --corpus`` must use. It must match ``CORPUS_ID``; anything else is refused.
  Proposal IDs hash the corpus, so a mismatched name finds no proposal (404)
  and can never decide another corpus's proposal.
* **Storage root.** ``api.main.configure(corpus_root=...)``, else
  ``$FOLIO_INSIGHTS_CORPUS_ROOT``, else ``~/.folio-insights/corpora``: the same
  resolution as the CLI. The API never creates a root. Without
  ``journal.sqlite3`` the ledger reads as empty. A root inside the served
  output directory is refused.
* **Reviewer.** ``api.main.configure(reviewer=...)``, else
  ``$FOLIO_INSIGHTS_REVIEWER``. A bare handle becomes ``human:<handle>`` and
  must pass ``validate_decided_by``. With none, a write is refused (403). The
  API has no authentication, so the reviewer is server configuration and never
  request input; when authentication lands, it must come from the
  authenticated principal instead.

Access posture (``require_local_opt_in``, on every proposed-class route). The
API has no authentication, so whoever can reach these routes could record a
permanent "human" decision under the configured reviewer's handle, or read
reviewer notes and handles. They are therefore off unless the operator opts in
explicitly with ``FOLIO_INSIGHTS_ALLOW_UNAUTHENTICATED_DECISIONS=1``, and even
then they answer only a loopback client whose ``Host`` header names
``localhost``, ``127.0.0.1`` or ``::1`` (so a DNS-rebinding page cannot use a
local browser to reach them). Everything else is a 403. Other routes are
unaffected. Proper authentication is a follow-up.

Reads go through ``read_ledger_entries_readonly``: a read-only SQLite
connection to the journal, never a full storage context, so a GET never opens
the RDF projection.
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import jcs
from fastapi import HTTPException, Request

from folio_insights.proposals.decisions import DecisionInvalid, validate_decided_by

if TYPE_CHECKING:
    from folio_insights.proposals.registry import Proposal, ProposalRegistry
    from folio_insights.storage import CorpusStorageContext

CORPUS_ROOT_ENV = "FOLIO_INSIGHTS_CORPUS_ROOT"
REVIEWER_ENV = "FOLIO_INSIGHTS_REVIEWER"
OPT_IN_ENV = "FOLIO_INSIGHTS_ALLOW_UNAUTHENTICATED_DECISIONS"
LOOPBACK_HOST_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})
_POSTURE = (
    "Proposed-class decisions through this API are disabled. The API has no "
    "authentication, so anyone who could reach these routes could record a permanent "
    "decision under the configured reviewer's name or read reviewer notes. Record "
    "decisions with scripts/apply_approvals.py, or see 'One approval surface' in "
    "docs/storage-operations.md for the local-only operator opt-in and its risks. "
    "Nothing was recorded."
)


def _is_loopback_address(host: str | None) -> bool:
    if not host:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    mapped = getattr(address, "ipv4_mapped", None)
    return address.is_loopback or (mapped is not None and mapped.is_loopback)


def _host_name(header: str | None) -> str | None:
    """The host part of a ``Host`` header (``name``, ``name:port``, ``[v6]:port``)."""
    if not header:
        return None
    header = header.strip().lower()
    if header.startswith("["):
        end = header.find("]")
        return header[1:end] if end > 0 else None
    if header.count(":") == 1:
        header = header.split(":", 1)[0]
    elif header.count(":") > 1:
        return None  # an unbracketed IPv6 literal is not a valid Host header
    return header


def require_local_opt_in(request: Request) -> None:
    """Refuse (403) unless the operator opted in AND the request is local: a loopback
    client whose ``Host`` names a loopback host. Applied to every proposed-class route."""
    if os.environ.get(OPT_IN_ENV) != "1":
        raise HTTPException(status_code=403, detail=_POSTURE)
    client = request.client.host if request.client else None
    if not _is_loopback_address(client) or _host_name(
        request.headers.get("host")
    ) not in LOOPBACK_HOST_NAMES:
        raise HTTPException(
            status_code=403,
            detail=(
                "Proposed-class routes answer only local requests (a loopback client "
                "addressing localhost, 127.0.0.1 or ::1), because the API has no "
                "authentication. Nothing was recorded."
            ),
        )
CORPUS_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
CLIENT_OP_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,99}")
API_OP_PREFIX = "api:review:"


def configured_reviewer() -> str:
    """The configured reviewer as ``human:<handle>``, or a 403 refusal."""
    from api import main

    raw = main._reviewer if main._reviewer is not None else os.environ.get(REVIEWER_ENV)
    if not raw or not raw.strip():
        raise HTTPException(
            status_code=403,
            detail=(
                "no reviewer is configured, so this server cannot attribute a decision to a "
                "named human reviewer (see 'One approval surface' in "
                "docs/storage-operations.md). Nothing was recorded."
            ),
        )
    raw = raw.strip()
    decided_by = raw if raw.startswith("human:") else f"human:{raw}"
    try:
        return validate_decided_by(decided_by)
    except DecisionInvalid:
        raise HTTPException(
            status_code=403,
            detail=(
                "the configured reviewer is not a valid reviewer handle "
                "(letters, digits, '.', '_' or '-'). Nothing was recorded."
            ),
        ) from None


def ledger_corpus(corpus: str) -> str:
    """The ledger corpus for an API corpus ID (verbatim), or a 400 refusal."""
    if not isinstance(corpus, str) or not CORPUS_ID.fullmatch(corpus):
        raise HTTPException(
            status_code=400,
            detail="corpus must be a corpus ID of letters, digits, '.', '_' or '-'",
        )
    return corpus


def storage_root() -> Path:
    """The corpus storage root, or a 503 refusal when it sits in served output."""
    from api import main
    from folio_insights.storage._paths import inside, inside_served_output
    from folio_insights.storage.errors import StorageError

    if main._corpus_root is not None:
        root = Path(main._corpus_root).expanduser()
    elif os.environ.get(CORPUS_ROOT_ENV):
        root = Path(os.environ[CORPUS_ROOT_ENV]).expanduser()
    else:
        root = Path.home() / ".folio-insights" / "corpora"
    try:
        served = inside(root, main._output_dir) or inside_served_output(root) is not None
    except StorageError:
        served = True
    if served:
        raise HTTPException(
            status_code=503,
            detail=(
                "proposal ledger unavailable: the corpus storage root must not sit inside "
                "the served output directory"
            ),
        )
    return root


@asynccontextmanager
async def open_ledger(corpus: str) -> AsyncIterator[CorpusStorageContext | None]:
    """The storage context of ``corpus``, or ``None`` when the storage root has no
    journal yet (the ledger is then empty). Never creates a storage root."""
    from folio_insights.storage import CorpusStorageContext
    from folio_insights.storage.errors import StorageError
    from folio_insights.storage.journal import JOURNAL_FILENAME

    root = storage_root()
    if not (root / JOURNAL_FILENAME).is_file():
        yield None
        return
    try:
        ctx = await CorpusStorageContext.open(root, corpus)
    except Exception as exc:  # noqa: BLE001 - any open failure means "unavailable"
        kind = type(exc).__name__ if isinstance(exc, StorageError) else "storage open failed"
        raise HTTPException(
            status_code=503, detail=f"proposal ledger unavailable ({kind})"
        ) from None
    try:
        yield ctx
    finally:
        await ctx.close()


async def load_registry_readonly(corpus: str) -> ProposalRegistry | None:
    """The folded registry of ``corpus`` from a read-only connection to the journal, or
    ``None`` when the storage root has no journal. Never opens a storage context or the
    projection, and never creates anything."""
    from folio_insights.proposals.registry import ProposalRegistry
    from folio_insights.storage.journal import JOURNAL_FILENAME
    from folio_insights.storage.proposals import read_ledger_entries_readonly

    journal = storage_root() / JOURNAL_FILENAME
    if not journal.is_file():
        return None
    try:
        entries = await asyncio.to_thread(read_ledger_entries_readonly, journal, corpus)
        return ProposalRegistry.fold(corpus, entries)
    except Exception:  # noqa: BLE001 - an unreadable ledger is "unavailable", never a 500
        raise HTTPException(
            status_code=503, detail="proposal ledger unavailable (read failed)"
        ) from None


def client_op_id(key: str) -> str:
    """The ledger op_id for a client idempotency key, or a 400 refusal."""
    if not isinstance(key, str) or not CLIENT_OP_KEY.fullmatch(key):
        raise HTTPException(
            status_code=400,
            detail=(
                "op_id must be 1-100 characters of letters, digits, '.', '_', ':' or '-', "
                "starting with a letter or digit"
            ),
        )
    return f"{API_OP_PREFIX}key:{key}"


def derived_op_id(corpus: str, decided_by: str, item: dict[str, Any], ledger_head: int) -> str:
    """The server's op_id when the client sends none: a digest of the corpus, reviewer,
    decision and the ledger head it was validated at (``apply_approvals.py``'s rule). A
    retry before commit replays; a repeat after the ledger moved is a new no-op batch that
    keeps the original ``decided_at``."""
    digest = hashlib.sha256(jcs.canonicalize({
        "corpus": corpus, "decided_by": decided_by, "decision": item,
        "ledger_head": ledger_head,
    })).hexdigest()
    return f"{API_OP_PREFIX}auto:{digest[:32]}"


def decision_view(decision: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": decision.get("status"),
        "note": decision.get("note", "") or "",
        "decided_by": decision.get("decided_by"),
        "decided_at": decision.get("decided_at"),
        "merge_into": decision.get("merge_into"),
        "op_id": decision.get("op_id"),
        "ledger_position": decision.get("ledger_position"),
        "provenance": decision.get("provenance"),
    }


def proposal_view(p: Proposal) -> dict[str, Any]:
    """A proposal for the viewer: labels, counts, the current judgment's verdict and the
    current decision. Nothing here is source text."""
    j = p.judgment
    return {
        "proposal_id": p.proposal_id,
        "label": p.proposed_label,
        "normalized_label": p.normalized_label,
        "label_variants": list(p.label_variants),
        "occurrences": p.occurrences,
        "runs": list(p.runs),
        "judgment": None if j is None else {
            "verdict": j.get("verdict"),
            "judged_by": j.get("judged_by"),
            "target_iri": j.get("target_iri"),
            "target_proposal_id": j.get("target_proposal_id"),
        },
        "decision": decision_view(p.decision),
        "decision_history_length": len(p.decision_history),
    }


def registry_view(corpus: str, registry: ProposalRegistry | None) -> dict[str, Any]:
    if registry is None:
        return {"corpus": corpus, "ledger_head": -1, "invalid_decision_items": 0,
                "count": 0, "proposals": []}
    rows = [proposal_view(p) for p in registry.all()]
    return {
        "corpus": corpus,
        "ledger_head": registry.head,
        "invalid_decision_items": len(registry.invalid_decisions),
        "count": len(rows),
        "proposals": rows,
    }


__all__ = [
    "API_OP_PREFIX",
    "OPT_IN_ENV",
    "REVIEWER_ENV",
    "client_op_id",
    "configured_reviewer",
    "decision_view",
    "derived_op_id",
    "ledger_corpus",
    "load_registry_readonly",
    "open_ledger",
    "proposal_view",
    "registry_view",
    "require_local_opt_in",
    "storage_root",
]
