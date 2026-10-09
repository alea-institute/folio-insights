"""Operator authentication for the API's state-changing routes (drain plan U5, R15, KTD10).

Every route that changes state (POST, PUT, PATCH, DELETE) requires an **operator bearer
token**; reads stay open, as deployed. Each router in ``api/routes`` declares
:data:`WRITE_GUARD` as a router-level dependency, so a route added to one of them is covered
without anyone remembering to add it (``tests/api/test_auth.py`` enumerates the app's route
table and fails on a mutating route without the guard).

Tokens file
    ``FOLIO_INSIGHTS_API_TOKENS_FILE`` names a file outside the repository holding one entry
    per line::

        sha256:<64 lowercase hex> <handle> <role>

    ``#`` comments and blank lines are allowed. Only the SHA-256 of a token is ever stored; the
    token itself is printed once by ``folio-insights api token-new``. The file is refused (the
    server does not start, and a request that would need it answers 503) when it is not a
    regular file, is owned by another user, is group- or world-accessible (any of mode
    ``0o077``), or has a line that is not exactly a digest, a handle and a known role. A refused
    line is reported by its number only, never its content, because the most likely mistake is
    a raw token pasted where its hash belongs.

Modes (``FOLIO_INSIGHTS_API_AUTH``)
    ``required`` (the default, with or without a tokens file: no file means every write is
    refused, i.e. fail closed)
        a write needs ``Authorization: Bearer <token>`` matching an entry.
    ``loopback-open`` (local development and the test suite)
        a write from a loopback client (127.0.0.1, ::1 or an IPv4-mapped loopback) that
        addresses a loopback ``Host`` and carries no proxy forwarding headers needs no token;
        any other client still needs one. A token that *is* presented must be valid, even on
        loopback. Never use this mode behind a reverse proxy on the same host.

Comparison and refusal
    The presented token is hashed and compared with :func:`hmac.compare_digest` against every
    entry, without stopping at the first match. Every authentication failure is the same 401
    with ``WWW-Authenticate: Bearer realm="folio-insights"`` and one fixed detail, so a caller
    learns nothing about which part failed. A misconfigured server (bad mode, refused tokens
    file) answers 503 and logs the reason. Neither tokens nor ``Authorization`` headers are ever
    logged: log lines name the method, path and outcome only.

The job control token (``X-Job-Control-Token``, ``api/routes/processing.py``) remains a second,
independent factor on job cancel, resume and key re-supply.

Known limit: FastAPI reads a request body (a multipart upload is spooled to a temporary file)
before it resolves dependencies, so an unauthenticated write is refused only after its body
arrives. Nothing is written to the corpus; a deployment that must bound unauthenticated upload
size should cap request bodies at its reverse proxy.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
import os
import re
import secrets
import stat
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fastapi import Depends, HTTPException, Request

logger = logging.getLogger(__name__)

AUTH_MODE_ENV = "FOLIO_INSIGHTS_API_AUTH"
TOKENS_FILE_ENV = "FOLIO_INSIGHTS_API_TOKENS_FILE"

MODE_REQUIRED = "required"
MODE_LOOPBACK_OPEN = "loopback-open"
MODES = frozenset({MODE_REQUIRED, MODE_LOOPBACK_OPEN})

#: Roles a tokens-file entry may name. Every role may perform operator writes today; the role is
#: recorded on ``request.state.operator`` for routes that later need to distinguish them.
ROLES = frozenset({"operator", "admin"})
DEFAULT_ROLE = "operator"

#: Methods that never change state; every other method needs an operator.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

#: Prefix of generated tokens, so secret scanners and humans recognise one on sight.
TOKEN_PREFIX = "fio_op_"
_TOKEN_BYTES = 32

#: Handle recorded for a tokenless loopback write in ``loopback-open`` mode.
LOOPBACK_HANDLE = "loopback"

LOOPBACK_HOST_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})
#: Headers a reverse proxy adds; their presence means the TCP peer is not the real client.
FORWARDING_HEADERS = ("forwarded", "x-forwarded-for", "x-forwarded-host", "x-real-ip")

_DIGEST_FIELD = re.compile(r"sha256:([0-9a-f]{64})")
_HANDLE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@-]{0,63}")
# RFC 6750 b64token, bounded so an oversized header is refused before it is hashed.
_BEARER_TOKEN = re.compile(r"[A-Za-z0-9\-._~+/]+=*")
_MAX_TOKEN_CHARS = 512
_MAX_TOKENS_FILE_BYTES = 1 << 20

_REALM = 'Bearer realm="folio-insights"'
_REFUSED_DETAIL = "Operator authentication required."
_MISCONFIGURED_DETAIL = (
    "Operator authentication is misconfigured on this server; the server log names the problem."
)


class AuthConfigError(RuntimeError):
    """The authentication configuration is unusable (unknown mode, refused tokens file).

    Messages name the setting, file path and line number, never a line's content.
    """


class TokensFileError(AuthConfigError):
    """The tokens file was refused (mode, ownership, type, size, encoding or a bad line)."""


@dataclass(frozen=True)
class Operator:
    """Who performed a write: stored on ``request.state.operator`` by :func:`require_operator`.

    ``via`` is ``"token"`` for a bearer-token match and ``"loopback"`` for a tokenless write a
    ``loopback-open`` server accepted from a local client.
    """

    handle: str
    role: str
    via: Literal["token", "loopback"]


@dataclass(frozen=True)
class TokenEntry:
    """One tokens-file entry: the raw SHA-256 of a token, its operator handle and role."""

    digest: bytes
    handle: str
    role: str


# ---------------------------------------------------------------------------
# Tokens: generation, hashing, entry lines
# ---------------------------------------------------------------------------


def generate_token() -> str:
    """A fresh operator token: :data:`TOKEN_PREFIX` plus 256 random bits, URL-safe base64."""
    return TOKEN_PREFIX + secrets.token_urlsafe(_TOKEN_BYTES)


def hash_token(token: str) -> str:
    """The tokens-file digest field for *token*: ``sha256:<64 lowercase hex>``."""
    return "sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest()


def validate_handle(handle: str) -> str:
    """Return *handle* if it is a valid operator handle, else raise :class:`ValueError`.

    A handle is 1-64 characters of letters, digits and ``. _ @ -``, starting with a letter or
    digit. A handle that looks like a generated token is refused, so a token pasted into the
    handle field is never stored in plaintext.
    """
    if not _HANDLE.fullmatch(handle):
        raise ValueError(
            "a handle is 1-64 letters, digits or . _ @ -, starting with a letter or digit"
        )
    if handle.startswith(TOKEN_PREFIX):
        raise ValueError("a handle must not look like an operator token")
    return handle


def validate_role(role: str) -> str:
    """Return *role* if it is one of :data:`ROLES`, else raise :class:`ValueError`."""
    if role not in ROLES:
        raise ValueError(f"a role is one of: {', '.join(sorted(ROLES))}")
    return role


def entry_line(token: str, handle: str, role: str = DEFAULT_ROLE) -> str:
    """The tokens-file line for *token* (its digest, never the token itself)."""
    return f"{hash_token(token)} {validate_handle(handle)} {validate_role(role)}"


def parse_tokens(text: str, source: str = "tokens file") -> tuple[TokenEntry, ...]:
    """Parse tokens-file text into entries, refusing anything that is not a well-formed line.

    Raises :class:`TokensFileError` naming *source* and the line number. The offending line is
    never quoted: it may be a raw token pasted where its hash belongs.
    """
    entries: list[TokenEntry] = []
    seen: set[bytes] = set()
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        where = f"{source}: line {number}"
        if len(fields) != 3:
            raise TokensFileError(
                f"{where}: expected 'sha256:<64 hex> <handle> <role>' (three fields); "
                "the line was not echoed"
            )
        match = _DIGEST_FIELD.fullmatch(fields[0])
        if match is None:
            raise TokensFileError(
                f"{where}: the first field is not a 'sha256:<64 lowercase hex>' digest. Store "
                "only token hashes: 'folio-insights api token-new' prints the line to append. "
                "The line was not echoed"
            )
        try:
            handle = validate_handle(fields[1])
            role = validate_role(fields[2])
        except ValueError as exc:
            raise TokensFileError(f"{where}: {exc}") from None
        digest = bytes.fromhex(match.group(1))
        if digest in seen:
            raise TokensFileError(f"{where}: the same token digest is listed twice")
        seen.add(digest)
        entries.append(TokenEntry(digest=digest, handle=handle, role=role))
    return tuple(entries)


def check_file_security(st: os.stat_result, path: Path | str) -> None:
    """Refuse a tokens file that is not a private regular file owned by this user (or root)."""
    if not stat.S_ISREG(st.st_mode):
        raise TokensFileError(f"{path}: not a regular file")
    if st.st_uid not in {os.geteuid(), 0}:
        raise TokensFileError(f"{path}: owned by another user (uid {st.st_uid})")
    loose = stat.S_IMODE(st.st_mode) & 0o077
    if loose:
        raise TokensFileError(
            f"{path}: mode {stat.S_IMODE(st.st_mode):04o} lets other users read or write it; "
            f"run: chmod 600 {path}"
        )


def load_tokens_file(path: Path | str) -> tuple[TokenEntry, ...]:
    """Read and validate the tokens file at *path*.

    The file is opened once and checked through its descriptor (``fstat``), so the mode that
    was checked is the mode of the bytes that were read.
    """
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOCTTY", 0))
    except OSError as exc:
        raise TokensFileError(f"{path}: cannot open ({exc.strerror})") from None
    try:
        check_file_security(os.fstat(fd), path)
    except BaseException:
        os.close(fd)
        raise
    with os.fdopen(fd, "rb") as handle:
        data = handle.read(_MAX_TOKENS_FILE_BYTES + 1)
    if len(data) > _MAX_TOKENS_FILE_BYTES:
        raise TokensFileError(f"{path}: larger than {_MAX_TOKENS_FILE_BYTES} bytes")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise TokensFileError(f"{path}: not UTF-8 text") from None
    return parse_tokens(text, str(path))


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def auth_mode() -> str:
    """The configured mode (``FOLIO_INSIGHTS_API_AUTH``); an unknown value is refused."""
    from folio_insights.config import get_settings

    mode = (get_settings().api_auth or MODE_REQUIRED).strip().lower()
    if mode not in MODES:
        raise AuthConfigError(
            f"{AUTH_MODE_ENV} must be one of {', '.join(sorted(MODES))}; refusing to guess"
        )
    return mode


def tokens_file_path() -> Path | None:
    """The configured tokens file (``FOLIO_INSIGHTS_API_TOKENS_FILE``), or None."""
    from folio_insights.config import get_settings

    path = get_settings().api_tokens_file
    return None if path is None else Path(path).expanduser()


class _TokenCache:
    """The parsed tokens file, reloaded when the file's identity, size, mode or mtime change.

    Operators can add or revoke a token by editing the file; no restart is needed.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._key: tuple | None = None
        self._entries: tuple[TokenEntry, ...] = ()

    def entries(self, path: Path | None) -> tuple[TokenEntry, ...]:
        if path is None:
            return ()
        try:
            st = os.stat(path)
        except OSError as exc:
            raise TokensFileError(f"{path}: cannot stat ({exc.strerror})") from None
        key = (str(path), st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_mode, st.st_uid)
        with self._lock:
            if key != self._key:
                self._entries = load_tokens_file(path)
                self._key = key
            return self._entries

    def clear(self) -> None:
        with self._lock:
            self._key = None
            self._entries = ()


