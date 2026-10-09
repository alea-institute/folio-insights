"""folio-enrich bridge API (``/api/bridge/v1``): status read contract + optional ingest.

* ``POST /status`` — corpus status for up to 500 shard IRIs (read-only,
  unauthenticated like the rest of the insights API today; adding auth is a
  documented follow-up).
* ``GET /health`` — liveness plus the corpus shard count.
* ``POST /ingest`` — enabled only while ``FOLIO_INSIGHTS_BRIDGE_TOKEN`` is
  non-empty (checked per request: unset answers 404 as if the route did not
  exist); needs ``Authorization: Bearer <token>``. Idempotent per shard IRI:
  re-pushing a record answers 200 with ``created == 0``. Accepts a JSON record
  (``application/json``) or the NDJSON form (``application/x-ndjson``,
  ``application/ndjson``, ``application/jsonl``, ``application/x-jsonlines``);
  bodies over ``FOLIO_INSIGHTS_BRIDGE_MAX_BODY_BYTES`` (default 20 MiB) answer
  413.

The storage root and corpus follow ``api.services.proposals``: the configured
root, else ``$FOLIO_INSIGHTS_CORPUS_ROOT``, else ``~/.folio-insights/corpora``;
the bridge corpus defaults to ``$FOLIO_INSIGHTS_BRIDGE_CORPUS``, else the app's
default corpus. Responses never contain filesystem paths.
"""
from __future__ import annotations

import hmac
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from folio_insights import __version__ as INSIGHTS_VERSION

router = APIRouter(prefix="/api/bridge/v1", tags=["bridge"])

TOKEN_ENV = "FOLIO_INSIGHTS_BRIDGE_TOKEN"
CORPUS_ENV = "FOLIO_INSIGHTS_BRIDGE_CORPUS"
EXTRACTOR_DID_ENV = "FOLIO_INSIGHTS_BRIDGE_EXTRACTOR_DID"
MAX_BODY_ENV = "FOLIO_INSIGHTS_BRIDGE_MAX_BODY_BYTES"
DEFAULT_MAX_BODY_BYTES = 20 * 1024 * 1024
NDJSON_CONTENT_TYPES = frozenset(
    {"application/x-ndjson", "application/ndjson", "application/jsonl",
     "application/x-jsonlines", "application/jsonlines"}
)


class StatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    iris: list[str] = Field(default_factory=list)
    corpus: str | None = None


def _bridge_corpus(corpus: str | None) -> str:
    from api import main
    from api.services.proposals import ledger_corpus

    name = corpus or os.environ.get(CORPUS_ENV) or main._default_corpus
    return ledger_corpus(name)


def _storage_root():  # noqa: ANN202
    from api.services.proposals import storage_root

    return storage_root()


def _corpus_exists(root: Any, corpus: str) -> bool:
    from folio_insights.storage.journal import JOURNAL_FILENAME, committed_corpora

    try:
        return corpus in committed_corpora(root / JOURNAL_FILENAME)
    except Exception:  # noqa: BLE001 - an unreadable journal is "unavailable"
        raise HTTPException(status_code=503, detail="corpus storage unavailable") from None


async def _open(root: Any, corpus: str):  # noqa: ANN202
    from folio_insights.storage import CorpusStorageContext
    from folio_insights.storage.errors import StorageError

    try:
        return await CorpusStorageContext.open(root, corpus)
    except Exception as exc:  # noqa: BLE001 - never leak paths or tracebacks
        kind = type(exc).__name__ if isinstance(exc, StorageError) else "storage open failed"
        raise HTTPException(status_code=503, detail=f"corpus storage unavailable ({kind})") from None


