"""A built viewer must preserve the API's method and namespace boundaries."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.main import SPAStaticFiles, ViewerMount
from api.routes.shard import router


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    (tmp_path / "index.html").write_text("synthetic viewer", encoding="utf-8")
    application = FastAPI()
    application.include_router(router)

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    application.router.routes.append(
        ViewerMount("/", SPAStaticFiles(directory=tmp_path, html=True), name="viewer")
    )
    return TestClient(application)


@pytest.mark.parametrize("path", [
    "/api/shard/synthetic/core", "/health",
    "/api/v1/corpus/synthetic/shards/urn:folio:shard/" + "a" * 32 + "/graph",
    "/api/v1/corpus/synthetic/shards/urn:folio:shard/" + "a" * 32 + "/derivation",
])
def test_head_on_get_only_api_routes_is_405_with_a_viewer_build(
    client: TestClient, path: str,
) -> None:
    assert client.head(path).status_code == 405


@pytest.mark.parametrize("path", ["/api", "/api/missing"])
def test_unknown_api_routes_remain_404(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_viewer_deep_links_still_work(client: TestClient, method: str) -> None:
    response = client.request(method, "/shards/synthetic/graph")
    assert response.status_code == 200
    if method == "GET":
        assert response.text == "synthetic viewer"
