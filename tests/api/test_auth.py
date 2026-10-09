"""API operator authentication (drain plan U5, R15, KTD10; ``api/auth.py``).

Every state-changing route needs an operator bearer token whose SHA-256 is in the tokens file;
reads stay open; ``loopback-open`` lets only a genuinely local, tokenless request write; the
job control token stays a second factor; tokens never reach a log. All tokens here are minted
per test; tokens files live in ``tmp_path``.
"""

from __future__ import annotations

import logging
import os
import re
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest
from click.testing import CliRunner
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from api import auth
from api import main as api_main
from api.main import app
from api.routes import discovery as discovery_mod
from api.routes import processing as processing_mod
from api.services.job_manager import get_runtime
from folio_insights.config import get_settings

# Captured at collection, before the conftest fixture swaps in its test-client stand-in.
REAL_IS_LOCAL_REQUEST = auth.is_local_request

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
GUARDS = (auth.require_operator, auth.require_operator_for_writes)
#: POST routes that are reads. Each needs a reason; a stale entry fails the enumeration test.
READ_ONLY_POSTS = {
    # Validates the candidate in the body against the SHACL suite and stores nothing.
    ("POST", "/validate"),
}

REMOTE = ("203.0.113.7", 40000)  # TEST-NET-3, never loopback
LOCAL = ("127.0.0.1", 40000)
UNAUTHORIZED_DETAIL = "Operator authentication required."


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def real_locality(monkeypatch: pytest.MonkeyPatch) -> None:
    """Undo the suite-wide stand-in: here locality is decided by the real check."""
    monkeypatch.setattr(auth, "is_local_request", REAL_IS_LOCAL_REQUEST)


@pytest.fixture(autouse=True)
def isolated_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("FOLIO_INSIGHTS_QUEUE_DB", str(tmp_path / ".queue" / "jobs.sqlite3"))
    monkeypatch.setenv("FOLIO_INSIGHTS_EMBEDDED_WORKER", "0")
    previous = api_main._output_dir
    api_main.configure(output_dir=tmp_path / "output")
    processing_mod.reset_job_manager()
    discovery_mod.reset_discovery_job_manager()
    yield tmp_path
    get_runtime().secret_store.clear()
    processing_mod.reset_job_manager()
    discovery_mod.reset_discovery_job_manager()
    api_main.configure(output_dir=previous)


def _configure(monkeypatch: pytest.MonkeyPatch, mode: str | None,
               tokens_file: Path | None = None) -> None:
    if mode is None:
        monkeypatch.delenv(auth.AUTH_MODE_ENV, raising=False)
    else:
        monkeypatch.setenv(auth.AUTH_MODE_ENV, mode)
    if tokens_file is None:
        monkeypatch.delenv(auth.TOKENS_FILE_ENV, raising=False)
    else:
        monkeypatch.setenv(auth.TOKENS_FILE_ENV, str(tokens_file))
    get_settings.cache_clear()
    auth.reset_cache()


def _write_tokens(path: Path, lines: list[str], mode: int = 0o600) -> Path:
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    os.chmod(path, mode)
    return path


@pytest.fixture()
def tokens() -> dict[str, str]:
    """Two freshly minted tokens (alice: operator, root-ops: admin)."""
    return {"alice": auth.generate_token(), "root-ops": auth.generate_token()}


@pytest.fixture()
def tokens_file(tmp_path: Path, tokens: dict[str, str]) -> Path:
    (tmp_path / "secrets").mkdir(mode=0o700)
    return _write_tokens(tmp_path / "secrets" / "api-tokens", [
        "# operator tokens (hashes only)",
        "",
        auth.entry_line(tokens["alice"], "alice", "operator"),
        auth.entry_line(tokens["root-ops"], "root-ops", "admin"),
    ])


@pytest.fixture()
def required(monkeypatch: pytest.MonkeyPatch, tokens_file: Path) -> Path:
    _configure(monkeypatch, auth.MODE_REQUIRED, tokens_file)
    return tokens_file