_cache = _TokenCache()


def current_entries() -> tuple[TokenEntry, ...]:
    """The configured tokens file's entries (``()`` with no file); refusals raise."""
    return _cache.entries(tokens_file_path())


def reset_cache() -> None:
    """Forget the cached tokens file (tests, or after replacing the file in place)."""
    _cache.clear()


def check_configuration() -> tuple[str, int]:
    """Validate the mode and tokens file at startup; return ``(mode, entry count)``.

    Raises :class:`AuthConfigError` so a misconfigured server refuses to start rather than
    serve with authentication silently broken. Logs the posture (never a token).
    """
    mode = auth_mode()
    path = tokens_file_path()
    entries = current_entries()
    if mode == MODE_REQUIRED and not entries:
        logger.warning(
            "API auth: mode=required and no operator tokens are configured (%s); every "
            "state-changing request will be refused with 401",
            TOKENS_FILE_ENV if path is None else f"{path} has no entries",
        )
    elif mode == MODE_LOOPBACK_OPEN:
        logger.warning(
            "API auth: mode=loopback-open; local clients may write without a token. Use only "
            "for local development, never behind a reverse proxy"
        )
    logger.info("API auth: mode=%s, %d operator token(s) configured", mode, len(entries))
    return mode, len(entries)


# ---------------------------------------------------------------------------
# Request checks
# ---------------------------------------------------------------------------


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