@router.post("/status")
async def bridge_status(body: StatusRequest) -> dict[str, Any]:
    from folio_insights.bridge_ingest.status import MAX_STATUS_IRIS, normalize_iris, shard_status

    if len(body.iris) > MAX_STATUS_IRIS:
        raise HTTPException(status_code=422, detail=f"at most {MAX_STATUS_IRIS} IRIs per request")
    try:
        wanted = normalize_iris(body.iris)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    corpus = _bridge_corpus(body.corpus)
    root = _storage_root()
    if not _corpus_exists(root, corpus):
        raise HTTPException(status_code=404, detail=f"unknown corpus {corpus!r}")
    ctx = await _open(root, corpus)
    try:
        results = await shard_status(ctx, wanted)
    finally:
        await ctx.close()
    return {
        "corpus": corpus,
        "insights_version": INSIGHTS_VERSION,
        "results": [r.model_dump(mode="json") for r in results],
    }


@router.get("/health")
async def bridge_health(corpus: str | None = Query(default=None)) -> dict[str, Any]:
    """Liveness and shard count. A corpus with no committed rows counts 0 shards."""
    from folio_insights.bridge_ingest.status import shard_count

    name = _bridge_corpus(corpus)
    root = _storage_root()
    if not _corpus_exists(root, name):
        return {"status": "ok", "corpus": name, "shards": 0}
    ctx = await _open(root, name)
    try:
        count = await shard_count(ctx)
    finally:
        await ctx.close()
    return {"status": "ok", "corpus": name, "shards": count}


def _max_body_bytes() -> int:
    raw = os.environ.get(MAX_BODY_ENV, "").strip()
    try:
        value = int(raw) if raw else DEFAULT_MAX_BODY_BYTES
    except ValueError:
        value = DEFAULT_MAX_BODY_BYTES
    return value if value > 0 else DEFAULT_MAX_BODY_BYTES


def _check_token(request: Request) -> None:
    token = os.environ.get(TOKEN_ENV, "")
    if not token.strip():
        raise HTTPException(status_code=404, detail="Not Found")
    header = request.headers.get("authorization", "")
    scheme, _, supplied = header.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(
        supplied.strip().encode("utf-8"), token.strip().encode("utf-8")
    ):
        raise HTTPException(
            status_code=401, detail="bridge ingest needs a valid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def _read_body(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > limit:
                raise HTTPException(status_code=413, detail=f"body exceeds {limit} bytes")
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid Content-Length") from None
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HTTPException(status_code=413, detail=f"body exceeds {limit} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/ingest")
async def bridge_ingest(
    request: Request,
    corpus: str | None = Query(default=None),
    framework_id: str = Query(default="us.case-law.unspecified", min_length=1, max_length=256),
) -> dict[str, Any]:
    from folio_insights.bridge_ingest.errors import BridgeIngestError
    from folio_insights.bridge_ingest.ingest import ingest_record
    from folio_insights.bridge_ingest.mapping import DEFAULT_EXTRACTOR_DID
    from folio_insights.bridge_ingest.record import parse_record_text, record_from_mapping
    from folio_insights.storage.errors import StorageError

    _check_token(request)
    body = await _read_body(request, _max_body_bytes())
    if not body.strip():
        raise HTTPException(status_code=422, detail="empty body")
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    name = _bridge_corpus(corpus)
    root = _storage_root()
    did = os.environ.get(EXTRACTOR_DID_ENV, "").strip() or DEFAULT_EXTRACTOR_DID
    try:
        record = record_from_mapping(
            parse_record_text(body, ndjson=content_type in NDJSON_CONTENT_TYPES)
        )
        report = await ingest_record(
            record, corpus_root=root, corpus=name, framework_id=framework_id,
            extractor_did=did,
        )
    except BridgeIngestError as exc:
        raise HTTPException(status_code=422, detail=f"{type(exc).__name__}: {exc}") from None
    except StorageError as exc:
        raise HTTPException(
            status_code=503, detail=f"corpus storage unavailable ({type(exc).__name__})"
        ) from None
    except ValueError as exc:  # storage input refusals (e.g. an operation-ID conflict)
        raise HTTPException(status_code=409, detail=f"{type(exc).__name__}") from None
    return report.model_dump(mode="json")


__all__ = ["router"]
