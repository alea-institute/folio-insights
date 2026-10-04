"""U17 versioned shard-record adapter (R18 interchange + migration policy).

The ONE sanctioned path between stored shard records (bytes / JSON) and the
in-memory ``Shard`` discriminated union. Phase 13 storage persists what this
module returns and never calls ``TypeAdapter(Shard)`` on stored bytes directly.

Versions (``ENVELOPE_SCHEMA_VERSION`` lives in ``envelope.py``):

* **1 — legacy.** The unstamped envelope shipped through Phase 8. A record with
  no ``schema_version`` key is version 1.
* **2 — current.** Adds the frozen ``schema_version`` stamp and requires the
  nullable envelope keys to be present (``null`` is data, not absence — R18).

Guarantees:

* Forward-only, copying migration: the caller's input is never mutated; each
  registered consecutive step runs on a deep copy. No downgrades.
* Identity preservation: steps may not change the identity boundary
  (``IDENTITY_FIELDS``); the loader checks this after migration and refuses a
  step that did.
* Explicit nulls stay ``null``; absent nullable keys in a legacy record become
  explicit ``null``.
* The exact original bytes and the source version travel with the result.
* Unsupported versions raise ``UnsupportedEnvelopeVersion``; nothing is guessed.
* Signatures: content-hash binding (``revision.canonical_content_hash``)
  excludes ``schema_version``, so a content-preserving step keeps existing
  signatures verifiable, while a content-changing step changes the hashed bytes
  and the verifier refuses old signatures. Loading ANY legacy record also
  resets every cached ``verified`` annotation to ``None`` so a stored "verified"
  flag never survives a version change. Rule for future steps: a step that
  re-interprets a value must change its bytes (rename, re-value) — never keep
  the same bytes under a new meaning.

Pure stdlib + Pydantic (dep-leak guard: no RDF/storage imports here).
"""
from __future__ import annotations

import copy
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import TypeAdapter

from folio_insights.shards.envelope import ENVELOPE_SCHEMA_VERSION, ShardEnvelope
from folio_insights.shards.subtypes import Shard

LEGACY_ENVELOPE_SCHEMA_VERSION: int = 1

# Nullable top-level envelope keys that a current-version record must carry
# explicitly (R18 null semantics: null is data, not absence).
NULLABLE_ENVELOPE_KEYS: tuple[str, ...] = (
    "valid_time_start",
    "valid_time_end",
    "supersedes",
    "superseded_by",
)

# The identity boundary no migration step may alter (R18 "Adopt into frozen
# storage now"). Mirrors the Pydantic-frozen envelope fields minus the stamp.
IDENTITY_FIELDS: tuple[str, ...] = (
    "shard_iri",
    "provenance_hash",
    "source_uri",
    "source_span",
    "extracted_at",
    "first_extractor_did",
)

_SHARD_ADAPTER: TypeAdapter = TypeAdapter(Shard)


class UnsupportedEnvelopeVersion(ValueError):
    """The record's ``schema_version`` is not one this code can load."""


class MalformedEnvelopeRecord(ValueError):
    """The record is not a well-formed shard record for its declared version."""


@dataclass(frozen=True)
class EnvelopeMigration:
    """One consecutive forward step ``from_version -> to_version``.

    ``apply`` receives a private deep copy and returns the migrated mapping.
    ``content_preserving`` declares that the step leaves every hashed content
    field byte-identical (only representation changes such as the stamp).
    """

    from_version: int
    to_version: int
    content_preserving: bool
    apply: Callable[[dict[str, Any]], dict[str, Any]]


def _migrate_v1_to_v2(record: dict[str, Any]) -> dict[str, Any]:
    """Legacy v1 -> v2: stamp the version and materialize absent nullable keys.

    Present values — including explicit ``null`` — are left untouched.
    """
    for key in NULLABLE_ENVELOPE_KEYS:
        record.setdefault(key, None)
    record["schema_version"] = 2
    return record


MIGRATIONS: Mapping[tuple[int, int], EnvelopeMigration] = {
    (1, 2): EnvelopeMigration(
        from_version=1,
        to_version=2,
        content_preserving=True,
        apply=_migrate_v1_to_v2,
    ),
}


@dataclass(frozen=True)
class LoadedShardRecord:
    """Result of ``load_shard_record``.

    * ``shard`` — the validated current-version shard.
    * ``source_schema_version`` — the version the stored record declared.
    * ``original_bytes`` — the exact bytes supplied (for a ``Mapping`` input,
      a deterministic sorted-key compact JSON rendering of it).
    * ``migrated`` — ``True`` iff at least one migration step ran.
    * ``content_preserved`` — ``True`` iff every step that ran declared itself
      content-preserving (vacuously ``True`` when nothing ran).
    """

    shard: ShardEnvelope
    source_schema_version: int
    original_bytes: bytes
    migrated: bool
    content_preserved: bool
    steps: tuple[tuple[int, int], ...] = field(default=())