def is_local_request(request: Request) -> bool:
    """True for a loopback client addressing a loopback host, with no proxy forwarding headers.

    The forwarding-header check matters: a reverse proxy on the same host connects from
    127.0.0.1 and (nginx's default) sends ``Host: 127.0.0.1:<port>``, which would otherwise
    make every proxied request look local.
    """
    client = request.client.host if request.client else None
    if not _is_loopback_address(client):
        return False
    hosts = request.headers.getlist("host")
    if len(hosts) != 1 or _host_name(hosts[0]) not in LOOPBACK_HOST_NAMES:
        return False
    return not any(name in request.headers for name in FORWARDING_HEADERS)


def _bearer_token(request: Request) -> str | None:
    """The token of a single well-formed ``Authorization: Bearer <token>`` header, else None."""
    values = request.headers.getlist("authorization")
    if len(values) != 1:
        return None
    scheme, _, token = values[0].strip().partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token or len(token) > _MAX_TOKEN_CHARS:
        return None
    if not _BEARER_TOKEN.fullmatch(token):
        return None
    return token


def _match(token: str, entries: tuple[TokenEntry, ...]) -> TokenEntry | None:
    """The entry whose digest equals the token's, comparing against every entry."""
    digest = hashlib.sha256(token.encode("utf-8")).digest()
    found: TokenEntry | None = None
    for entry in entries:
        if hmac.compare_digest(digest, entry.digest) and found is None:
            found = entry
    return found


