"""Bounded acquisition and offline verification of real-corpus pilot cells.

Run collection/sealing in the orchestrator's restricted evaluator workspace.
Only the tuning export may be distributed to candidate workers. Directory names
are not a custody boundary (KTD6); deployment supplies that boundary. Text lives
once in digest-addressed files; all retained selections use code-point offsets.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import tempfile
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
from lxml import etree, html
from pydantic import Field, StringConstraints, model_validator

from folio_insights.measurement.gold import repo_root
from folio_insights.measurement.schema import (
    GoldDocument, GoldProposition, MeasurementModel, Nonempty, Sha256,
    SourceSnapshot, SupportingSpan,
)

PublicGenre = Literal["opinions", "statutes-regulations", "briefs"]
Jurisdiction = Literal["federal", "MN", "TX", "CA", "NY", "FL", "IL"]
EnvironmentName = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]*$")]
DEFAULT_ROOT = Path("output/measurement/sealed")
DEFAULT_THROTTLE_STATE = Path("output/measurement/corpus/throttle-state.json")
SCORE_LABEL = "judge agreement, unanchored"


class CorpusError(ValueError):
    """Acquisition or verification cannot supply the required evidence."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: MeasurementModel | dict) -> bytes:
    if isinstance(value, MeasurementModel):
        value = value.model_dump(mode="json")
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode()


def _public_url(value: str) -> str:
    url = urlsplit(value)
    if (url.scheme != "https" or not url.hostname or url.username or url.password
            or url.fragment or any(part in {".", ".."} for part in unquote(url.path).split("/"))
            or any(re.sub(r"[^a-z]", "", k.casefold()) in {
                "key", "token", "apikey", "accesstoken", "auth", "authorization"}
                   for k in parse_qs(url.query))):
        raise ValueError("use an HTTPS URL without credentials or fragments")
    return value


class RateLimits(MeasurementModel):
    minimum_interval_seconds: float = Field(default=1, gt=0)
    per_minute: int | None = Field(default=None, gt=0)
    per_hour: int | None = Field(default=None, gt=0)
    per_day: int | None = Field(default=None, gt=0)


class SourcePolicy(MeasurementModel):
    source_id: Nonempty
    publisher: Nonempty
    url_prefixes: tuple[Nonempty, ...] = Field(min_length=1)
    access_method: Literal["direct-download", "token-api", "bulk-download", "manual-permission"]
    auth_env: EnvironmentName | None
    auth_style: Literal["none", "bearer", "token", "query-key"] = "none"
    rate_limits: RateLimits
    robots_url: Nonempty
    terms_url: Nonempty
    rights_basis: Nonempty
    substitute_forum_label: Nonempty | None
    access_status: Literal["permitted", "pending-review", "blocked"] = "permitted"

    @model_validator(mode="after")
    def check_access(self) -> SourcePolicy:
        for url in (*self.url_prefixes, self.robots_url, self.terms_url):
            _public_url(url)
        if (self.auth_env is None) != (self.auth_style == "none"):
            raise ValueError("authentication records an env var name and matching style only")
        return self


