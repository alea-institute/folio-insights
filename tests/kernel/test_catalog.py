"""Drain U3 (R9, R10, KTD6) — the packaged kernel catalog.

The catalog loads every verified maxim of both packaged datasets with its
provenance; IRIs are ``mint_shard_iri(citation_uri, latin)`` and stable; the
Latin text is exactly the dataset's, which is pinned by its SHA-256.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from importlib.resources import files

import pytest

from folio_insights.kernel import catalog as catalog_mod
from folio_insights.kernel.catalog import (
    COLLECTIONS,
    UnknownCollection,
    collection_spec,
    dataset_sha256,
    is_kernel_iri,
    kernel_manifest,
    load_catalog,
)
from folio_insights.shards.minting import _normalize_uri, mint_shard_iri

# The reviewed datasets' exact bytes. Editing any Latin text (or any other
# byte) of a data file must be a deliberate, re-verified change: update the
# pin only together with a fresh run of scripts/kernel/fetch_and_verify_sources.py.
DATASET_SHA256 = {
    "liber_sextus": "720cf03bb62a4be477e2463fa94a97f96fcb58fba1ff9e96ad8430860e9959ab",
    "digest": "cb366adb166f8d9642c4fce0c423e9ef8de2909925bfca146b05b09d88b09758",
}


def _raw_items(key: str) -> list[dict]:
    spec = COLLECTIONS[key]
    raw = (files("folio_insights.kernel") / "data" / spec.data_file).read_text("utf-8")
    return json.loads(raw)["items"]


def test_catalog_counts_every_item_verified() -> None:
    cat = load_catalog()
    assert len(cat.collection("liber_sextus")) == 88
    assert len(cat.collection("digest")) == 211
    assert len(cat) == 299
    assert cat.excluded == ()
    counts = cat.counts()
    assert counts["liber_sextus"] == {"verified": 88, "single_source": 4, "excluded": 0}
    assert counts["digest"] == {"verified": 211, "single_source": 3, "excluded": 0}
    assert [m.citation for m in cat.single_source()] == [
        "VI 5.12.41", "VI 5.12.67", "VI 5.12.73", "VI 5.12.79",
        "D.50.17.73", "D.50.17.193", "D.50.17.205",
    ]
    assert all(m.provenance.verified_substring for m in cat)


def test_numbers_and_citations_follow_the_collection_forms() -> None:
    cat = load_catalog()
    ls = cat.collection("liber_sextus")
    dig = cat.collection("digest")
    assert [m.number for m in ls] == list(range(1, 89))
    assert [m.number for m in dig] == list(range(1, 212))
    for m in ls:
        assert m.citation == f"VI 5.12.{m.number}"
        assert m.citation_uri == f"urn:folio:kernel:liber-sextus:5.12.{m.number}"
        assert m.inscription is None and m.reference == m.citation
    for m in dig:
        assert m.citation == f"D.50.17.{m.number}"
        assert m.citation_uri == f"urn:folio:kernel:digest:50.17.{m.number}"
        assert m.inscription and m.reference == f"{m.citation} ({m.inscription})"


def test_iris_are_minted_from_citation_uri_and_latin() -> None:
    for m in load_catalog():
        assert (m.shard_iri, m.provenance_hash) == mint_shard_iri(m.citation_uri, m.latin)
        assert re.fullmatch(r"urn:folio:shard/[0-9a-f]{32}", m.shard_iri)


def test_iris_are_stable_across_loads() -> None:
    first = [(m.citation, m.shard_iri, m.provenance_hash) for m in load_catalog()]
    load_catalog.cache_clear()
    try:
        second = [(m.citation, m.shard_iri, m.provenance_hash) for m in load_catalog()]
    finally:
        load_catalog.cache_clear()
    assert first == second
    assert len({iri for _, iri, _ in first}) == len(first)  # no two maxims share an IRI


def test_known_maxim_identity_is_pinned() -> None:
    """A regression pin on one IRI: VI 5.12.6 must mint the same IRI forever."""
    m = load_catalog().by_citation("VI 5.12.6")
    assert m is not None
    assert m.latin == "Nemo potest ad impossibile obligari."
    expected, _ = mint_shard_iri("urn:folio:kernel:liber-sextus:5.12.6",
                                 "Nemo potest ad impossibile obligari.")
    assert m.shard_iri == expected


def test_citation_urns_normalize_to_themselves() -> None:
    """The URI normalizer leaves the kernel URNs untouched (deterministic minting)."""
    for m in load_catalog():
        assert _normalize_uri(m.citation_uri) == m.citation_uri


@pytest.mark.parametrize("key", ["liber_sextus", "digest"])
def test_dataset_bytes_are_pinned(key: str) -> None:
    raw = (files("folio_insights.kernel") / "data" / COLLECTIONS[key].data_file).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == DATASET_SHA256[key]
    assert dataset_sha256(key) == DATASET_SHA256[key]


@pytest.mark.parametrize("key", ["liber_sextus", "digest"])
def test_latin_is_exactly_the_dataset_text(key: str) -> None:
    raw = {item["number"]: item for item in _raw_items(key)}
    for m in load_catalog().collection(key):
        assert m.latin == raw[m.number]["latin"]  # byte-identical, never normalized
        assert unicodedata.normalize("NFC", m.latin) == m.latin
        assert m.latin == m.latin.strip() and m.latin
    if key == "digest":
        for m in load_catalog().collection(key):
            paragraphs = raw[m.number]["paragraphs"]
            assert m.latin == " ".join(p["latin"] for p in paragraphs)


def test_every_maxim_has_complete_provenance() -> None:
    for m in load_catalog():
        p = m.provenance
        assert p.source_url.startswith("https://")
        assert p.edition
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", p.retrieved_at)
        assert re.fullmatch(r"[0-9a-f]{64}", p.sha256)
        if m.collection == "liber_sextus":
            assert p.source_url.startswith("https://archive.org/download/")
            assert "Friedberg" in p.edition
        else:
            assert p.source_url.startswith(
                "https://droitromain.univ-grenoble-alpes.fr/Corpus/d-50.htm#50.17."
            )
            assert "Mommsen" in p.edition


def test_manifest_and_kernel_membership() -> None:
    cat = load_catalog()
    manifest = kernel_manifest()
    assert manifest == frozenset(m.shard_iri for m in cat)
    assert len(manifest) == 299
    m = cat.maxims[0]
    assert is_kernel_iri(m.shard_iri)
    assert cat.by_iri(m.shard_iri) is m
    assert not is_kernel_iri("urn:folio:shard/" + "0" * 32)


def test_unverified_items_are_excluded(monkeypatch: pytest.MonkeyPatch) -> None:
    """An item the dataset does not mark verified never enters the catalog."""
    real = catalog_mod._read_dataset

    def doctored(spec):  # noqa: ANN001, ANN202
        raw, data = real(spec)
        if spec.key == "liber_sextus":
            data["items"][0] = {**data["items"][0], "verified_substring": False}
        if spec.key == "digest":
            item = data["items"][1]
            paragraphs = [{**item["paragraphs"][0], "verified_substring": False}]
            data["items"][1] = {**item, "paragraphs": paragraphs}
        return raw, data

    monkeypatch.setattr(catalog_mod, "_read_dataset", doctored)
    load_catalog.cache_clear()
    try:
        cat = load_catalog()
        assert len(cat.collection("liber_sextus")) == 87
        assert len(cat.collection("digest")) == 210
        assert [(e.citation, e.collection) for e in cat.excluded] == [
            ("VI 5.12.1", "liber_sextus"), ("D.50.17.2", "digest"),
        ]
        assert cat.counts()["liber_sextus"]["excluded"] == 1
    finally:
        load_catalog.cache_clear()


def test_unknown_collection_is_refused() -> None:
    with pytest.raises(UnknownCollection, match="gratian"):
        collection_spec("gratian")
    with pytest.raises(UnknownCollection):
        load_catalog().collection("gratian")
