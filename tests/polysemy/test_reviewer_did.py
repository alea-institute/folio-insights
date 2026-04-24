"""Wave-0 placeholder for reviewer did:key generation. Impl lands in 01-02."""
import pytest

pytestmark = pytest.mark.polysemy_spike


@pytest.mark.xfail(reason="Wave-0 scaffold; impl in 01-02", strict=False)
def test_first_invocation_generates_real_did_key() -> None:
    """First invocation generates a real did:key (Ed25519 + base58btc multibase
    encoding per W3C did:key spec); persisted to ~/.folio-insights/ (gitignored)."""
    raise NotImplementedError("Wave-0 placeholder")
