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
    FIXTURE_RECORD,
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
    response = _push(client, FIXTURE_RECORD.read_bytes())
    assert response.status_code == 404


def test_ingest_wrong_or_missing_token(client: TestClient, monkeypatch) -> None:
    _enable(monkeypatch)
    assert _push(client, FIXTURE_RECORD.read_bytes(), token="wrong").status_code == 401
    assert _push(client, FIXTURE_RECORD.read_bytes(), token=None).status_code == 401


def test_ingest_then_repush_is_idempotent(client: TestClient, monkeypatch) -> None:
    _enable(monkeypatch)
    expected = {
        p["content_iri"] for p in fixture_record_dict()["propositions"] if p.get("content_iri")
    }
    first = _push(client, FIXTURE_RECORD.read_bytes())
    assert first.status_code == 200, first.text
    assert set(first.json()["created_iris"]) == expected
    second = _push(client, FIXTURE_RECORD.read_bytes())
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
    response = _push(client, FIXTURE_RECORD.read_bytes())
    assert response.status_code == 413


def test_status_contract(client: TestClient, monkeypatch) -> None:
    _enable(monkeypatch)
    assert _push(client, FIXTURE_RECORD.read_bytes()).status_code == 200
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
    _push(client, FIXTURE_RECORD.read_bytes())
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
    report = _push(client, FIXTURE_RECORD.read_bytes()).json()
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
