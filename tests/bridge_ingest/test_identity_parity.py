"""Plan R13: folio_propositions content identity == folio-insights mint_shard_iri."""
from __future__ import annotations

import unicodedata

import pytest
from folio_propositions import content_identity, content_iri
from hypothesis import given, settings
from hypothesis import strategies as st

from folio_insights.shards.minting import mint_shard_iri

# Fixed vectors: (source_uri, span) pairs whose two IRIs must coincide, plus
# the plan's AE1 equivalence.
FIXED = [
    ("https://example.com/a", "x\ny"),
    ("https://Example.com/a/", "x\r\ny "),
    ("HTTPS://EXAMPLE.COM/opinions/123/", "  The court held.\r\n"),
    ("urn:sha256:" + "a" * 64, "A span"),
    ("http://example.org/café", "café"),
    ("http://example.org/café", "café"),
    ("https://example.org/p?q=1&r=2#frag", "line one\rline two"),
    ("https://example.org/", "root path keeps its slash"),
]


@pytest.mark.parametrize(("uri", "span"), FIXED)
def test_fixed_vectors(uri: str, span: str) -> None:
    iri, provenance_hash = mint_shard_iri(uri, span)
    assert content_iri(uri, span) == iri
    assert content_identity(uri, span).provenance_hash == provenance_hash
    assert content_identity(uri, span).iri == iri


def test_ae1_normalization_equivalence() -> None:
    assert content_iri("https://Example.com/a/", "x\r\ny ") == mint_shard_iri(
        "https://example.com/a", "x\ny"
    )[0]


def test_nfc_nfd_uris_agree() -> None:
    nfc = "http://example.org/café"
    nfd = unicodedata.normalize("NFD", nfc)
    assert content_iri(nfc, "s") == content_iri(nfd, "s") == mint_shard_iri(nfd, "s")[0]


_segment = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cs", "Cc"), blacklist_characters="/?#%[]@:\\ "
    ),
    min_size=0,
    max_size=12,
)


@st.composite
def source_uris(draw: st.DrawFn) -> str:
    scheme = draw(st.sampled_from(["http", "https", "HTTP", "Https", "urn"]))
    segments = draw(st.lists(_segment, min_size=0, max_size=4))
    form = draw(st.sampled_from(["NFC", "NFD"]))
    path = "/".join(unicodedata.normalize(form, s) for s in segments)
    trailing = draw(st.sampled_from(["", "/"]))
    query = draw(st.sampled_from(["", "?q=1", "?a=b&c=d", "?x=café"]))
    fragment = draw(st.sampled_from(["", "#f", "#sec-2"]))
    if scheme == "urn":
        return f"urn:folio:{path or 'x'}{query}{fragment}"
    host = draw(st.sampled_from(["example.com", "EXAMPLE.org", "Courts.Example.GOV"]))
    return f"{scheme}://{host}/{path}{trailing}{query}{fragment}"


@st.composite
def spans(draw: st.DrawFn) -> str:
    words = draw(
        st.lists(
            st.text(alphabet=st.characters(blacklist_categories=("Cs",)), min_size=1, max_size=10),
            min_size=1,
            max_size=6,
        )
    )
    seps = st.sampled_from([" ", "\n", "\r\n", "\r", "\t"])
    body = words[0] + "".join(draw(seps) + w for w in words[1:])
    form = draw(st.sampled_from(["NFC", "NFD", None]))
    if form:
        body = unicodedata.normalize(form, body)
    lead = draw(st.sampled_from(["", " ", "\n", "\r\n  "]))
    tail = draw(st.sampled_from(["", " ", "\n", " \r\n"]))
    return lead + body + tail


@settings(max_examples=400, deadline=None)
@given(uri=source_uris(), span=spans())
def test_property_parity(uri: str, span: str) -> None:
    iri, provenance_hash = mint_shard_iri(uri, span)
    try:
        identity = content_identity(uri, span)
    except ValueError:
        # The library refuses spans that normalize to "" (insights would mint
        # an IRI for the bare URI); everything else must agree.
        folded = span.replace("\r\n", "\n").replace("\r", "\n")
        assert not unicodedata.normalize("NFC", folded).strip()
        return
    assert identity.iri == iri
    assert identity.provenance_hash == provenance_hash
    assert content_iri(uri, span) == iri