def _client(peer: tuple[str, int] = REMOTE, host: str = "api.example.org") -> TestClient:
    return TestClient(app, base_url=f"http://{host}", client=peer)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _assert_refused(resp) -> None:
    assert resp.status_code == 401, (resp.status_code, resp.text)
    assert resp.headers["www-authenticate"] == 'Bearer realm="folio-insights"'
    assert resp.json() == {"detail": UNAUTHORIZED_DETAIL}


def _api_routes(application: FastAPI) -> Iterator[tuple[str, set[str], object]]:
    """``(path, methods, dependant)`` of every API route as served, includes resolved.

    FastAPI 0.139 keeps included routers as lazy ``_IncludedRouter`` entries in ``app.routes``;
    its public ``iter_route_contexts`` yields each route with its effective path and dependant
    (router-level and include-level dependencies merged). Older FastAPI flattens on include.
    """
    try:
        from fastapi.routing import iter_route_contexts
    except ImportError:  # pragma: no cover - FastAPI before lazy includes
        contexts = application.routes
    else:
        contexts = iter_route_contexts(application.routes)
    for ctx in contexts:
        original = getattr(ctx, "original_route", ctx)
        if isinstance(original, APIRoute):
            yield ctx.path, set(ctx.methods or ()), ctx.dependant


def _dependency_calls(dependant) -> Iterator[object]:
    yield dependant.call
    for sub in dependant.dependencies:
        yield from _dependency_calls(sub)


def unguarded_mutating_routes(application: FastAPI) -> list[tuple[str, str]]:
    """Mutating (method, path) pairs of *application* without an operator guard."""
    missing = []
    for path, methods, dependant in _api_routes(application):
        calls = set(_dependency_calls(dependant))
        for method in sorted(methods & MUTATING_METHODS):
            if (method, path) in READ_ONLY_POSTS:
                continue
            if not any(guard in calls for guard in GUARDS):
                missing.append((method, path))
    return missing


def _mutating_routes() -> list[tuple[str, str]]:
    return sorted(
        (method, path)
        for path, methods, _ in _api_routes(app)
        for method in methods & MUTATING_METHODS
        if (method, path) not in READ_ONLY_POSTS
    )


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "synthetic", path)


def _probe_app() -> FastAPI:
    """A minimal app whose routes report what the guard put on ``request.state``."""
    probe = FastAPI()
    router = APIRouter(dependencies=auth.WRITE_GUARD)

    @router.post("/probe")
    def write_probe(request: Request) -> dict:
        op = request.state.operator
        return {"handle": op.handle, "role": op.role, "via": op.via}

    @router.get("/probe")
    def read_probe(request: Request) -> dict:
        return {"operator": hasattr(request.state, "operator")}

    @probe.post("/direct")
    def direct(operator: auth.Operator = Depends(auth.require_operator)) -> dict:
        return {"handle": operator.handle}

    probe.include_router(router)
    return probe


# ---------------------------------------------------------------------------
# Every mutating route is guarded (enumerated from the route table)
# ---------------------------------------------------------------------------


def test_every_mutating_route_has_the_operator_dependency() -> None:
    routes = _mutating_routes()
    assert len(routes) >= 23, routes  # the sweep really sees the API's write surface (23 today)
    assert unguarded_mutating_routes(app) == []


def test_read_only_post_allowlist_is_not_stale() -> None:
    present = {(m, path) for path, methods, _ in _api_routes(app) for m in methods}
    assert READ_ONLY_POSTS <= present


def test_a_new_route_without_the_dependency_is_detected() -> None:
    rogue = FastAPI()

    @rogue.post("/api/v1/rogue")
    def rogue_write() -> dict:  # pragma: no cover - never called
        return {}

    @rogue.delete("/api/v1/guarded", dependencies=[Depends(auth.require_operator)])
    def guarded_write() -> dict:  # pragma: no cover - never called
        return {}

    assert unguarded_mutating_routes(rogue) == [("POST", "/api/v1/rogue")]


