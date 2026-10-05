"""Phase 11 SHACL-05: ``POST /validate`` returns a pyshacl report.

Valid and invalid synthetic candidates both get 200 and a report. Bodies that
are not a JSON object get 422, and oversize bodies get 413. The endpoint is
documented in OpenAPI.
"""
from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from api.main import app
from tests.shapes.cases import dumped, mutate
from tests.shards.conftest import _SUBTYPE_TABLE


@pytest.fixture()
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.parametrize("tag,cls", _SUBTYPE_TABLE)
async def test_valid_candidate_conforms(client: AsyncClient, tag: str, cls: type) -> None:
    resp = await client.post("/validate", json=dumped(cls))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["conforms"] is True and body["model_valid"] is True
    assert body["violations"] == 0 and body["engine"] == "pyshacl" and body["tier"] == "local"
    assert len(body["suite_digest"]) == 64
    assert body["results_total"] == 0 and body["results_truncated"] is False
    assert "report_text" not in body


@pytest.mark.parametrize(
    "change,component,path",
    [
        ({"layer": "L9"}, "InConstraintComponent", "layer"),
        ({"smuggled": 1}, "ClosedConstraintComponent", "undeclared#smuggled"),
        ({"extracted_at": "not-a-time"}, "DatatypeConstraintComponent", "extractedAt"),
        ({"confidence": 7}, "MaxInclusiveConstraintComponent", "confidence"),
    ],
)
async def test_invalid_candidate_reports_violations(
    client: AsyncClient, change: dict, component: str, path: str
) -> None:
    resp = await client.post("/validate", json=mutate(dumped(), **change))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["conforms"] is False and body["model_valid"] is False
    assert body["model_errors"] and all(":" in e for e in body["model_errors"])
    hits = [r for r in body["results"] if r["component"] == component]
    assert hits and hits[0]["path"].endswith(("/" if "#" not in path else "/shapes/") + path)
    assert hits[0]["severity"] == "Violation"


async def test_missing_field_and_model_valid_rule_breach(client: AsyncClient) -> None:
    missing = {k: v for k, v in dumped().items() if k != "sense"}
    body = (await client.post("/validate", json=missing)).json()
    assert not body["conforms"]
    assert any(r["component"] == "MinCountConstraintComponent" for r in body["results"])

    # The model accepts an inverted interval; SHACL refuses it.
    inverted = mutate(dumped(), valid_time_start="2027-01-01T00:00:00Z", valid_time_end="2026-01-01T00:00:00Z")
    body = (await client.post("/validate", json=inverted)).json()
    assert body["model_valid"] is True and body["conforms"] is False
    assert any("earlier than fi:validTimeEnd" in r["message"] for r in body["results"])


async def test_warnings_do_not_fail_conformance(client: AsyncClient) -> None:
    unsigned = mutate(dumped(), signatures=[])
    body = (await client.post("/validate", json=unsigned)).json()
    assert body["conforms"] is True and body["warnings"] >= 1 and body["violations"] == 0
    assert all(r["severity"] == "Warning" for r in body["results"])


async def test_legacy_record_is_migrated_then_validated(client: AsyncClient) -> None:
    legacy = {k: v for k, v in dumped().items() if k not in ("schema_version", "supersedes")}
    body = (await client.post("/validate", json=legacy)).json()
    assert body["model_valid"] is True and body["source_schema_version"] == 1
    assert body["conforms"] is True


@pytest.mark.parametrize(
    "raw,status",
    [(b"[1, 2]", 422), (b"not json", 422), (b'"a string"', 422), (b"x" * ((1 << 20) + 1), 413)],
)
async def test_bad_bodies(client: AsyncClient, raw: bytes, status: int) -> None:
    resp = await client.post("/validate", content=raw, headers={"content-type": "application/json"})
    assert resp.status_code == status