def _parse(raw: bytes | str | Mapping[str, Any]) -> tuple[dict[str, Any], bytes]:
    if isinstance(raw, Mapping):
        data = copy.deepcopy(dict(raw))
        original = json.dumps(
            data, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return data, original
    if isinstance(raw, str):
        original = raw.encode("utf-8")
    elif isinstance(raw, (bytes, bytearray)):
        original = bytes(raw)
    else:
        raise MalformedEnvelopeRecord(
            f"shard record must be bytes, str, or a mapping; got {type(raw).__name__}"
        )
    try:
        data = json.loads(original.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MalformedEnvelopeRecord(f"shard record is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise MalformedEnvelopeRecord("shard record must be a JSON object")
    return data, original


def _declared_version(data: Mapping[str, Any]) -> int:
    if "schema_version" not in data:
        return LEGACY_ENVELOPE_SCHEMA_VERSION
    version = data["schema_version"]
    if isinstance(version, bool) or not isinstance(version, int):
        raise UnsupportedEnvelopeVersion(
            f"schema_version must be an integer; got {version!r}"
        )
    return version


def _reset_verified(signatures: Any) -> None:
    """Clear cached ``verified`` annotations (and nested cosigners) in place."""
    if not isinstance(signatures, list):
        return
    for sig in signatures:
        if isinstance(sig, dict):
            if "verified" in sig:
                sig["verified"] = None
            _reset_verified(sig.get("cosigners"))


def _reset_all_verified(data: dict[str, Any]) -> None:
    _reset_verified(data.get("signatures"))
    edits = data.get("content_edits")
    if isinstance(edits, list):
        for edit in edits:
            if isinstance(edit, dict) and isinstance(edit.get("signature"), dict):
                _reset_verified([edit["signature"]])


def load_shard_record(
    raw: bytes | str | Mapping[str, Any],
    *,
    migrations: Mapping[tuple[int, int], EnvelopeMigration] = MIGRATIONS,
) -> LoadedShardRecord:
    """Load a stored shard record, migrating supported legacy versions forward.

    Raises ``UnsupportedEnvelopeVersion`` for a non-integer, boolean, < 1,
    newer-than-current, or path-less version, and ``MalformedEnvelopeRecord``
    for non-JSON input or a current-version record missing a nullable key.
    Pydantic ``ValidationError`` propagates for a record that parses but does
    not validate as a ``Shard``.
    """
    current_version = ENVELOPE_SCHEMA_VERSION
    data, original = _parse(raw)
    source_version = _declared_version(data)
    if source_version < 1:
        raise UnsupportedEnvelopeVersion(
            f"schema_version {source_version} is below the first version (1)"
        )
    if source_version > current_version:
        raise UnsupportedEnvelopeVersion(
            f"schema_version {source_version} is newer than this code supports "
            f"({current_version}); refusing to guess"
        )

    identity_before = {k: data.get(k) for k in IDENTITY_FIELDS}
    steps: list[tuple[int, int]] = []
    content_preserved = True
    version = source_version
    while version < current_version:
        step = migrations.get((version, version + 1))
        if step is None:
            raise UnsupportedEnvelopeVersion(
                f"no migration registered from schema_version {version} "
                f"to {version + 1}"
            )
        data = step.apply(copy.deepcopy(data))
        if not isinstance(data, dict) or data.get("schema_version") != version + 1:
            raise MalformedEnvelopeRecord(
                f"migration {version}->{version + 1} did not stamp "
                f"schema_version {version + 1}"
            )
        steps.append((version, version + 1))
        content_preserved = content_preserved and step.content_preserving
        version += 1

    if steps:
        if {k: data.get(k) for k in IDENTITY_FIELDS} != identity_before:
            raise MalformedEnvelopeRecord(
                "a migration step altered the frozen identity boundary"
            )
        _reset_all_verified(data)

    missing = [k for k in NULLABLE_ENVELOPE_KEYS if k not in data]
    if missing:
        raise MalformedEnvelopeRecord(
            f"schema_version {current_version} record must carry nullable keys "
            f"explicitly (null is data, not absence); missing {missing}"
        )

    shard = _SHARD_ADAPTER.validate_python(data)
    return LoadedShardRecord(
        shard=shard,
        source_schema_version=source_version,
        original_bytes=original,
        migrated=bool(steps),
        content_preserved=content_preserved,
        steps=tuple(steps),
    )


def dump_shard_record(shard: ShardEnvelope) -> bytes:
    """Serialize ``shard`` as a current-version record (compact UTF-8 JSON).

    Explicit nulls are kept and the ``schema_version`` stamp is always present.
    """
    return shard.model_dump_json().encode("utf-8")


__all__ = [
    "IDENTITY_FIELDS",
    "LEGACY_ENVELOPE_SCHEMA_VERSION",
    "MIGRATIONS",
    "NULLABLE_ENVELOPE_KEYS",
    "EnvelopeMigration",
    "LoadedShardRecord",
    "MalformedEnvelopeRecord",
    "UnsupportedEnvelopeVersion",
    "dump_shard_record",
    "load_shard_record",
]
