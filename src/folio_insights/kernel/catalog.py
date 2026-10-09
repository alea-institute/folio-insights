"""The packaged axiom kernel: verified regulae iuris as data (drain U3, KTD6).

PHILOSOPHY.md Part II ("Regulae iuris as seed axiom kernel") designates the 88
*regulae iuris* of the Liber Sextus (VI 5.12) and the Digest's parallel title
(D.50.17, *De diversis regulis iuris antiqui*) as the seed axiomatic layer that
derivation chains terminate in. This module loads both collections from the
package's verified datasets and gives every maxim a stable identity.

* **Fetched, never generated.** ``data/liber_sextus_regulae.json`` and
  ``data/digest_50_17.json`` were produced by
  ``scripts/kernel/fetch_and_verify_sources.py``: every Latin string is cut out
  of a downloaded public-domain edition by code, with the source URL, edition,
  retrieval time and the SHA-256 of the fetched page recorded per item. This
  module never edits, normalises or translates the Latin; it reads it.
* **Verified only.** A maxim enters the catalog only when the dataset marks it
  ``verified_substring`` (for the Digest, every paragraph too). Excluded items
  and verified-but-single-source items (``cross_checked`` false) are exposed
  for review rather than silently dropped.
* **Stable identity (R10, R20).** Each maxim's canonical citation URI is
  ``urn:folio:kernel:liber-sextus:5.12.<n>`` or
  ``urn:folio:kernel:digest:50.17.<n>``; its shard IRI and provenance hash are
  ``mint_shard_iri(citation_uri, latin)``, the unchanged shard recipe, so the
  same maxim mints the same IRI on every machine.
* **Kernel membership** is the packaged manifest: ``is_kernel_iri`` answers
  from the set of catalog IRIs, never from a field on the envelope.

Stdlib only (plus the pure ``shards.minting`` and ``models.framework``).
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from importlib.resources import files
from typing import Any, Literal

from folio_insights.models.framework import Framework
from folio_insights.shards.minting import mint_shard_iri

CollectionKey = Literal["liber_sextus", "digest"]


@dataclass(frozen=True)
class KernelCollection:
    """One packaged kernel collection and the framework its maxims belong to.

    ``valid_from`` is the collection's promulgation date, used as every seeded
    shard's ``valid_time_start``: the Liber Sextus was promulgated by Boniface
    VIII's bull *Sacrosanctae* on 3 March 1298; the Digest by Justinian's
    constitution *Tanta* on 16 December 533.
    """

    key: CollectionKey
    data_file: str
    urn_slug: str
    citation_prefix: str  # citation_uri = f"urn:folio:kernel:{urn_slug}:{citation_prefix}.<n>"
    framework: Framework
    valid_from: datetime

    def citation_uri(self, number: int) -> str:
        return f"urn:folio:kernel:{self.urn_slug}:{self.citation_prefix}.{number}"


COLLECTIONS: Mapping[str, KernelCollection] = {
    "liber_sextus": KernelCollection(
        key="liber_sextus",
        data_file="liber_sextus_regulae.json",
        urn_slug="liber-sextus",
        citation_prefix="5.12",
        framework=Framework(
            id="ius_commune.canon.liber_sextus",
            label="Liber Sextus Decretalium (Boniface VIII, 1298)",
            jurisdiction="ius_commune",
        ),
        valid_from=datetime(1298, 3, 3, tzinfo=UTC),
    ),
    "digest": KernelCollection(
        key="digest",
        data_file="digest_50_17.json",
        urn_slug="digest",
        citation_prefix="50.17",
        framework=Framework(
            id="ius_commune.roman.digest",
            label="Digesta Iustiniani (533)",
            jurisdiction="ius_commune",
        ),
        valid_from=datetime(533, 12, 16, tzinfo=UTC),
    ),
}
COLLECTION_KEYS: tuple[str, ...] = tuple(COLLECTIONS)


class UnknownCollection(KeyError):
    """A collection key is not one of ``COLLECTION_KEYS``."""

    def __str__(self) -> str:
        return str(self.args[0]) if self.args else "unknown kernel collection"


def collection_spec(key: str) -> KernelCollection:
    try:
        return COLLECTIONS[key]
    except KeyError:
        raise UnknownCollection(
            f"unknown kernel collection {key!r}; expected one of {list(COLLECTION_KEYS)}"
        ) from None


@dataclass(frozen=True)
class MaximProvenance:
    """Where a maxim's Latin text was cut from (recorded by the fetch script)."""

    source_url: str
    edition: str
    retrieved_at: str  # ISO-8601 UTC, as recorded in the dataset
    sha256: str  # SHA-256 of the fetched source page / file
    verified_substring: bool
    cross_checked: bool