async def test_documented_in_openapi(client: AsyncClient) -> None:
    spec = (await client.get("/openapi.json")).json()
    op = spec["paths"]["/validate"]["post"]
    assert op["summary"].startswith("Validate a candidate shard")
    assert "application/json" in op["requestBody"]["content"]
    schema_ref = op["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    report = spec["components"]["schemas"][schema_ref.rsplit("/", 1)[-1]]
    assert {"conforms", "results", "results_total", "suite_digest"} <= set(report["properties"])
    assert "report_text" not in report["properties"]
    assert {"413", "422", "503"} <= set(op["responses"])
    json.dumps(spec)  # serializable


# ── Phase 11 review findings (each failed before its fix) ─────────────────

import time  # noqa: E402

from api.routes import validate as validate_route  # noqa: E402


async def test_p1_2_list_amplification_is_refused_before_pyshacl(client: AsyncClient) -> None:
    body = {"shard_type": "simple_assertion", "signatures": [{"x": 1}] * 5000}
    started = time.perf_counter()
    resp = await client.post("/validate", json=body)
    assert resp.status_code == 413 and time.perf_counter() - started < 2
    assert len(resp.content) < 1000


async def test_p1_2_undeclared_key_amplification_is_refused(client: AsyncClient) -> None:
    resp = await client.post("/validate", json={f"{i:x}": 0 for i in range(40_000)})
    assert resp.status_code == 413 and len(resp.content) < 1000


async def test_p1_2_results_are_capped_with_a_total(client: AsyncClient) -> None:
    body = mutate(dumped(), **{f"k{i}": "v" for i in range(1500)})
    started = time.perf_counter()
    resp = await client.post("/validate", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["results"]) == validate_route.MAX_RESULTS
    assert data["results_total"] >= 1500 and data["results_truncated"] is True
    assert data["violations"] >= 1500
    assert len(data["model_errors"]) == validate_route.MAX_MODEL_ERRORS
    assert data["model_errors_total"] >= 1500
    assert len(resp.content) < 200_000 and time.perf_counter() - started < 15


async def test_p2_3_values_are_never_echoed(client: AsyncClient) -> None:
    resp = await client.post("/validate", json=mutate(dumped(), confidence="SSN 123-45-6789"))
    assert resp.status_code == 200
    assert "123-45-6789" not in resp.text
    assert all("value" not in r for r in resp.json()["results"])


@pytest.mark.parametrize(
    "raw",
    [
        json.dumps({"shard_type": []}).encode(),
        json.dumps({"shard_type": {}}).encode(),
        json.dumps(mutate(dumped(), schema_version=[1])).encode(),
    ],
    ids=["shard_type_list", "shard_type_dict", "schema_version_list"],
)
async def test_p2_3_hostile_types_do_not_500(client: AsyncClient, raw: bytes) -> None:
    resp = await client.post("/validate", content=raw, headers={"content-type": "application/json"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["model_valid"] is False


@pytest.mark.parametrize(
    "raw",
    [
        b'{"a":' + b"[" * 200_000 + b"]" * 200_000 + b"}",
        ('{"x": ' + '{"a":' * 3000 + "1" + "}" * 3000 + "}").encode(),
        ('{"triple": ' + '{"a":' * 40 + "1" + "}" * 40 + "}").encode(),
    ],
    ids=["deep_json", "deep_object", "just_over_depth"],
)
async def test_p2_3_deep_nesting_is_422(client: AsyncClient, raw: bytes) -> None:
    resp = await client.post("/validate", content=raw, headers={"content-type": "application/json"})
    assert resp.status_code in (413, 422), resp.text
    if len(raw) <= validate_route.MAX_BODY_BYTES:
        assert resp.status_code == 422


async def test_p2_3_content_length_is_checked_before_reading(client: AsyncClient) -> None:
    consumed: list[int] = []

    async def body():  # noqa: ANN202
        for _ in range(64):
            consumed.append(1)
            yield b" " * 65536

    resp = await client.post(
        "/validate",
        content=body(),
        headers={"content-type": "application/json", "content-length": str(64 * 65536)},
    )
    assert resp.status_code == 413
    assert len(consumed) <= 2  # refused on the header, not after buffering 4 MiB


async def test_p2_3_streamed_body_without_length_is_capped(client: AsyncClient) -> None:
    async def body():  # noqa: ANN202
        for _ in range(40):
            yield b" " * 65536

    resp = await client.post("/validate", content=body(), headers={"content-type": "application/json"})
    assert resp.status_code == 413
