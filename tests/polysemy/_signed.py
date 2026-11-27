"""Disposable test reviewer identities; private key bytes are never persisted."""
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from folio_insights.proposals.signed_decisions import did_key_of, sign_decision

KEY = Ed25519PrivateKey.generate()
OTHER_KEY = Ed25519PrivateKey.generate()
DID = did_key_of(KEY)
OTHER_DID = did_key_of(OTHER_KEY)
CORPUS = "synthetic"


def signed_record(record, *, key=None, now=None, nonce=None):
    from folio_insights.polysemy.signing import disposition_fields

    record = record.model_copy(update={"corpus": CORPUS})
    key = key or (OTHER_KEY if record.reviewer_did == OTHER_DID else KEY)
    signed = sign_decision(disposition_fields(record), signing_key=key, now=now, nonce=nonce)
    return record.model_copy(update={"signed_decision": signed})


def signed_certificate(certificate, *, key=KEY, now=None):
    from folio_insights.polysemy.signing import certification_fields

    certificate = certificate.model_copy(update={"corpus": CORPUS})
    signed = sign_decision(certification_fields(certificate), signing_key=key, now=now)
    return certificate.model_copy(update={"signed_decision": signed})
