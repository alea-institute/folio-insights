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
"""
from __future__ import annotations

import hashlib
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import jcs
from fastapi import HTTPException

from folio_insights.proposals.decisions import DecisionInvalid, validate_decided_by

if TYPE_CHECKING:
    from folio_insights.proposals.registry import Proposal, ProposalRegistry
    from folio_insights.storage import CorpusStorageContext

CORPUS_ROOT_ENV = "FOLIO_INSIGHTS_CORPUS_ROOT"
REVIEWER_ENV = "FOLIO_INSIGHTS_REVIEWER"
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
                "no reviewer is configured; proposed-class decisions need a named human "
                f"reviewer (set ${REVIEWER_ENV} to a handle). Nothing was recorded."
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
                f"the configured reviewer (${REVIEWER_ENV}) is not a valid reviewer handle "
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
    except StorageError as exc:
        raise HTTPException(
            status_code=503, detail=f"proposal ledger unavailable ({type(exc).__name__})"
        ) from None
    try:
        yield ctx
    finally:
        await ctx.close()


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
    "REVIEWER_ENV",
    "client_op_id",
    "configured_reviewer",
    "decision_view",
    "derived_op_id",
    "ledger_corpus",
    "open_ledger",
    "proposal_view",
    "registry_view",
    "storage_root",
]