def _refuse(request: Request) -> HTTPException:
    logger.info("API auth: refused %s %s", request.method, request.url.path)
    return HTTPException(
        status_code=401, detail=_REFUSED_DETAIL, headers={"WWW-Authenticate": _REALM}
    )


def _misconfigured(request: Request, exc: AuthConfigError) -> HTTPException:
    logger.error("API auth: cannot authenticate %s %s: %s", request.method, request.url.path, exc)
    return HTTPException(status_code=503, detail=_MISCONFIGURED_DETAIL)


def require_operator(request: Request) -> Operator:
    """FastAPI dependency: the authenticated operator, stored on ``request.state.operator``.

    401 (``WWW-Authenticate: Bearer``) when no valid operator token is presented, unless the
    server is ``loopback-open`` and the request is local (:func:`is_local_request`) and carries
    no ``Authorization`` header. 503 when the configuration is unusable.
    """
    try:
        mode = auth_mode()
        if not request.headers.getlist("authorization"):
            if mode == MODE_LOOPBACK_OPEN and is_local_request(request):
                operator = Operator(handle=LOOPBACK_HANDLE, role=DEFAULT_ROLE, via="loopback")
                request.state.operator = operator
                return operator
            raise _refuse(request)
        token = _bearer_token(request)
        entries = current_entries()
    except AuthConfigError as exc:
        raise _misconfigured(request, exc) from None
    entry = _match(token, entries) if token is not None else None
    if entry is None:
        raise _refuse(request)
    operator = Operator(handle=entry.handle, role=entry.role, via="token")
    request.state.operator = operator
    return operator


def require_operator_for_writes(request: Request) -> Operator | None:
    """Router-level dependency: :func:`require_operator` for every method but GET/HEAD/OPTIONS.

    Declared once per router (:data:`WRITE_GUARD`) so a new mutating route cannot be added to
    a router without it; reads pass through untouched.
    """
    if request.method.upper() in SAFE_METHODS:
        return None
    return require_operator(request)


#: The router-level dependency list every ``api/routes`` router declares.
WRITE_GUARD = [Depends(require_operator_for_writes)]

__all__ = [
    "AUTH_MODE_ENV",
    "DEFAULT_ROLE",
    "MODES",
    "MODE_LOOPBACK_OPEN",
    "MODE_REQUIRED",
    "ROLES",
    "SAFE_METHODS",
    "TOKENS_FILE_ENV",
    "TOKEN_PREFIX",
    "WRITE_GUARD",
    "AuthConfigError",
    "Operator",
    "TokenEntry",
    "TokensFileError",
    "auth_mode",
    "check_configuration",
    "check_file_security",
    "current_entries",
    "entry_line",
    "generate_token",
    "hash_token",
    "is_local_request",
    "load_tokens_file",
    "parse_tokens",
    "require_operator",
    "require_operator_for_writes",
    "reset_cache",
    "tokens_file_path",
    "validate_handle",
    "validate_role",
]
