"""Phase 7 promotion validator (D-20 cite-resolvable + D-21 status-kind cross-check).

The library-layer validator the ``governance promote`` CLI calls between
``authorize()`` and ``log.append(event)``. The Pydantic event class
(``PromotionEvent``) enforces the field-level invariants D-20 can express
(``cited_iris: list[str] = Field(min_length=1)`` — no empty citation list);
this module enforces the cross-shard invariants that need the ShardStore to
resolve:

  * **D-20 cite-resolvable** — every IRI in ``cited_iris`` MUST resolve to an
    existing shard in the corpus AND MUST NOT equal the shard being promoted
    (no self-citation). The first protects against dangling citations; the
    second against a reviewer "supporting" a promotion by citing the very
    shard being promoted.

  * **D-21 status-kind cross-check** — the cited shard's authority kind must
    be commensurate with the promotion target:

      * ``authority_only`` — at least one cited shard must be a
        ``ConflictingAuthoritiesShard`` (the closest Phase 2/3 analog to the
        plan's ``AuthorityShard``; see 07-04b SUMMARY deviation note) OR
        carry envelope ``epistemic_status == "authority_only"`` itself.
      * ``demonstrable`` — at least one cited shard must carry envelope
        ``epistemic_status`` in
        {``demonstrable``, ``per_se_nota_quoad_se``,
         ``per_se_nota_quoad_nos``, ``authority_only``} (a stronger-or-equal
        epistemic basis).
      * ``per_se_nota_quoad_nos`` — no citation depth check (self-evident-to-us
        is axiomatic; the D-20 resolvability guard upstream remains in force).

D-04 boundary: stdlib + Pydantic + ShardStore Protocol import only. NO
aiosqlite / rdflib / pyoxigraph imports (this is a library-layer validator;
the SHACL belt for D-20/D-21 lives in ``shape_validation.py`` — the lone
exempt module).

Phase 6 seam: ``governance/cli/promote.py`` calls ``sign_attestation`` on the
output of ``signature_payload()`` AFTER this validator passes; ``log.append``
runs the SHACL belt as the third defense-in-depth layer.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from folio_insights.governance.events import PromotionEvent

if TYPE_CHECKING:
    from folio_insights.revision.store import ShardStore


# ── D-21 per-status epistemic-status table ──
#
# For ``demonstrable``: a stronger-or-equal epistemic basis is required from
# at least one cited shard. The four "stronger-or-equal" values cover
# axiomatic (per_se_nota_*), demonstrable (the same tier), and authority_only
# (lateral — an authority of equivalent legal force).
_DEMONSTRABLE_OR_STRONGER: frozenset[str] = frozenset(
    {
        "demonstrable",
        "per_se_nota_quoad_se",
        "per_se_nota_quoad_nos",
        "authority_only",
    }
)


# Per-class predicates for D-21 ``authority_only``. The plan references an
# ``AuthorityShard`` subtype that does not exist in Phase 2; the closest match
# is ``ConflictingAuthoritiesShard`` (the sic-et-non authority-conflict shard).
# We accept either that class OR an envelope-level ``epistemic_status ==
# "authority_only"`` as proof of authority-kind backing.
_AUTHORITY_CLASS_NAMES: frozenset[str] = frozenset(
    {
        "ConflictingAuthoritiesShard",
    }
)


async def validate_promotion(
    event: PromotionEvent,
    *,
    store: "ShardStore",
) -> None:
    """Validate a ``PromotionEvent`` against D-20 + D-21 (07-04b).

    D-20 cite-resolvable: every IRI in ``event.cited_iris`` MUST resolve in
    ``store`` (no dangling citations) AND MUST NOT equal ``event.shard_iri``
    (no self-citation).

    D-21 status-kind cross-check: the cited shards must be commensurate with
    ``event.new_status`` per the per-status table documented at module top.

    Raises ``ValueError`` with a diagnostic message naming the violation kind
    on any failure. Pure-validation discipline: this function NEVER mutates
    the store and NEVER appends to the log.
    """
    # ── D-20: cite-resolvable + non-self-citation ──
    cited_shards = []
    for iri in event.cited_iris:
        if iri == event.shard_iri:
            raise ValueError(
                f"D-20 self-citation refused: cited_iris contains the shard "
                f"being promoted ({iri!r}). A promotion cannot cite itself."
            )
        cited = await store.get(iri)
        if cited is None:
            raise ValueError(
                f"D-20 unresolvable citation: {iri!r} is not in the ShardStore. "
                f"Every cited IRI must resolve to an existing shard."
            )
        cited_shards.append(cited)

    # ── D-21: per-status epistemic-kind cross-check ──
    status = event.new_status
    if status == "per_se_nota_quoad_nos":
        # Axiomatic — no citation depth check. The D-20 resolvability guard
        # above already ran.
        return

    if status == "authority_only":
        ok = any(
            cited.__class__.__name__ in _AUTHORITY_CLASS_NAMES
            or cited.epistemic_status == "authority_only"
            for cited in cited_shards
        )
        if not ok:
            raise ValueError(
                "D-21 status-kind mismatch: authority_only requires at least "
                "one cited shard to be a ConflictingAuthoritiesShard (the "
                "Phase 2/3 authority-class analog) or to carry envelope "
                "epistemic_status == 'authority_only'. None of the cited "
                "shards satisfy this constraint."
            )
        return

    if status == "demonstrable":
        ok = any(
            cited.epistemic_status in _DEMONSTRABLE_OR_STRONGER
            for cited in cited_shards
        )
        if not ok:
            raise ValueError(
                "D-21 status-kind mismatch: demonstrable requires at least "
                "one cited shard with epistemic_status in "
                f"{sorted(_DEMONSTRABLE_OR_STRONGER)}. None of the cited "
                "shards reach the demonstrable-or-stronger tier."
            )
        return

    # Unknown status — Pydantic Literal narrowing should have refused
    # construction, but defensively surface here.
    raise ValueError(
        f"D-21 unknown promotion status: {status!r} (expected one of "
        "per_se_nota_quoad_nos / demonstrable / authority_only)."
    )


__all__ = ["PromotionEvent", "validate_promotion"]