@dataclass(frozen=True)
class KernelMaxim:
    """One verified kernel maxim with its minted identity."""

    collection: str
    number: int
    citation: str
    citation_uri: str
    latin: str
    provenance: MaximProvenance
    shard_iri: str
    provenance_hash: str
    inscription: str | None = None

    @property
    def iri(self) -> str:
        return self.shard_iri

    @property
    def reference(self) -> str:
        """The citation, with the Digest fragment's inscription when it has one."""
        if self.inscription:
            return f"{self.citation} ({self.inscription})"
        return self.citation

    def as_dict(self) -> dict[str, Any]:
        return {
            "collection": self.collection,
            "number": self.number,
            "citation": self.citation,
            "citation_uri": self.citation_uri,
            "shard_iri": self.shard_iri,
            "provenance_hash": self.provenance_hash,
            "latin": self.latin,
            "inscription": self.inscription,
            "provenance": {
                "source_url": self.provenance.source_url,
                "edition": self.provenance.edition,
                "retrieved_at": self.provenance.retrieved_at,
                "sha256": self.provenance.sha256,
                "verified_substring": self.provenance.verified_substring,
                "cross_checked": self.provenance.cross_checked,
            },
        }


@dataclass(frozen=True)
class ExcludedItem:
    """A dataset item left out of the catalog, with the reason."""

    collection: str
    number: int
    citation: str
    reason: str


