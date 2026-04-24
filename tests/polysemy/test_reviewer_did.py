"""Real did:key (ed25519) generation + JWK persistence (OQ-4 RESOLVED)."""
import json
from pathlib import Path

import base58
import pytest

pytestmark = pytest.mark.polysemy_spike


def test_first_invocation_generates_real_did_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from folio_insights.polysemy import reviewer

    key_path = tmp_path / ".folio-insights" / "reviewer.jwk"
    did_path = tmp_path / ".folio-insights" / "reviewer.did"
    monkeypatch.setattr(reviewer, "KEY_PATH", key_path)
    monkeypatch.setattr(reviewer, "DID_PATH", did_path)

    did = reviewer.ensure_reviewer_did()
    assert did.startswith("did:key:z"), did
    raw = base58.b58decode(did.removeprefix("did:key:z"))
    assert len(raw) == 34
    assert raw[:2] == b"\xed\x01"
    mtime_before = key_path.stat().st_mtime
    did2 = reviewer.ensure_reviewer_did()
    assert did == did2
    assert key_path.stat().st_mtime == mtime_before
    # JWK persistence (OQ-4 RESOLVED): file content is valid JWK
    jwk = json.loads(key_path.read_text(encoding="utf-8"))
    assert jwk["kty"] == "OKP"
    assert jwk["crv"] == "Ed25519"
    assert "d" in jwk and "x" in jwk
