"""Wave-0 placeholder for distinguo TTL emission. Impl lands in 01-04."""
import pytest

pytestmark = pytest.mark.polysemy_spike


@pytest.mark.xfail(reason="Wave-0 scaffold; impl in 01-04", strict=False)
def test_analogousTo_requires_sub_properties() -> None:
    """fi:analogousTo requires fi:primeAnalogate + fi:proportionalRelation
    sub-properties (VOCAB-02; PHILOSOPHY.md L108-141 scholastic distinguo)."""
    raise NotImplementedError("Wave-0 placeholder")


@pytest.mark.xfail(reason="Wave-0 scaffold; impl in 01-04", strict=False)
def test_distinctionKind_enum() -> None:
    """fi:distinctionKind values constrained to the 4-enum set (VOCAB-02)."""
    raise NotImplementedError("Wave-0 placeholder")


@pytest.mark.xfail(reason="Wave-0 scaffold; impl in 01-04", strict=False)
def test_ttl_roundtrip_pyoxigraph() -> None:
    """Emitted TTL parses via pyoxigraph + round-trips back to identical graph
    (uses consideration_fixture_store session fixture)."""
    raise NotImplementedError("Wave-0 placeholder")