@pytest.mark.parametrize("method,path", _mutating_routes())
def test_every_mutating_route_refuses_without_a_valid_token_off_loopback(
    required: Path, method: str, path: str,
) -> None:
    client = _client()
    url = _concrete(path)
    for headers in ({}, _bearer(auth.generate_token()), {"Authorization": "Basic YWxpY2U6cHc="}):
        _assert_refused(client.request(method, url, headers=headers))


# ---------------------------------------------------------------------------
# Token acceptance and refusal
# ---------------------------------------------------------------------------


def test_valid_token_passes_and_the_handle_reaches_request_state(
    required: Path, tokens: dict[str, str],
) -> None:
    client = TestClient(_probe_app(), base_url="http://api.example.org", client=REMOTE)
    resp = client.post("/probe", headers=_bearer(tokens["alice"]))
    assert resp.status_code == 200
    assert resp.json() == {"handle": "alice", "role": "operator", "via": "token"}
    admin = client.post("/probe", headers={"Authorization": f"bearer {tokens['root-ops']}"})
    assert admin.json() == {"handle": "root-ops", "role": "admin", "via": "token"}
    assert client.post("/direct", headers=_bearer(tokens["alice"])).json() == {"handle": "alice"}
    _assert_refused(client.post("/direct"))
    # Reads are untouched by the router guard: no operator is resolved for them.
    assert client.get("/probe").json() == {"operator": False}


def test_valid_token_performs_a_real_write_and_a_refused_one_writes_nothing(
    required: Path, tokens: dict[str, str], isolated_api: Path,
) -> None:
    client = _client()
    _assert_refused(client.post("/api/v1/corpora", json={"name": "Refused Corpus"}))
    assert not (isolated_api / "output" / "refused-corpus").exists()
    resp = client.post("/api/v1/corpora", json={"name": "Synthetic Corpus"},
                       headers=_bearer(tokens["alice"]))
    assert resp.status_code == 201, resp.text
    corpus = resp.json()["id"]
    _assert_refused(client.delete(f"/api/v1/corpora/{corpus}"))
    assert client.get(f"/api/v1/corpora/{corpus}").status_code == 200
    deleted = client.delete(f"/api/v1/corpora/{corpus}", headers=_bearer(tokens["alice"]))
    assert deleted.status_code == 204


@pytest.mark.parametrize("header", [
    "Bearer",
    "Bearer ",
    "Bearer two tokens",
    "Token abcdef0123456789",
    "Bearer not*a*b64token",
    "Bearer " + "A" * 600,
])
def test_malformed_authorization_is_refused(required: Path, header: str) -> None:
    _assert_refused(_client().post("/api/v1/corpora", json={"name": "x"},
                                   headers={"Authorization": header}))


def test_two_authorization_headers_are_refused(required: Path, tokens: dict[str, str]) -> None:
    resp = _client().post("/api/v1/corpora", json={"name": "x"}, headers=[
        ("Authorization", f"Bearer {tokens['alice']}"),
        ("Authorization", f"Bearer {tokens['root-ops']}"),
    ])
    _assert_refused(resp)


def test_every_failure_looks_the_same(required: Path, tokens: dict[str, str]) -> None:
    client = _client()
    bodies = {
        (r.status_code, r.headers["www-authenticate"], r.text)
        for r in (
            client.post("/api/v1/corpora", json={"name": "x"}),
            client.post("/api/v1/corpora", json={"name": "x"},
                        headers=_bearer(auth.generate_token())),
            client.post("/api/v1/corpora", json={"name": "x"}, headers={"Authorization": "Bearer"}),
            client.post("/api/v1/corpora", json={"name": "x"},
                        headers=_bearer(tokens["alice"][:-1])),
        )
    }
    assert len(bodies) == 1