@dataclass(frozen=True)
class KernelCatalog:
    """Every verified maxim of the packaged collections, in collection order."""

    maxims: tuple[KernelMaxim, ...]
    excluded: tuple[ExcludedItem, ...]
    dataset_sha256: Mapping[str, str]
    _by_iri: Mapping[str, KernelMaxim] = field(repr=False, compare=False, default_factory=dict)

    def __post_init__(self) -> None:
        by_iri: dict[str, KernelMaxim] = {}
        for maxim in self.maxims:
            if maxim.shard_iri in by_iri:  # two maxims with identical citation and text
                raise ValueError(f"kernel IRI collision at {maxim.citation}")
            by_iri[maxim.shard_iri] = maxim
        object.__setattr__(self, "_by_iri", by_iri)

    def __iter__(self) -> Iterator[KernelMaxim]:
        return iter(self.maxims)

    def __len__(self) -> int:
        return len(self.maxims)

    def collection(self, key: str) -> tuple[KernelMaxim, ...]:
        collection_spec(key)
        return tuple(m for m in self.maxims if m.collection == key)

    def by_iri(self, iri: str) -> KernelMaxim | None:
        return self._by_iri.get(iri)

    def by_citation(self, citation: str) -> KernelMaxim | None:
        for maxim in self.maxims:
            if maxim.citation == citation:
                return maxim
        return None

    @property
    def manifest(self) -> frozenset[str]:
        """The kernel manifest: every kernel shard IRI."""
        return frozenset(self._by_iri)

    def single_source(self) -> tuple[KernelMaxim, ...]:
        """Verified maxims no second independent transcription confirms."""
        return tuple(m for m in self.maxims if not m.provenance.cross_checked)

    def counts(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for key in COLLECTION_KEYS:
            items = self.collection(key)
            out[key] = {
                "verified": len(items),
                "single_source": sum(1 for m in items if not m.provenance.cross_checked),
                "excluded": sum(1 for e in self.excluded if e.collection == key),
            }
        return out


def _read_dataset(spec: KernelCollection) -> tuple[bytes, dict[str, Any]]:
    raw = (files("folio_insights.kernel") / "data" / spec.data_file).read_bytes()
    return raw, json.loads(raw.decode("utf-8"))


def _source_for(data: Mapping[str, Any], url: str) -> Mapping[str, Any]:
    """The dataset ``sources`` entry a per-item URL (fragment ignored) names."""
    base = url.split("#", 1)[0]
    for source in data.get("sources", ()):
        if source.get("url") == base:
            return source
    raise ValueError(f"dataset {data.get('collection')!r} records no source entry for {base!r}")


def _maxim(spec: KernelCollection, data: Mapping[str, Any], item: Mapping[str, Any],
           ) -> KernelMaxim:
    number = int(item["number"])
    latin = item["latin"]
    if spec.key == "liber_sextus":
        provenance = MaximProvenance(
            source_url=item["source_url"],
            edition=item["edition"],
            retrieved_at=item["retrieved_at"],
            sha256=item["sha256"],
            verified_substring=bool(item["verified_substring"]),
            cross_checked=bool(item["cross_checked"]),
        )
        inscription = None
    else:
        # Digest items record only their per-fragment URL; the edition and the
        # retrieval record live once in the dataset header's ``sources``.
        source = _source_for(data, item["source_url"])
        provenance = MaximProvenance(
            source_url=item["source_url"],
            edition=data["edition"],
            retrieved_at=source["retrieved_at"],
            sha256=source["sha256"],
            verified_substring=bool(item["verified_substring"]),
            cross_checked=bool(item["cross_checked"]),
        )
        inscription = item.get("inscription") or None
    citation_uri = spec.citation_uri(number)
    iri, provenance_hash = mint_shard_iri(citation_uri, latin)
    return KernelMaxim(
        collection=spec.key,
        number=number,
        citation=item["citation"],
        citation_uri=citation_uri,
        latin=latin,
        provenance=provenance,
        shard_iri=iri,
        provenance_hash=provenance_hash,
        inscription=inscription,
    )


def _exclusion_reason(spec: KernelCollection, item: Mapping[str, Any]) -> str | None:
    if not item.get("latin"):
        return "no Latin text recorded"
    if item.get("verified_substring") is not True:
        return "Latin text is not a verified substring of the recorded source"
    if spec.key == "digest":
        paragraphs = item.get("paragraphs") or []
        if not paragraphs or any(p.get("verified_substring") is not True for p in paragraphs):
            return "a paragraph is not a verified substring of the recorded source"
    return None


@lru_cache(maxsize=1)
def load_catalog() -> KernelCatalog:
    """Load and verify-filter both packaged collections (cached per process)."""
    maxims: list[KernelMaxim] = []
    excluded: list[ExcludedItem] = []
    digests: dict[str, str] = {}
    for spec in COLLECTIONS.values():
        raw, data = _read_dataset(spec)
        digests[spec.key] = hashlib.sha256(raw).hexdigest()
        for item in data["items"]:
            reason = _exclusion_reason(spec, item)
            if reason is not None:
                excluded.append(
                    ExcludedItem(spec.key, int(item["number"]), str(item.get("citation")), reason)
                )
                continue
            maxims.append(_maxim(spec, data, item))
    return KernelCatalog(tuple(maxims), tuple(excluded), dict(digests))


def kernel_manifest() -> frozenset[str]:
    """The set of kernel shard IRIs (the packaged manifest)."""
    return load_catalog().manifest


def is_kernel_iri(iri: str) -> bool:
    """True iff ``iri`` is a kernel shard IRI."""
    return iri in load_catalog().manifest


def dataset_sha256(key: str) -> str:
    """SHA-256 of a collection's packaged dataset file (its exact bytes)."""
    return load_catalog().dataset_sha256[collection_spec(key).key]


__all__ = [
    "COLLECTIONS",
    "COLLECTION_KEYS",
    "CollectionKey",
    "ExcludedItem",
    "KernelCatalog",
    "KernelCollection",
    "KernelMaxim",
    "MaximProvenance",
    "UnknownCollection",
    "collection_spec",
    "dataset_sha256",
    "is_kernel_iri",
    "kernel_manifest",
    "load_catalog",
]