class AcquisitionPolicy(MeasurementModel):
    format: Literal[1]
    documents_per_cell: Literal[8] = 8
    tuning_groups: Literal[6] = 6
    held_out_groups: Literal[2] = 2
    minimum_words: Literal[150] = 150
    maximum_words: Literal[400] = 400
    max_download_bytes: int = Field(default=10_000_000, gt=0)
    sources: tuple[SourcePolicy, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_sources(self) -> AcquisitionPolicy:
        ids = [s.source_id for s in self.sources]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate policy source ID")
        return self


class Rights(MeasurementModel):
    basis: Literal["government-edicts", "federal-work", "license", "permission"]
    supporting_url: Nonempty
    checked_date: date
    retained_evaluation_allowed: bool
    original_retention_allowed: bool
    exclusions: tuple[Nonempty, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def check_proof_url(self) -> Rights:
        _public_url(self.supporting_url)
        return self


class DocumentRequest(MeasurementModel):
    document_id: Nonempty
    source_id: Nonempty
    group_id: Nonempty
    related_group_ids: tuple[Nonempty, ...] = ()
    url: Nonempty
    title: Nonempty
    jurisdiction: Jurisdiction
    genre: PublicGenre
    subgenre: Nonempty
    forum: Nonempty
    case_section: Nonempty
    document_date: date
    official_text: bool = True
    federal_employee_work: bool = False
    extraction_method: Literal["utf8-v1", "html-xpath-v1", "xml-xpath-v1", "json-field-v1"]
    selector: Nonempty | None = None
    span: SupportingSpan
    rights: Rights

    @model_validator(mode="after")
    def check_url_and_selector(self) -> DocumentRequest:
        _public_url(self.url)
        if self.extraction_method != "utf8-v1" and not self.selector:
            raise ValueError("structured text extraction needs an explicit selector")
        return self


class AcquiredDocument(MeasurementModel):
    request: DocumentRequest
    source_policy: SourcePolicy
    retrieved_at: datetime
    raw_sha256: Sha256
    normalized_sha256: Sha256
    span_sha256: Sha256
    snapshot_id: Sha256
    partition: Literal["tuning", "held-out"]
    propositions: tuple[GoldProposition, ...] = ()
    gold_status: Literal["draft"] = "draft"
    judge_rationale: str | None = None


class AcquisitionGap(MeasurementModel):
    document_id: Nonempty
    jurisdiction: Jurisdiction
    genre: PublicGenre
    url: Nonempty
    reason: Nonempty


class CorpusManifest(MeasurementModel):
    format: Literal[1] = 1
    policy: AcquisitionPolicy
    seed: int = Field(ge=0)
    score_label: Literal["judge agreement, unanchored"] = SCORE_LABEL
    documents: tuple[AcquiredDocument, ...]
    gaps: tuple[AcquisitionGap, ...] = ()


class Verification(MeasurementModel):
    complete: bool
    documents: int
    errors: tuple[str, ...]


def load_policy(path: Path | None = None) -> AcquisitionPolicy:
    return AcquisitionPolicy.model_validate_json(
        (path or repo_root() / "data/measurement/corpus-policy.json").read_bytes())


def load_manifest(path: Path) -> CorpusManifest:
    return CorpusManifest.model_validate_json(path.read_bytes())


def _rights_check(request: DocumentRequest) -> None:
    rights = request.rights
    if not rights.retained_evaluation_allowed:
        raise CorpusError("rights proof does not permit retained evaluation material")
    if not rights.original_retention_allowed:
        raise CorpusError("rights proof does not permit retention of the downloaded original")
    if rights.checked_date > datetime.now(timezone.utc).date():
        raise CorpusError("rights checked date is in the future")
    if rights.basis == "government-edicts" and (
            request.genre == "briefs" or not request.official_text):
        raise CorpusError("rights: a public brief or editorial addition is not a government edict")
    if rights.basis == "federal-work" and not request.federal_employee_work:
        raise CorpusError("rights: federal employee authorship must be documented")


def _source_check(request: DocumentRequest, source: SourcePolicy) -> None:
    if request.source_id != source.source_id:
        raise CorpusError("source policy does not match document")
    if source.access_status != "permitted":
        raise CorpusError("source access requires review or permission")
    target = urlsplit(request.url)
    if not any(target.netloc == urlsplit(prefix).netloc and request.url.startswith(prefix)
               for prefix in source.url_prefixes):
        raise CorpusError("URL is outside the source access policy")
    _rights_check(request)


def normalize(raw: bytes, request: DocumentRequest) -> str:
    """Versioned, deterministic extraction; editorial material is excluded by selector."""
    method = request.extraction_method
    if method == "utf8-v1":
        return raw.decode("utf-8")
    if method == "json-field-v1":
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise CorpusError("JSON response is not an object")
        # Deliberately select one API field, never silently select an alternative.
        value = value[request.selector]
        if not isinstance(value, str):
            raise CorpusError("selected JSON field is not text")
        return value
    if method == "html-xpath-v1":
        tree = html.fromstring(raw.decode("utf-8"))
        for node in tree.xpath("//script|//style"):
            node.drop_tree()
    else:
        tree = etree.fromstring(raw, parser=etree.XMLParser(resolve_entities=False, no_network=True))
    selected = tree.xpath(request.selector)
    if not isinstance(selected, list) or not selected:
        raise CorpusError("text selector matched no nodes")
    parts = [" ".join(node.itertext()) if isinstance(node, etree._Element) else str(node)
             for node in selected]
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def _snapshot_id(raw_digest: str, normalized_digest: str, request: DocumentRequest) -> str:
    return sha256(_json_bytes({"raw_sha256": raw_digest, "normalized_sha256": normalized_digest,
                               "method": request.extraction_method, "selector": request.selector}))


class HttpFetcher:
    """Injected HTTP transport, bounded streaming and per-host request pacing.

    No redirect, challenge bypass, account registration or auth fallback. Tokens
    are read at request time and never become part of a persisted URL or receipt.
    The caller must verify current robots/terms before marking a source permitted.
    """

    def __init__(self, client: httpx.Client, *, user_agent: str, state_path: Path,
                 clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        if not user_agent.strip():
            raise CorpusError("a contact User-Agent is required")
        self.client = client
        self.user_agent = user_agent
        self.clock, self.sleep = clock, sleep
        self.state_path = state_path
        # Validate at startup, then reload inside each request's transaction.
        with self._locked_state():
            pass

    @contextmanager
    def _locked_file(self, path: Path):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Lock a stable inode: replacing the JSON must not replace the lock.
            with path.open("a+b") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)
        except OSError:
            raise CorpusError(f"cannot read or write throttle state: {self.state_path}") from None

    @contextmanager
    def _locked_state(self):
        with self._locked_file(self.state_path.with_suffix(self.state_path.suffix + ".lock")):
            yield self._load_state()

    def _load_state(self) -> dict:
        try:
            raw = self.state_path.read_bytes()
        except FileNotFoundError:
            if self.state_path.is_symlink():
                raise CorpusError(f"unreadable throttle state: {self.state_path}") from None
            return {}
        try:
            state = json.loads(raw)
            if not isinstance(state, dict):
                raise ValueError
            for host, entry in state.items():
                if (not re.fullmatch(r"[a-z0-9.:-]+", host) or not isinstance(entry, dict)
                        or set(entry) != {"requests", "retry_at"}):
                    raise ValueError
                history, retry = entry["requests"], entry["retry_at"]
                if not isinstance(history, list):
                    raise ValueError
                timestamps = history + ([] if retry is None else [retry])
                if any(type(t) not in (int, float) or not math.isfinite(t) for t in timestamps):
                    raise ValueError
                if history != sorted(history):
                    raise ValueError
            return state
        except (ValueError, TypeError, OverflowError):
            raise CorpusError(f"corrupt throttle state: {self.state_path}") from None

    def _save_state(self, state: dict) -> None:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.state_path.parent,
                                             prefix=self.state_path.name + ".", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(_json_bytes(state))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.state_path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _reserve(self, entry: dict, limits: RateLimits) -> float:
        now = self.clock()
        history = entry["requests"]
        ready = max(now, entry["retry_at"] or now)
        if history:
            ready = max(ready, history[-1] + limits.minimum_interval_seconds)
        windows = ((60, limits.per_minute), (3600, limits.per_hour), (86400, limits.per_day))
        for window, count in windows:
            if count and len(history) >= count:
                ready = max(ready, history[-count] + window)
        # A later request may use a different policy, including a daily quota.
        entry["requests"] = [stamp for stamp in history if stamp > now - 86400] + [ready]
        if entry["retry_at"] is not None and entry["retry_at"] <= ready:
            entry["retry_at"] = None
        return ready

    def fetch(self, request: DocumentRequest, source: SourcePolicy, max_bytes: int) -> bytes:
        _source_check(request, source)
        headers = {"User-Agent": self.user_agent}
        url = httpx.URL(request.url)
        if source.auth_env:
            token = os.environ.get(source.auth_env)
            if not token:
                raise CorpusError("required source authentication is unavailable")
            if source.auth_style == "query-key":
                auth_query = str(httpx.QueryParams({"key": token})).encode("ascii")
                url = url.copy_with(query=url.query + (b"&" if url.query else b"") + auth_query)
            else:
                prefix = "Token" if source.auth_style == "token" else "Bearer"
                headers["Authorization"] = f"{prefix} {token}"
        host = url.raw_host.decode("ascii")
        host_lock = self.state_path.with_suffix(self.state_path.suffix + f".{sha256(host.encode())}.lock")
        # Keep a host serialized through its response (including Retry-After),
        # while unrelated hosts only share the brief JSON transactions below.
        with self._locked_file(host_lock):
            with self._locked_state() as state:
                entry = state.setdefault(host, {"requests": [], "retry_at": None})
                ready = self._reserve(entry, source.rate_limits)
                # Persist even a future slot: a crash can only overcount quota.
                self._save_state(state)
            delay = ready - self.clock()
            if delay > 0:
                self.sleep(delay)
            with self._locked_state() as state:
                entry = state[host]
                # A late wake must pace subsequent requests from the actual start.
                now = max(ready, self.clock())
                entry["requests"] = [stamp for stamp in entry["requests"][:-1]
                                     if stamp > now - 86400] + [now]
                self._save_state(state)
            try:
                return self._download(url, headers, max_bytes, entry)
            finally:
                with self._locked_state() as state:
                    state[host] = entry
                    self._save_state(state)

    def _download(self, url: httpx.URL, headers: dict, max_bytes: int, entry: dict) -> bytes:
        try:
            with self.client.stream("GET", url, headers=headers,
                                    follow_redirects=False, timeout=30) as response:
                if response.status_code == 429:
                    retry = response.headers.get("Retry-After", "60")
                    try:
                        delay = float(retry)
                    except ValueError:
                        try:
                            delay = parsedate_to_datetime(retry).timestamp() - self.clock()
                        except (TypeError, ValueError):
                            delay = 60
                    if not math.isfinite(delay):
                        delay = 60
                    entry["retry_at"] = self.clock() + max(0, delay)
                if response.status_code != 200:
                    raise CorpusError(f"source HTTP {response.status_code}; no access bypass attempted")
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise CorpusError("source exceeds download byte limit")
        except httpx.HTTPError:
            # httpx errors may embed an authenticated query URL: do not persist them.
            raise CorpusError("source transport failed") from None
        if re.search(rb"(?i)(cf-chl-|g-recaptcha|<title>\s*(access denied|just a moment))", body):
            raise CorpusError("source access challenge; permission or an alternative is required")
        return bytes(body)


def _store(root: Path, directory: str, digest: str, suffix: str, data: bytes) -> None:
    path = root / directory / f"{digest}.{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise CorpusError("cached content does not match its digest")
    else:
        with path.open("xb") as stream:
            stream.write(data)


def _held_out_ids(requests: Sequence[DocumentRequest], seed: int) -> set[str]:
    cells: dict[tuple[str, str], list[DocumentRequest]] = defaultdict(list)
    for request in requests:
        cells[request.jurisdiction, request.genre].append(request)
    held_out = set()
    for (_, genre), cell in cells.items():
        ordered = sorted(cell, key=lambda r: (sha256(f"{seed}:{r.group_id}".encode()), r.document_id))
        if genre == "statutes-regulations":
            for kind in ("statute", "regulation"):
                match = next((r for r in ordered if r.subgenre == kind), None)
                if match:
                    held_out.add(match.document_id)
        else:
            held_out.update(r.document_id for r in ordered[:2])
    return held_out


def _source_snapshot(doc: AcquiredDocument, canonical: str) -> SourceSnapshot:
    request = doc.request
    return SourceSnapshot(
        source_id=request.document_id, group_id=request.group_id, title=request.title,
        genre=request.genre, subgenre=request.subgenre, jurisdiction=request.jurisdiction,
        synthetic=False, partition=doc.partition,
        text=request.span.source_slice(canonical), sha256=doc.span_sha256)


def collect(requests: Sequence[DocumentRequest], policy: AcquisitionPolicy, root: Path,
            fetcher: HttpFetcher, *, seed: int = 0,
            draft_gold: Callable[[SourceSnapshot], Sequence[GoldProposition]] | None = None) -> CorpusManifest:
    """Collect one bounded cell; failed requests remain explicit coverage gaps.

    Gold drafting is an injected judge port, never a CLI/network call here. Drafts
    cannot set anchor status. Gold spans are relative to the retained selection.
    """
    if seed < 0:
        raise CorpusError("sampling seed must be nonnegative")
    if not 0 < len(requests) <= policy.documents_per_cell:
        raise CorpusError("collection takes one to eight documents per invocation")
    if len({(r.jurisdiction, r.genre) for r in requests}) != 1:
        raise CorpusError("collect one jurisdiction/genre cell at a time")
    if len({r.document_id for r in requests}) != len(requests):
        raise CorpusError("duplicate document IDs")
    if (root / "manifest.json").exists() or (root / "sealed.json").exists():
        raise CorpusError("acquisition manifest already exists; use a new snapshot directory")
    held_out = _held_out_ids(requests, seed)
    sources = {s.source_id: s for s in policy.sources}
    documents, gaps = [], []
    for request in sorted(requests, key=lambda r: r.document_id):
        try:
            source = sources.get(request.source_id)
            if source is None:
                raise CorpusError("source is absent from acquisition policy")
            _source_check(request, source)
            raw = fetcher.fetch(request, source, policy.max_download_bytes)
            canonical = normalize(raw, request)
            selected = request.span.source_slice(canonical)
            if not policy.minimum_words <= len(selected.split()) <= policy.maximum_words:
                raise CorpusError("selection must contain 150 to 400 words")
            raw_digest, normalized_digest = sha256(raw), sha256(canonical.encode("utf-8"))
            document = AcquiredDocument(
                request=request, source_policy=source, retrieved_at=datetime.now(timezone.utc),
                raw_sha256=raw_digest, normalized_sha256=normalized_digest,
                span_sha256=sha256(selected.encode("utf-8")),
                snapshot_id=_snapshot_id(raw_digest, normalized_digest, request),
                partition="held-out" if request.document_id in held_out else "tuning")
            if draft_gold is not None:
                snapshot = _source_snapshot(document, canonical)
                gold = GoldDocument(source=snapshot, propositions=tuple(draft_gold(snapshot)))
                document = document.model_copy(update={"propositions": gold.propositions})
            _store(root, "raw", raw_digest, "bin", raw)
            _store(root, "text", normalized_digest, "txt", canonical.encode("utf-8"))
            documents.append(document)
        except (ValueError, KeyError, etree.LxmlError) as exc:
            # Validation/parse exceptions can contain source text; record only safe categories.
            reason = str(exc) if type(exc) is CorpusError else "invalid source text, offsets or drafted gold"
            gaps.append(AcquisitionGap(document_id=request.document_id,
                                       jurisdiction=request.jurisdiction, genre=request.genre,
                                       url=request.url, reason=reason))
    manifest = CorpusManifest(policy=policy, seed=seed, documents=tuple(documents), gaps=tuple(gaps))
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_bytes(_json_bytes(manifest))
    return manifest


def verify(manifest: CorpusManifest, root: Path, *, jurisdiction: str | None = None,
           genre: str | None = None, require_documents: int = 8) -> Verification:
    """Offline verification from raw bytes through grounding, rights and group split."""
    errors = []
    cells: dict[tuple[str, str], list[AcquiredDocument]] = defaultdict(list)
    selected = [d for d in manifest.documents
                if (jurisdiction is None or d.request.jurisdiction == jurisdiction)
                and (genre is None or d.request.genre == genre)]
    for gap in manifest.gaps:
        if ((jurisdiction is None or gap.jurisdiction == jurisdiction)
                and (genre is None or gap.genre == genre)):
            errors.append(f"{gap.document_id}: {gap.reason}")
    if require_documents != 8:
        errors.append("pilot quota is exactly eight documents; it cannot be weakened")
    if not selected:
        errors.append("cell has no documents; eight independent groups required")
    ids = [d.request.document_id for d in manifest.documents]
    if len(ids) != len(set(ids)):
        errors.append("duplicate document IDs")
    policies = {s.source_id: s for s in manifest.policy.sources}
    for doc in selected:
        request = doc.request
        cells[request.jurisdiction, request.genre].append(doc)
        try:
            _source_check(request, doc.source_policy)
            if policies.get(request.source_id) != doc.source_policy:
                raise CorpusError("document source policy differs from manifest policy")
            if doc.retrieved_at.tzinfo is None:
                raise CorpusError("retrieved time needs a timezone")
            raw = (root / "raw" / f"{doc.raw_sha256}.bin").read_bytes()
            canonical_bytes = (root / "text" / f"{doc.normalized_sha256}.txt").read_bytes()
            canonical = canonical_bytes.decode("utf-8")
            if sha256(raw) != doc.raw_sha256 or sha256(canonical_bytes) != doc.normalized_sha256:
                raise CorpusError("raw or normalized snapshot digest mismatch")
            if normalize(raw, request) != canonical:
                raise CorpusError("canonical text differs from recorded extraction method")
            if _snapshot_id(doc.raw_sha256, doc.normalized_sha256, request) != doc.snapshot_id:
                raise CorpusError("snapshot identity mismatch")
            selected_text = request.span.source_slice(canonical)
            if sha256(selected_text.encode("utf-8")) != doc.span_sha256:
                raise CorpusError("selection offsets do not reproduce recorded grounding digest")
            if not manifest.policy.minimum_words <= len(selected_text.split()) <= manifest.policy.maximum_words:
                raise CorpusError("selection must contain 150 to 400 words")
            if doc.propositions:
                GoldDocument(source=_source_snapshot(doc, canonical), propositions=doc.propositions)
        except (OSError, ValueError, KeyError, etree.LxmlError) as exc:
            reason = str(exc) if type(exc) is CorpusError else "missing or invalid source, grounding or gold"
            errors.append(f"{request.document_id}: {reason}")
    # Independence is checked across the entire manifest, including across cells.
    groups: dict[str, list[str]] = defaultdict(list)
    content: dict[str, list[str]] = defaultdict(list)
    selections: dict[str, list[str]] = defaultdict(list)
    for doc in manifest.documents:
        groups[doc.request.group_id].append(doc.request.document_id)
        content[doc.normalized_sha256].append(doc.request.document_id)
        selections[doc.span_sha256].append(doc.request.document_id)
    if any(len(values) > 1 for values in groups.values()):
        errors.append("duplicate document group; eight independent groups required")
    if any(len(values) > 1 for values in content.values()):
        errors.append("duplicate canonical source text in independent groups")
    if any(len(values) > 1 for values in selections.values()):
        errors.append("duplicate retained selection in independent groups")
    if any(related in groups and related != doc.request.group_id
           for doc in manifest.documents for related in doc.request.related_group_ids):
        errors.append("related documents must share one group and cannot fill independent slots")
    for (_, cell_genre), docs in cells.items():
        if len(docs) != 8 or len({d.request.group_id for d in docs}) != 8:
            errors.append("cell requires eight documents from eight independent groups")
        if Counter(d.partition for d in docs) != {"tuning": 6, "held-out": 2}:
            errors.append("cell requires six tuning and two held-out groups")
        expected = _held_out_ids([d.request for d in docs], manifest.seed)
        if {d.request.document_id for d in docs if d.partition == "held-out"} != expected:
            errors.append("partition differs from reproducible group split")
        if cell_genre == "statutes-regulations":
            if Counter(d.request.subgenre for d in docs) != {"statute": 4, "regulation": 4}:
                errors.append("cell requires four statutes and four regulations")
            if Counter(d.request.subgenre for d in docs if d.partition == "held-out") != {
                    "statute": 1, "regulation": 1}:
                errors.append("held-out requires one statute and one regulation")
    return Verification(complete=not errors, documents=len(selected), errors=tuple(errors))


def seal(manifest: CorpusManifest, root: Path, tuning_output: Path) -> str:
    """Freeze full evaluator manifest and export only tuning selections and draft gold."""
    result = verify(manifest, root)
    if not result.complete:
        raise CorpusError("incomplete corpus cannot be sealed")
    root, tuning_output = root.resolve(), tuning_output.resolve()
    if root == tuning_output or root in tuning_output.parents or tuning_output in root.parents:
        raise CorpusError("tuning output and evaluator storage must be separate")
    if tuning_output.exists() or (root / "sealed.json").exists():
        raise CorpusError("sealed manifest or tuning output already exists")
    tuning_output.mkdir(parents=True)
    tuning_documents = []
    for doc in manifest.documents:
        if doc.partition != "tuning":
            continue
        canonical = (root / "text" / f"{doc.normalized_sha256}.txt").read_bytes().decode("utf-8")
        selected = doc.request.span.source_slice(canonical)
        selected_bytes = selected.encode("utf-8")
        if sha256(selected_bytes) != doc.span_sha256:
            raise CorpusError("exported selection does not match recorded grounding digest")
        _store(tuning_output, "text", doc.span_sha256, "txt", selected_bytes)
        # Raw files, held-out records and judge rationales never enter this payload.
        record = doc.model_dump(mode="json", exclude={"judge_rationale"})
        # The evaluator policy may list exact held-out document URLs. Narrow it
        # to this tuning document rather than distributing that shared allowlist.
        record["source_policy"]["url_prefixes"] = [doc.request.url]
        record["origin_span"] = doc.request.span.model_dump()
        record["request"]["span"] = {"start": 0, "end": len(selected)}
        record["text_sha256"] = doc.span_sha256
        tuning_documents.append(record)
    tuning = {"format": 1, "score_label": SCORE_LABEL, "documents": tuning_documents}
    (tuning_output / "manifest.json").write_bytes(_json_bytes(tuning))
    sealed_bytes = _json_bytes(manifest)
    with (root / "sealed.json").open("xb") as stream:
        stream.write(sealed_bytes)
    return sha256(sealed_bytes)