def test_matching_compares_against_every_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    tokens = [auth.generate_token() for _ in range(5)]
    entries = auth.parse_tokens("\n".join(auth.entry_line(t, f"op{i}") for i, t in enumerate(tokens)))
    calls: list[int] = []
    real = auth.hmac.compare_digest

    def counting(a, b):
        calls.append(1)
        return real(a, b)

    monkeypatch.setattr(auth.hmac, "compare_digest", counting)
    assert auth._match(tokens[0], entries).handle == "op0"  # first entry matches...
    assert len(calls) == 5  # ...and every entry was still compared
    calls.clear()
    assert auth._match(auth.generate_token(), entries) is None
    assert len(calls) == 5


def test_tokens_file_edits_apply_without_restart(
    required: Path, tokens: dict[str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(_probe_app(), base_url="http://api.example.org", client=REMOTE)
    assert client.post("/probe", headers=_bearer(tokens["alice"])).status_code == 200
    newcomer = auth.generate_token()
    _write_tokens(required, [auth.entry_line(newcomer, "bob")])  # alice revoked, bob added
    assert client.post("/probe", headers=_bearer(newcomer)).json()["handle"] == "bob"
    _assert_refused(client.post("/probe", headers=_bearer(tokens["alice"])))


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------


def test_default_mode_is_required_and_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch, None, None)  # neither mode nor tokens file
    assert auth.auth_mode() == auth.MODE_REQUIRED
    assert auth.check_configuration() == (auth.MODE_REQUIRED, 0)
    _assert_refused(_client(LOCAL, "127.0.0.1").post("/api/v1/corpora", json={"name": "x"}))
    _assert_refused(_client().post("/api/v1/corpora", json={"name": "x"}))


def test_required_mode_refuses_loopback_without_a_token(
    required: Path, tokens: dict[str, str],
) -> None:
    local = _client(LOCAL, "localhost:8742")
    _assert_refused(local.post("/api/v1/corpora", json={"name": "x"}))
    ok = local.post("/api/v1/corpora", json={"name": "Local Corpus"},
                    headers=_bearer(tokens["alice"]))
    assert ok.status_code == 201


@pytest.mark.parametrize("peer,host", [
    (("127.0.0.1", 5000), "127.0.0.1:8742"),
    (("127.0.0.1", 5000), "localhost"),
    (("::1", 5000), "[::1]:8742"),
    (("::ffff:127.0.0.1", 5000), "localhost:8742"),
])
def test_loopback_open_lets_a_local_tokenless_request_write(
    monkeypatch: pytest.MonkeyPatch, peer: tuple[str, int], host: str,
) -> None:
    _configure(monkeypatch, auth.MODE_LOOPBACK_OPEN, None)
    # The Host header is set explicitly: TestClient cannot parse an IPv6 base URL.
    client = TestClient(_probe_app(), base_url="http://localhost", client=peer)
    resp = client.post("/probe", headers={"Host": host})
    assert resp.status_code == 200
    assert resp.json() == {"handle": auth.LOOPBACK_HANDLE, "role": "operator", "via": "loopback"}


@pytest.mark.parametrize("peer,host,headers", [
    (REMOTE, "api.example.org", {}),
    (REMOTE, "127.0.0.1", {}),  # a remote peer claiming a loopback Host
    (LOCAL, "api.example.org", {}),  # a loopback peer addressing a public name
    (LOCAL, "127.0.0.1", {"X-Forwarded-For": "198.51.100.9"}),  # a same-host reverse proxy
    (LOCAL, "127.0.0.1", {"Forwarded": "for=198.51.100.9"}),
    (LOCAL, "127.0.0.1", {"X-Real-IP": "198.51.100.9"}),
    (LOCAL, "127.0.0.1", {"X-Forwarded-Host": "api.example.org"}),
    (("testclient", 50000), "testserver", {}),  # not an address at all
])
def test_loopback_open_still_needs_a_token_off_loopback(
    monkeypatch: pytest.MonkeyPatch, peer, host, headers,
) -> None:
    _configure(monkeypatch, auth.MODE_LOOPBACK_OPEN, None)
    client = TestClient(_probe_app(), base_url=f"http://{host}", client=peer)
    _assert_refused(client.post("/probe", headers=headers))


def test_loopback_open_with_tokens_checks_any_presented_token(
    monkeypatch: pytest.MonkeyPatch, tokens_file: Path, tokens: dict[str, str],
) -> None:
    _configure(monkeypatch, auth.MODE_LOOPBACK_OPEN, tokens_file)
    local = TestClient(_probe_app(), base_url="http://127.0.0.1", client=LOCAL)
    remote = TestClient(_probe_app(), base_url="http://api.example.org", client=REMOTE)
    _assert_refused(local.post("/probe", headers=_bearer(auth.generate_token())))
    assert local.post("/probe", headers=_bearer(tokens["alice"])).json()["via"] == "token"
    assert remote.post("/probe", headers=_bearer(tokens["alice"])).json()["handle"] == "alice"
    _assert_refused(remote.post("/probe"))


def test_unknown_mode_is_a_misconfiguration(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch, "open", None)
    with pytest.raises(auth.AuthConfigError, match="FOLIO_INSIGHTS_API_AUTH"):
        auth.check_configuration()
    resp = _client(LOCAL, "127.0.0.1").post("/api/v1/corpora", json={"name": "x"})
    assert resp.status_code == 503
    assert "misconfigured" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Reads stay open; the job control token is still a second factor
# ---------------------------------------------------------------------------


def test_reads_stay_open_without_a_token(required: Path) -> None:
    client = _client()
    assert client.get("/health").status_code == 200
    assert client.get("/api/v1/corpora").status_code == 200
    assert client.get("/api/v1/tree", params={"corpus": "default"}).status_code == 200
    # POST /validate is a read (nothing is stored): open, answering on its merits.
    resp = client.post("/validate", content=b"[]", headers={"Content-Type": "application/json"})
    assert resp.status_code == 422


def test_job_control_token_is_still_required(required: Path, tokens: dict[str, str]) -> None:
    client = _client()
    op = _bearer(tokens["alice"])
    corpus = client.post("/api/v1/corpora", json={"name": "Job Corpus"}, headers=op).json()["id"]
    _assert_refused(client.post(f"/api/v1/corpus/{corpus}/process"))
    sub = client.post(f"/api/v1/corpus/{corpus}/process", headers=op)
    assert sub.status_code == 202, sub.text
    control = sub.json()["control_token"]
    assert control
    # An operator without the job's control token cannot cancel it...
    assert client.post(f"/api/v1/corpus/{corpus}/job/cancel", headers=op).status_code == 403
    # ...nor can the control token alone, without an operator...
    _assert_refused(client.post(f"/api/v1/corpus/{corpus}/job/cancel",
                                headers={"X-Job-Control-Token": control}))
    # ...but both factors together can.
    resp = client.post(f"/api/v1/corpus/{corpus}/job/cancel",
                       headers={**op, "X-Job-Control-Token": control})
    assert resp.status_code == 200 and resp.json()["status"] == "cancelled"


# ---------------------------------------------------------------------------
# The tokens file
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", [0o640, 0o604, 0o620, 0o602, 0o660, 0o644, 0o666])
def test_group_or_world_accessible_tokens_file_is_refused(
    monkeypatch: pytest.MonkeyPatch, tokens_file: Path, tokens: dict[str, str], mode: int,
) -> None:
    os.chmod(tokens_file, mode)
    _configure(monkeypatch, auth.MODE_REQUIRED, tokens_file)
    with pytest.raises(auth.TokensFileError, match="chmod 600"):
        auth.check_configuration()
    resp = _client().post("/api/v1/corpora", json={"name": "x"}, headers=_bearer(tokens["alice"]))
    assert resp.status_code == 503  # never accepted from a file others can read or write


def test_startup_refuses_an_insecure_tokens_file(
    monkeypatch: pytest.MonkeyPatch, tokens_file: Path,
) -> None:
    os.chmod(tokens_file, 0o644)
    _configure(monkeypatch, auth.MODE_REQUIRED, tokens_file)
    with pytest.raises(auth.TokensFileError):
        with TestClient(app):
            pass  # pragma: no cover - lifespan startup raises first


def test_startup_accepts_a_private_tokens_file(required: Path) -> None:
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200


def test_a_directory_or_missing_tokens_file_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _configure(monkeypatch, auth.MODE_REQUIRED, tmp_path)
    with pytest.raises(auth.TokensFileError, match="not a regular file"):
        auth.check_configuration()
    _configure(monkeypatch, auth.MODE_REQUIRED, tmp_path / "absent")
    with pytest.raises(auth.TokensFileError, match="cannot"):
        auth.check_configuration()


def test_a_raw_token_line_is_refused_and_never_echoed(tmp_path: Path) -> None:
    raw = auth.generate_token()
    for lines in (
        [raw],  # the token pasted on its own
        [f"{raw} alice operator"],  # the token where its digest belongs
        [f"sha256:{raw} alice operator"],
        [f"{auth.hash_token(raw)} {raw} operator"],  # the token in the handle field
    ):
        path = _write_tokens(tmp_path / "tokens", lines)
        with pytest.raises(auth.TokensFileError) as caught:
            auth.load_tokens_file(path)
        assert "line 1" in str(caught.value)
        assert raw not in str(caught.value)
        assert raw[len(auth.TOKEN_PREFIX):] not in str(caught.value)


@pytest.mark.parametrize("line,reason", [
    ("sha256:" + "a" * 63 + " alice operator", "digest"),
    ("sha256:" + "A" * 64 + " alice operator", "digest"),
    ("sha256:" + "g" * 64 + " alice operator", "digest"),
    ("sha512:" + "a" * 64 + " alice operator", "digest"),
    ("sha256:" + "a" * 64 + " alice", "three fields"),
    ("sha256:" + "a" * 64 + " alice operator extra", "three fields"),
    ("sha256:" + "a" * 64 + " alice superuser", "role"),
    ("sha256:" + "a" * 64 + " -alice operator", "handle"),
])
def test_malformed_lines_are_refused(tmp_path: Path, line: str, reason: str) -> None:
    path = _write_tokens(tmp_path / "tokens", ["# header", line])
    with pytest.raises(auth.TokensFileError, match=reason) as caught:
        auth.load_tokens_file(path)
    assert "line 2" in str(caught.value)


def test_duplicate_digest_is_refused(tmp_path: Path) -> None:
    token = auth.generate_token()
    path = _write_tokens(tmp_path / "tokens", [auth.entry_line(token, "alice"),
                                               auth.entry_line(token, "bob")])
    with pytest.raises(auth.TokensFileError, match="twice"):
        auth.load_tokens_file(path)


def test_well_formed_file_parses(tmp_path: Path) -> None:
    token = auth.generate_token()
    path = _write_tokens(tmp_path / "tokens", [
        "# comment", "", "   ", f"  {auth.entry_line(token, 'carol@example.org', 'admin')}  ",
    ])
    (entry,) = auth.load_tokens_file(path)
    assert (entry.handle, entry.role) == ("carol@example.org", "admin")
    assert entry.digest.hex() == auth.hash_token(token).removeprefix("sha256:")


# ---------------------------------------------------------------------------
# Tokens never reach the log
# ---------------------------------------------------------------------------


def test_tokens_never_appear_in_logs(
    required: Path, tokens: dict[str, str], caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    wrong = auth.generate_token()
    client = _client()
    client.post("/api/v1/corpora", json={"name": "Logged Corpus"}, headers=_bearer(tokens["alice"]))
    client.post("/api/v1/corpora", json={"name": "x"}, headers=_bearer(wrong))
    client.post("/api/v1/corpora", json={"name": "x"})
    os.chmod(required, 0o644)  # a refused file is logged too, by path only
    auth.reset_cache()
    client.post("/api/v1/corpora", json={"name": "x"}, headers=_bearer(tokens["alice"]))
    text = caplog.text
    assert "API auth: refused POST /api/v1/corpora" in text
    assert "mode 0644" in text
    for secret in (tokens["alice"], tokens["root-ops"], wrong):
        assert secret not in text
        assert secret[len(auth.TOKEN_PREFIX):] not in text
    assert "Bearer" not in text and "authorization" not in text.lower()


# ---------------------------------------------------------------------------
# CLI: folio-insights api token-new
# ---------------------------------------------------------------------------


def _cli():
    from folio_insights.cli import cli

    return cli


def test_token_new_prints_the_token_once_and_the_line(tmp_path: Path) -> None:
    result = CliRunner().invoke(_cli(), ["api", "token-new", "alice"])
    assert result.exit_code == 0, result.output
    token, line = result.stdout.splitlines()
    assert token.startswith(auth.TOKEN_PREFIX) and len(token) >= 40
    assert line == auth.entry_line(token, "alice", "operator")
    assert token not in line
    assert result.stdout.count(token) == 1


def test_token_new_appends_with_mode_600_and_the_server_accepts_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "tokens"
    first = CliRunner().invoke(_cli(), ["api", "token-new", "alice", "--append", str(path)])
    second = CliRunner().invoke(_cli(), ["api", "token-new", "ops", "--role", "admin",
                                         "--append", str(path)])
    assert first.exit_code == 0 and second.exit_code == 0, first.output + second.output
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    alice, ops = first.stdout.strip(), second.stdout.strip()
    content = path.read_text()
    assert alice not in content and ops not in content
    assert [(e.handle, e.role) for e in auth.load_tokens_file(path)] == [
        ("alice", "operator"), ("ops", "admin")]
    _configure(monkeypatch, auth.MODE_REQUIRED, path)
    client = TestClient(_probe_app(), base_url="http://api.example.org", client=REMOTE)
    assert client.post("/probe", headers=_bearer(ops)).json() == {
        "handle": "ops", "role": "admin", "via": "token"}


def test_token_new_refuses_an_insecure_or_invalid_existing_file(tmp_path: Path) -> None:
    path = _write_tokens(tmp_path / "tokens", [auth.entry_line(auth.generate_token(), "a")], 0o644)
    result = CliRunner().invoke(_cli(), ["api", "token-new", "bob", "--append", str(path)])
    assert result.exit_code != 0 and "chmod 600" in result.output
    assert len(path.read_text().splitlines()) == 1
    bad = _write_tokens(tmp_path / "bad", ["not-a-digest alice operator"])
    result = CliRunner().invoke(_cli(), ["api", "token-new", "bob", "--append", str(bad)])
    assert result.exit_code != 0 and "line 1" in result.output
    assert bad.read_text() == "not-a-digest alice operator\n"


def test_token_new_never_appends_through_a_symlink(tmp_path: Path) -> None:
    target = _write_tokens(tmp_path / "real-tokens", [])
    link = tmp_path / "tokens-link"
    link.symlink_to(target)
    result = CliRunner().invoke(_cli(), ["api", "token-new", "bob", "--append", str(link)])
    assert result.exit_code != 0 and "cannot" in result.output
    assert target.read_text() == ""
    assert auth.TOKEN_PREFIX not in result.stdout  # no token is shown for a failed append


@pytest.mark.parametrize("args", [["bad handle!"], ["fio_op_lookalike"], ["alice", "--role", "root"]])
def test_token_new_validates_handle_and_role(args: list[str]) -> None:
    result = CliRunner().invoke(_cli(), ["api", "token-new", *args])
    assert result.exit_code == 2
    assert auth.TOKEN_PREFIX not in result.stdout
