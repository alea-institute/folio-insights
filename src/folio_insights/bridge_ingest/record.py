"""Load a folio-enrich proposition export into a ``PropositionDocumentRecord``.

Accepted forms (all end as a current-schema record):

* a ``PropositionDocumentRecord`` instance;
* a mapping (the decoded JSON object);
* JSON text or bytes (``GET /enrich/{job}/export?format=propositions``);
* NDJSON text or bytes (``format=propositions-ndjson``): one JSON object per
  line. A header line carries the record fields (``document_id``,
  ``source_uri``, ``generator``, ``document_metadata``, ``schema_version``)
  and ``record_type`` in ``{"proposition_document", "document", "record",
  "header"}``; every following line is one proposition with
  ``record_type: "proposition"`` (a line without ``record_type`` that has a
  ``proposition_type`` is also read as a proposition). A single line holding
  a whole record (a ``propositions`` list) is accepted too;
* a filesystem path (``str`` or ``Path``) to either file form. The form is
  sniffed: a document that parses as one JSON object is JSON, otherwise it is
  read as NDJSON.

Records older than the library's ``SCHEMA_VERSION`` go through
``folio_propositions.migrate_record`` first. Before model validation every
stamped ``content_iri`` is compared with ``mint_shard_iri`` so a mismatch is
refused as ``ContentIriMismatch`` naming the proposition (the library's own
validator would refuse it too, but with a less specific error).
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from folio_propositions import SCHEMA_VERSION, PropositionDocumentRecord, migrate_record
from pydantic import ValidationError

from folio_insights.bridge_ingest.errors import ContentIriMismatch, InvalidRecord
from folio_insights.shards.minting import mint_shard_iri

HEADER_RECORD_TYPES = frozenset({"proposition_document", "document", "record", "header"})
PROPOSITION_RECORD_TYPE = "proposition"


@dataclass(frozen=True)
class LoadedRecord:
    """A validated record plus the SHA-256 of its canonical JSON form."""

    record: PropositionDocumentRecord
    sha256: str


def canonical_record_bytes(record: PropositionDocumentRecord) -> bytes:
    """Canonical JSON (sorted keys, compact) of a validated record."""
    return json.dumps(
        record.model_dump(mode="json"), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _decode(raw: bytes | str) -> str:
    if isinstance(raw, bytes):
        try:
            return raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise InvalidRecord("record is not UTF-8 text") from None
    return raw.removeprefix("﻿")


def parse_json_text(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InvalidRecord(f"record is not valid JSON (line {exc.lineno})") from None
    if not isinstance(data, dict):
        raise InvalidRecord("record JSON must be an object")
    return data


def parse_ndjson_text(text: str) -> dict[str, Any]:
    """Assemble a record dict from the NDJSON form (see module docstring)."""
    header: dict[str, Any] | None = None
    propositions: list[Any] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            raise InvalidRecord(f"NDJSON line {lineno} is not valid JSON") from None
        if not isinstance(obj, dict):
            raise InvalidRecord(f"NDJSON line {lineno} must be a JSON object")
        kind = obj.pop("record_type", None)
        if kind in HEADER_RECORD_TYPES or (
            kind is None and "document_id" in obj and "proposition_type" not in obj
        ):
            if header is not None:
                raise InvalidRecord(f"NDJSON line {lineno} is a second record header")
            header = obj
            embedded = header.pop("propositions", None)
            if embedded is not None:
                if not isinstance(embedded, list):
                    raise InvalidRecord("record header 'propositions' must be a list")
                propositions.extend(embedded)
        elif kind == PROPOSITION_RECORD_TYPE or (kind is None and "proposition_type" in obj):
            propositions.append(obj)
        else:
            raise InvalidRecord(f"NDJSON line {lineno} has unknown record_type {kind!r}")
    if header is None:
        raise InvalidRecord("NDJSON record has no header line (record_type 'proposition_document')")
    header["propositions"] = propositions
    return header


def parse_record_text(raw: bytes | str, *, ndjson: bool | None = None) -> dict[str, Any]:
    """Parse JSON or NDJSON. ``ndjson=None`` sniffs the form."""
    text = _decode(raw)
    if ndjson is True:
        return parse_ndjson_text(text)
    if ndjson is False:
        return parse_json_text(text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return parse_ndjson_text(text)
    if not isinstance(data, dict):
        raise InvalidRecord("record JSON must be an object")
    if data.get("record_type") in HEADER_RECORD_TYPES:
        # A one-line NDJSON document whose header is the whole record.
        return parse_ndjson_text(text)
    return data


def _check_content_iris(data: Mapping[str, Any]) -> None:
    source_uri = data.get("source_uri")
    if not isinstance(source_uri, str) or not source_uri:
        return
    for proposition in data.get("propositions") or []:
        if not isinstance(proposition, Mapping):
            continue
        text, stamped = proposition.get("text"), proposition.get("content_iri")
        if not isinstance(text, str) or not isinstance(stamped, str):
            continue
        minted, _ = mint_shard_iri(source_uri, text)
        if stamped != minted:
            raise ContentIriMismatch(str(proposition.get("id")), stamped, minted)


def _sanitized(exc: ValidationError) -> InvalidRecord:
    shown = "; ".join(
        f"{'.'.join(str(p) for p in err.get('loc', ())) or 'record'}: {err.get('msg')}"
        for err in exc.errors(include_input=False, include_url=False)[:5]
    )
    more = f" (+{exc.error_count() - 5} more)" if exc.error_count() > 5 else ""
    return InvalidRecord(f"record does not validate as PropositionDocumentRecord: {shown}{more}")


def record_from_mapping(data: Mapping[str, Any]) -> PropositionDocumentRecord:
    """Migrate (when older) and validate a decoded record."""
    migrated: dict[str, Any] = dict(data)
    version = migrated.get("schema_version", SCHEMA_VERSION)
    if isinstance(version, bool) or not isinstance(version, int):
        raise InvalidRecord("record schema_version must be an integer")
    if version > SCHEMA_VERSION:
        raise InvalidRecord(
            f"record schema_version {version} is newer than folio-propositions "
            f"supports ({SCHEMA_VERSION})"
        )
    if version < SCHEMA_VERSION:
        try:
            migrated = migrate_record(migrated)
        except ValueError as exc:
            raise InvalidRecord(f"record migration failed: {exc}") from None
    _check_content_iris(migrated)
    try:
        return PropositionDocumentRecord.model_validate(migrated)
    except ValidationError as exc:
        raise _sanitized(exc) from None


def load_record(
    source: PropositionDocumentRecord | Mapping[str, Any] | bytes | str | Path,
    *,
    ndjson: bool | None = None,
) -> LoadedRecord:
    """Load any accepted form (see module docstring) into a ``LoadedRecord``.

    A ``str`` is read as record text when it starts with ``{`` (after
    whitespace); otherwise it is a filesystem path.
    """
    if isinstance(source, PropositionDocumentRecord):
        record = record_from_mapping(source.model_dump(mode="json"))
    elif isinstance(source, Mapping):
        record = record_from_mapping(source)
    elif isinstance(source, Path) or (
        isinstance(source, str) and not source.lstrip().startswith("{")
    ):
        path = Path(source)
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise InvalidRecord(f"cannot read record file ({type(exc).__name__})") from None
        if ndjson is None and path.suffix.lower() in {".ndjson", ".jsonl"}:
            ndjson = True
        record = record_from_mapping(parse_record_text(raw, ndjson=ndjson))
    else:
        record = record_from_mapping(parse_record_text(source, ndjson=ndjson))
    return LoadedRecord(record, hashlib.sha256(canonical_record_bytes(record)).hexdigest())


__all__ = [
    "HEADER_RECORD_TYPES",
    "PROPOSITION_RECORD_TYPE",
    "LoadedRecord",
    "canonical_record_bytes",
    "load_record",
    "parse_json_text",
    "parse_ndjson_text",
    "parse_record_text",
    "record_from_mapping",
]
