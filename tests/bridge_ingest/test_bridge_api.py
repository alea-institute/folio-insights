"""/api/bridge/v1: status, health and the token-gated, idempotent ingest route."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import bridge
from folio_insights.shards.minting import mint_shard_iri
from tests.bridge_ingest.conftest import (
    SYNTHETIC_RECORD,
    SOURCE_URI,
    fixture_record_dict,
    make_record,
    proposition,
)

TOKEN = "test-bridge-token-0123456789"
CORPUS = "api-bridge"
SPAN = "A carrier may limit liability only with a fair opportunity to choose."
ABSENT = "urn:folio:shard/" + "a" * 32


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from api import main

    root = tmp_path / "bridge-corpora"
    monkeypatch.setenv("FOLIO_INSIGHTS_CORPUS_ROOT", str(root))
    monkeypatch.setenv("FOLIO_INSIGHTS_BRIDGE_CORPUS", CORPUS)
    monkeypatch.delenv("FOLIO_INSIGHTS_BRIDGE_TOKEN", raising=False)
    monkeypatch.setattr(main, "_corpus_root", None)
    app = FastAPI()
    app.include_router(bridge.router)
    with TestClient(app) as test_client:
        test_client.root = root  # type: ignore[attr-defined]
        yield test_client


def _push(client: TestClient, body: bytes | str, *, token: str | None = TOKEN,
          content_type: str = "application/json", **params):
    headers = {"Content-Type": content_type}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return client.post("/api/bridge/v1/ingest", content=body, headers=headers, params=params)


def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FOLIO_INSIGHTS_BRIDGE_TOKEN", TOKEN)


def test_ingest_disabled_without_token_env(client: TestClient) -> None:
    response = _push(client, SYNTHETIC_RECORD.read_bytes())
    assert response.status_code == 404


def test_ingest_wrong_or_missing_token(client: TestClient, monkeypatch) -> None:
    _enable(monkeypatch)
    assert _push(client, SYNTHETIC_RECORD.read_bytes(), token="wrong").status_code == 401
    assert _push(client, SYNTHETIC_RECORD.read_bytes(), token=None).status_code == 401


def test_ingest_then_repush_is_idempotent(client: TestClient, monkeypatch) -> None:
    _enable(monkeypatch)
    expected = {
        p["content_iri"] for p in fixture_record_dict()["propositions"] if p.get("content_iri")
    }
    first = _push(client, SYNTHETIC_RECORD.read_bytes())
    assert first.status_code == 200, first.text
    assert set(first.json()["created_iris"]) == expected
    second = _push(client, SYNTHETIC_RECORD.read_bytes())
    assert second.status_code == 200
    body = second.json()
    assert body["created"] == 0 and body["existing"] == len(expected)
    assert str(client.root) not in second.text  # type: ignore[attr-defined]


def test_ingest_ndjson_body(client: TestClient, monkeypatch) -> None:
    _enable(monkeypatch)
    data = make_record(proposition("p1", SPAN)).model_dump(mode="json")
    props = data.pop("propositions")
    lines = [json.dumps({"record_type": "proposition_document", **data})]
    lines += [json.dumps({"record_type": "proposition", **p}) for p in props]
    response = _push(client, "\n".join(lines), content_type="application/x-ndjson")
    assert response.status_code == 200, response.text
    assert response.json()["created_iris"] == [mint_shard_iri(SOURCE_URI, SPAN)[0]]


def test_ingest_refusals(client: TestClient, monkeypatch) -> None:
    _enable(monkeypatch)
    assert _push(client, b"{not json").status_code == 422
    assert _push(client, b"").status_code == 422
    record = make_record(proposition("p1", SPAN), source_uri=None)
    assert _push(client, record.model_dump_json()).status_code == 422
    data = make_record(proposition("p1", SPAN)).model_dump(mode="json")
    data["propositions"][0]["content_iri"] = "urn:folio:shard/" + "0" * 32
    response = _push(client, json.dumps(data))
    assert response.status_code == 422
    assert "ContentIriMismatch" in response.json()["detail"]


def test_ingest_body_cap(client: TestClient, monkeypatch) -> None:
    _enable(monkeypatch)
    monkeypatch.setenv("FOLIO_INSIGHTS_BRIDGE_MAX_BODY_BYTES", "64")
    response = _push(client, SYNTHETIC_RECORD.read_bytes())
    assert response.status_code == 413


def test_status_contract(client: TestClient, monkeypatch) -> None:
    _enable(monkeypatch)
    assert _push(client, SYNTHETIC_RECORD.read_bytes()).status_code == 200
    present = sorted(
        {p["content_iri"] for p in fixture_record_dict()["propositions"] if p.get("content_iri")}
    )
    response = client.post(
        "/api/bridge/v1/status", json={"iris": [ABSENT, present[0], ABSENT, present[1]]}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["corpus"] == CORPUS and body["insights_version"]
    assert [r["iri"] for r in body["results"]] == [ABSENT, present[0], present[1]]
    absent = body["results"][0]
    assert absent == {
        "iri": ABSENT, "present": False, "shard_type": None, "epistemic_status": None,
        "contested": None, "supersedes": None, "superseded_by": None,
        "related": [], "contesting": [], "enrich_sources": [],
    }
    hit = body["results"][1]
    assert set(hit) == set(absent)
    assert hit["present"] is True and hit["shard_type"] == "hypothesis"
    assert hit["epistemic_status"] == "hypothesis" and hit["contested"] is False
    assert hit["enrich_sources"] and set(hit["enrich_sources"][0]) == {
        "document_id", "proposition_id", "proposition_type",
    }


def test_status_validation(client: TestClient, monkeypatch) -> None:
    _enable(monkeypatch)
    _push(client, SYNTHETIC_RECORD.read_bytes())
    bad = client.post("/api/bridge/v1/status", json={"iris": ["urn:folio:shard/NOTHEX"]})
    assert bad.status_code == 422
    over = client.post("/api/bridge/v1/status", json={"iris": [ABSENT] * 501})
    assert over.status_code == 422
    unknown = client.post("/api/bridge/v1/status", json={"iris": [ABSENT], "corpus": "nope"})
    assert unknown.status_code == 404


def test_status_unknown_default_corpus_before_any_ingest(client: TestClient) -> None:
    response = client.post("/api/bridge/v1/status", json={"iris": [ABSENT]})
    assert response.status_code == 404


def test_health(client: TestClient, monkeypatch) -> None:
    empty = client.get("/api/bridge/v1/health")
    assert empty.status_code == 200
    assert empty.json() == {"status": "ok", "corpus": CORPUS, "shards": 0}
    _enable(monkeypatch)
    report = _push(client, SYNTHETIC_RECORD.read_bytes()).json()
    health = client.get("/api/bridge/v1/health").json()
    assert health == {"status": "ok", "corpus": CORPUS, "shards": report["created"]}


def test_router_mounted_on_main_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from api import main

    monkeypatch.setenv("FOLIO_INSIGHTS_CORPUS_ROOT", str(tmp_path / "main-app-root"))
    monkeypatch.setattr(main, "_corpus_root", None)
    monkeypatch.delenv("FOLIO_INSIGHTS_BRIDGE_TOKEN", raising=False)
    client = TestClient(main.app)  # no lifespan: no extraction load, no worker
    assert client.get("/api/bridge/v1/health").json()["status"] == "ok"
    assert client.post("/api/bridge/v1/ingest", content=b"{}").status_code == 404


# ── review fixes: error mappings, token edges, NDJSON variants, lock ─────────

SECRET_PATH = "/home/operator/private/corpora/journal.sqlite3"


def _ndjson(record) -> str:
    data = record.model_dump(mode="json")
    props = data.pop("propositions")
    lines = [json.dumps({"record_type": "proposition_document", **data})]
    lines += [json.dumps({"record_type": "proposition", **p}) for p in props]
    return "\n".join(lines)


def _raise(exc: BaseException):
    async def fake(*_args, **_kwargs):
        raise exc

    return fake


@pytest.mark.parametrize(
    ("exc", "status"),
    [
        ("storage", 503),
        ("busy", 503),
        ("conflict", 409),
        ("value", 409),
    ],
)
def test_ingest_error_mappings_never_leak_paths(client: TestClient, monkeypatch, exc, status) -> None:
    from folio_insights.bridge_ingest import ingest as ingest_module
    from folio_insights.bridge_ingest.manifest import ManifestBusy
    from folio_insights.storage import OperationIdConflict, StorageError

    error = {
        "storage": StorageError(f"cannot open {SECRET_PATH}"),
        "busy": ManifestBusy(f"locked: {SECRET_PATH}"),
        "conflict": OperationIdConflict(f"op committed at {SECRET_PATH}"),
        "value": ValueError(f"bad thing at {SECRET_PATH}"),
    }[exc]
    _enable(monkeypatch)
    monkeypatch.setattr(ingest_module, "ingest_record", _raise(error))
    response = _push(client, SYNTHETIC_RECORD.read_bytes())
    assert response.status_code == status
    assert SECRET_PATH not in response.text
    assert str(client.root) not in response.text  # type: ignore[attr-defined]


def test_status_storage_failure_is_503_without_path(client: TestClient, monkeypatch) -> None:
    from folio_insights.storage import CorpusStorageContext, StorageError

    _enable(monkeypatch)
    assert _push(client, SYNTHETIC_RECORD.read_bytes()).status_code == 200

    async def boom(*_args, **_kwargs):
        raise StorageError(f"cannot open {SECRET_PATH}")

    monkeypatch.setattr(CorpusStorageContext, "open", boom)
    for response in (
        client.post("/api/bridge/v1/status", json={"iris": [ABSENT]}),
        client.get("/api/bridge/v1/health"),
    ):
        assert response.status_code == 503
        assert SECRET_PATH not in response.text


@pytest.mark.parametrize(
    ("header", "status"),
    [
        (f"Basic {TOKEN}", 401),
        (f"Token {TOKEN}", 401),
        (f"Bearer {TOKEN}x", 401),
        (f"Bearer {TOKEN[:-1]}", 401),
        ("Bearer", 401),
        (f"bearer {TOKEN}", 200),        # the scheme is case-insensitive
        (f"Bearer   {TOKEN}  ", 200),    # surrounding whitespace is not part of the token
    ],
)
def test_token_edge_cases(client: TestClient, monkeypatch, header, status) -> None:
    _enable(monkeypatch)
    response = client.post(
        "/api/bridge/v1/ingest", content=SYNTHETIC_RECORD.read_bytes(),
        headers={"Content-Type": "application/json", "Authorization": header},
    )
    assert response.status_code == status, response.text


@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_blank_token_env_disables_route(client: TestClient, monkeypatch, value) -> None:
    monkeypatch.setenv("FOLIO_INSIGHTS_BRIDGE_TOKEN", value)
    assert _push(client, SYNTHETIC_RECORD.read_bytes(), token=value.strip() or "x").status_code == 404


@pytest.mark.parametrize(
    "content_type",
    [
        "application/x-ndjson",
        "application/ndjson",
        "application/jsonl",
        "application/x-jsonlines",
        "application/jsonlines",
        "Application/X-NDJSON; charset=utf-8",
    ],
)
def test_ndjson_content_types(client: TestClient, monkeypatch, content_type) -> None:
    _enable(monkeypatch)
    response = _push(client, _ndjson(make_record(proposition("p1", SPAN))), content_type=content_type)
    assert response.status_code == 200, response.text
    assert response.json()["created"] + response.json()["existing"] == 1


@pytest.mark.parametrize(
    "body",
    [
        '{"record_type": "proposition_document", "document_id": "d"}\n{broken',
        '{"record_type": "proposition", "id": "p"}',                     # no header
        '{"record_type": "mystery"}',                                     # unknown record_type
        '{"record_type": "proposition_document", "document_id": "d"}\n'
        '{"record_type": "proposition_document", "document_id": "e"}',  # two headers
        "[1, 2]",
    ],
)
def test_ndjson_parse_errors(client: TestClient, monkeypatch, body) -> None:
    _enable(monkeypatch)
    response = _push(client, body, content_type="application/x-ndjson")
    assert response.status_code == 422, response.text


def test_whole_record_on_one_ndjson_line(client: TestClient, monkeypatch) -> None:
    """A single NDJSON line holding a whole record (a header with an embedded
    ``propositions`` list) is accepted, as ``record.py`` documents."""
    _enable(monkeypatch)
    data = make_record(proposition("p1", SPAN)).model_dump(mode="json")
    response = _push(client, json.dumps(data), content_type="application/x-ndjson")
    assert response.status_code == 200, response.text


async def _raw_ingest(app, headers: list[tuple[bytes, bytes]], chunks: list[bytes]) -> tuple[int, bytes]:
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
        "scheme": "http", "path": "/api/bridge/v1/ingest", "raw_path": b"/api/bridge/v1/ingest",
        "query_string": b"", "root_path": "", "headers": headers,
        "client": ("127.0.0.1", 50000), "server": ("testserver", 80),
    }
    messages = [
        {"type": "http.request", "body": chunk, "more_body": i < len(chunks) - 1}
        for i, chunk in enumerate(chunks)
    ]

    async def receive():
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, body


def _raw_app() -> FastAPI:
    app = FastAPI()
    app.include_router(bridge.router)
    return app


_AUTH = (b"authorization", f"Bearer {TOKEN}".encode())
_JSON = (b"content-type", b"application/json")


async def test_invalid_content_length_is_400(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FOLIO_INSIGHTS_CORPUS_ROOT", str(tmp_path / "raw"))
    _enable(monkeypatch)
    status, _ = await _raw_ingest(_raw_app(), [_AUTH, _JSON, (b"content-length", b"abc")], [b"{}"])
    assert status == 400


async def test_chunked_body_over_cap_without_content_length_is_413(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FOLIO_INSIGHTS_CORPUS_ROOT", str(tmp_path / "raw"))
    monkeypatch.setenv("FOLIO_INSIGHTS_BRIDGE_MAX_BODY_BYTES", "1000")
    _enable(monkeypatch)
    chunks = [b"x" * 400] * 5  # 2000 bytes, no Content-Length header
    status, body = await _raw_ingest(_raw_app(), [_AUTH, _JSON], chunks)
    assert status == 413
    status, _ = await _raw_ingest(_raw_app(), [_AUTH, _JSON], [b"x" * 400] * 2)
    assert status == 422  # under the cap: read in full, then refused as invalid JSON


def test_held_manifest_lock_does_not_hang_reads(client: TestClient, monkeypatch) -> None:
    import fcntl
    import os
    import time

    from folio_insights.bridge_ingest import manifest as manifest_module

    _enable(monkeypatch)
    assert _push(client, SYNTHETIC_RECORD.read_bytes()).status_code == 200
    monkeypatch.setattr(manifest_module, "LOCK_TIMEOUT_S", 0.2)
    lock = manifest_module.manifest_path(client.root).parent / manifest_module.LOCK_FILENAME  # type: ignore[attr-defined]
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        started = time.monotonic()
        assert client.get("/api/bridge/v1/health").status_code == 200
        present = [
            p["content_iri"] for p in fixture_record_dict()["propositions"] if p.get("content_iri")
        ]
        status = client.post("/api/bridge/v1/status", json={"iris": present[:1]})
        assert status.status_code == 200 and status.json()["results"][0]["enrich_sources"]
        assert time.monotonic() - started < 5
        # A push needing a new manifest line answers 503 while the lock is held.
        other = make_record(proposition("held-1", "A span only this push carries."))
        response = _push(client, other.model_dump_json())
        assert response.status_code == 503
        assert str(client.root) not in response.text  # type: ignore[attr-defined]
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
