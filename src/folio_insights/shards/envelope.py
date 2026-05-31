"""Phase 2 v2.0 Shard envelope (PRD §6.1) — 15-field Pydantic core data model.

Round-trip + frozen identity contract for every downstream phase (3-16). The
15 envelope fields + 6 identity-and-origin fields + bitemporal triplet +
supersession link pair + contest state are locked here; subtype-specific
fields land in Phase 3.

Key locked decisions carried into this module (see 02-CONTEXT.md):

* D-03: `valid_time_start` and `valid_time_end` are `datetime | None = None`.
  Null means unbounded (Phase 13 SPARQL `--as-of` treats `null_start` as −∞
  and `null_end` as +∞).
* D-04 / D-12: `transaction_time` uses `Field(default_factory=lambda:
  datetime.now(UTC))` — tz-aware UTC on every instance.
* D-05: `ShardType` Literal is the canonical discriminator alias; subtypes
  pin each Literal default in `subtypes.py`.
* D-07: The 6 identity-and-origin fields (`shard_iri`, `provenance_hash`,
  `source_uri`, `source_span`, `extracted_at`, `first_extractor_did`) use
  per-field freeze via ``Field(frozen=...)``. Pydantic 2.7+ raises
  ``ValidationError`` with ``type="frozen_field"`` on assignment. Mutable
  fields stay assignable.
* D-08: Mutable-with-audit fields append a `ContentEdit` to `content_edits`
  on every change (helper + model land in Plan 02-02; Phase 5 wires the
  forward-only SHACL gate).
* D-10: `from __future__ import annotations` at module top.
* D-11: `Field(default_factory=list)` on every mutable list default.

This module is pure-Pydantic + stdlib: no storage-layer libraries are
pulled in at Phase 2. RDF mapping + SHACL gates are Phase 11 / Phase 13
scope.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ── Phase 8 D-02 / D-03 vocab pin ──────────────────────────────────────────
#
# VOCAB_VERSION is the source-of-truth FOLIO Insights v2.0 vocabulary version
# constant, owned by ``folio_insights.vocab`` (Plan 08-01).
from folio_insights.vocab import VOCAB_VERSION

# D-05: canonical discriminator alias (5 values, ordered per CONTEXT D-05).
ShardType = Literal[
    "simple_assertion",
    "disputed_proposition",
    "conflicting_authorities",
    "gloss",
    "hypothesis",
]


# ── Phase 6 SignedAction vocabulary (D-13, DID-02, PRD §3.1) ───────────────
#
# The canonical set of action strings an AttestedSignature may carry. Spellings
# are RECONCILED against the PRD §3.1 source of truth (L220-230 of
# PRD-v2.0-draft-2.md, in the §6.1 AttestedSignature definition block):
#
#   * PRD §3.1.2 L117 — ``action="promote"`` (HypothesisShard → attested)
#   * PRD §3.1.3 L125 — ``action="resolve_contest"`` (arbiter resolution)
#   * PRD §3.1   L103 — reviewer role: "edit content on any shard" (the
#                       ``content_edit`` action is a real, audited reviewer act —
#                       Phase 5's ``add_edit`` / ``sign_attestation`` paths
#                       already construct ``AttestedSignature(action="content_edit",
#                       …)`` and the unsigned stub records it honestly).
#
# Reconciliation with REQUIREMENTS DID-02 (the 8 governance actions: extract,
# promote, demote, contest, supersede, retract, distinguo, role-assertion):
#
#   * Spellings the PRD/code already use (PRD §3.1 / §6.1 L220-230):
#       extract, promote, demote, contest, resolve_contest, distinguo,
#       supersede, content_edit, reparent, reconcile
#   * DID-02 additions not yet present in PRD §3.1 vocabulary:
#       retract            — "retraction cascade" verb (PRD §3.1.4 L131,
#                            "retraction cascade fires") + REQUIREMENTS DID-02
#       role_assertion     — "issue role assertions" (PRD §3.1 L105, corpus_admin
#                            role); DID-02 spelling is "role-assertion" but
#                            Python identifiers and PRD code style use snake_case
#                            (e.g. test name ``test_role_assertion_signed.py``
#                            at PRD L146). We pick the snake_case spelling.
#
# DID-07 acceptance criterion ("preview for all 8 signed-action types") is
# satisfied by the **governance subset** of this Literal, not the full set —
# Plan 03 iterates `{extract, promote, demote, contest, supersede, retract,
# distinguo, role_assertion}` for the CLI preview. ``content_edit``,
# ``reparent``, ``reconcile`` are present-but-not-subject-to-DID-07 — they
# keep Phase-5 construction sites green without muddying EC5 (option A,
# 06-RESEARCH §9 + Open Question 1 resolution).
SignedAction = Literal[
    # 8 governance actions (DID-02 / DID-07 preview subset):
    "extract",            # first extraction (PRD §3.1 row "extractor")
    "promote",            # hypothesis → attested (PRD §3.1.2 L117)
    "demote",             # attested → hypothesis (PRD §3.1.3 L121)
    "contest",            # marked contested (PRD §3.1.3 L123)
    "supersede",          # asserted a superseding shard (PRD §3.1 / §6.4)
    "retract",            # retraction cascade (PRD §3.1.4 L131; DID-02)
    "distinguo",          # proposed/confirmed a sense-fork (PRD §6.1 L225)
    "role_assertion",     # issued a role assertion (PRD §3.1 L105; DID-02)
    # Reviewer/governance actions present in PRD §3.1 / §6.1 vocabulary
    # but OUTSIDE the DID-07 8-action preview subset:
    "content_edit",       # mutable content was edited (PRD §6.1 L223;
                          #   Phase 5 ``add_edit`` / ``sign_attestation``)
    "reparent",           # relationships changed (PRD §6.1 L224)
    "reconcile",          # set reconciliation_strategy (PRD §6.1 L226)
    "resolve_contest",    # governance-resolved a contested state
                          #   (PRD §3.1.3 L125)
    # ── Phase 7 D-13 extension (12 → 13) — append at end for positional stability ──
    "role_revocation",    # revoke a previously-asserted role (Phase 7 GOV-01 /
                          #   PRD §3.1; structurally distinct from role_assertion
                          #   to close F6 — see governance/events.py
                          #   RoleRevocationEvent).
]


class AttestedSignature(BaseModel):
    """Phase 6.1 DID-signed reviewer attestation (D-13, PRD §6.5).

    REPLACES the permissive Phase 2 stub (was ``extra="allow"``). Every
    reviewer write action is cryptographically signed by the reviewer's DID;
    downstream systems weigh signatures as they see fit (PRD §16 R5,
    §21.10).

    Phase 6.1 shape (D-13 — single breaking reshape; the ``cosigners[]`` slot
    is reserved present-but-empty so the deferred 6.3 N-of-M multi-sig adds
    behavior without re-breaking the schema):

    * ``model_config = ConfigDict(extra="forbid")`` — unknown fields raise
      (T-06-03 integrity gate).
    * ``did`` — the signer DID (e.g., ``did:web:example.org``, ``did:key:z…``).
    * ``action`` — a ``SignedAction`` Literal reconciled against PRD §3.1 (see
      the ``SignedAction`` docstring above). Default is ``"content_edit"`` so
      the Phase-5 unsigned audit-stub paths (``add_edit``, ``sign_attestation``)
      continue to construct.
    * ``signed_at`` — wall-clock at signing (UTC, tz-aware).
    * ``signature`` — base58-encoded ed25519 signature over the JCS-canonical
      ``over_content_hash`` (Plan 02 wires real signing). Empty string in the
      Phase-5 unsigned stub path is HONESTLY unsigned (never reads as
      "verified" — see ``verified`` below).
    * ``over_content_hash`` — SHA-256 hex of the JCS-canonical content the
      signature covers (the value returned by
      ``revision.content_edit.canonical_content_hash``).
    * ``signing_key_id`` — DID URL + ``#fragment`` of the verificationMethod
      that produced ``signature`` (DID-04 / SEC-05). Defaults to ``""`` so the
      Phase-5 unsigned stub still constructs; Plan 02 populates it.
    * ``did_doc_snapshot_at`` — the wall-clock at which the signer's DID
      document was resolved/snapshotted, so verification resolves the
      **signing-time** key — not the DID's current key — surviving key
      rotation (DID-04 / SEC-05 / Pitfall F2).
    * ``verified`` — cache annotation; ``None`` until the verifier runs and
      sets ``True``/``False``. Defaulting to ``None`` (NOT ``True``) is the
      T-06-03 anti-spoofing guarantee: an unverified signature can never read
      as verified.
    * ``cosigners`` — RESERVED, present-but-empty list of co-signing
      ``AttestedSignature``s for the deferred 6.3 N-of-M multi-sig (D-13).
      Present here in 6.1 so 6.3 adds behavior without a second breaking
      reshape. Self-referential — Pydantic 2 resolves the forward ref via
      ``model_rebuild()`` at module bottom (mirrors ``ShardEnvelope`` /
      ``ContentEdit``).
    """
    model_config = ConfigDict(extra="forbid")

    did: str = ""
    action: SignedAction = "content_edit"
    signed_at: Optional[datetime] = None
    signature: str = ""
    over_content_hash: str = ""
    # ── Phase 6.1 additions (D-13) ──
    signing_key_id: str = ""
    did_doc_snapshot_at: Optional[datetime] = None
    verified: Optional[bool] = None
    cosigners: list["AttestedSignature"] = Field(default_factory=list)


class Triple(BaseModel):
    """Fregean function-argument triple (PRD §6.1 field 1).

    The v2.0 Shard envelope is built around the Fregean sense/reference pair
    (`sense`, `reference`) + the subject/predicate/object function-argument
    triple. `object_datatype` is optional so typed literals (xsd:dateTime,
    xsd:decimal) can be distinguished from plain IRIs at Phase 11 / Phase 13.
    """
    model_config = ConfigDict(extra="forbid")

    subject: str
    predicate: str
    object: str
    object_datatype: Optional[str] = None


class ShardEnvelope(BaseModel):
    """15-field v2.0 Shard envelope (PRD §6.1).

    The 6 identity-and-origin fields use per-field freeze via
    ``Field(frozen=...)`` (D-07); mutable fields allow in-place assignment
    but every change SHOULD append a ``ContentEdit`` (D-08 — audit record
    + helper land in Plan 02-02). Phase 2 ships the shape + round-trip;
    Phase 5 wires the forward-only SHACL gate over ``content_edits``;
    Phase 11 adds SHACL hybrid validation; Phase 13 serializes to RDF-12.
    """

    # Schema drift at Phase 3 / 5 / 7 consumer boundaries raises pydantic
    # ValidationError rather than silently accepting unknown fields.
    model_config = ConfigDict(extra="forbid")

    # ── IMMUTABLE identity + origin (D-07) — 6 per-field-immutable fields ──
    shard_iri: str = Field(frozen=True)
    provenance_hash: str = Field(frozen=True)
    source_uri: str = Field(frozen=True)
    source_span: str = Field(frozen=True)
    extracted_at: datetime = Field(frozen=True)
    first_extractor_did: str = Field(frozen=True)

    # ── Discriminator (D-05 / D-06 — pinned by each subtype's Literal default) ──
    shard_type: ShardType

    # ── 15 envelope fields (PRD §6.1) ──
    # 1. Fregean function-argument triple.
    triple: Triple
    # 2. Tractarian elaboration edges (list of shard IRIs this shard refines).
    elaborates: list[str] = Field(default_factory=list)
    # 3. Sense / reference pair.
    sense: str
    reference: str
    # 4. Logical form imputed by the extractor.
    #    `source_uri` + `source_span` are declared above (both frozen).
    logical_form_imputed: str
    # 5. Carnapian layer tag.
    layer: Literal[
        "L0_primitive",
        "L1_definitional",
        "L2_composed",
        "L3_jurisdictional",
    ]
    # 6. `shard_type` discriminator already declared above (fills PRD slot 6).
    # 7. Aristotelian predication mode.
    predication_mode: Literal["per_se", "per_accidens"]
    # 8. Hume-fork tag.
    fork: Literal[
        "analytic",
        "synthetic_a_posteriori",
        "synthetic_a_priori",
    ]
    # 9. Epistemic status (Aquinas + crowdsourced extensions).
    epistemic_status: Literal[
        "per_se_nota_quoad_se",
        "per_se_nota_quoad_nos",
        "demonstrable",
        "authority_only",
        "aporetic",
        "hypothesis",
        "contested",
        "superseded",
    ]
    # 10. Vienna Circle verification method.
    verification_method: Literal[
        "textual_citation",
        "definitional_derivation",
        "inferential_chain",
        "extractor_assertion",
        "reviewer_attested",
    ]
    # 11. Explicit dependencies (Spinoza + Quine).
    depends_on_axioms: list[str] = Field(default_factory=list)
    depends_on_definitions: list[str] = Field(default_factory=list)
    depends_on_precedents: list[str] = Field(default_factory=list)
    depends_on_shards: list[str] = Field(default_factory=list)
    # 12. Framework identifier (Carnap) — NOT year-versioned (PRD §6.1 L343-346).
    framework_id: str
    # 13. Speech-act / language-game context (Wittgenstein II).
    speech_act: Literal[
        "holding",
        "dictum",
        "statutory_text",
        "statutory_definition",
        "regulatory_text",
        "pleading_argument",
        "contract_term",
        "treatise_statement",
        "restatement_black_letter",
        "practitioner_advice",
        "administrative_interpretation",
    ]
    # 14. Provenance metadata — DID-anchored.
    extractor_version: str
    extraction_prompt_hash: str
    extractor_model: str
    signatures: list[AttestedSignature] = Field(default_factory=list)
    # ``content_edits`` points at ``ContentEdit``, which ships in Plan 02-02
    # (shards/audit.py). A forward string-ref is used here to avoid a circular
    # import at module load; Plan 02-02's audit.py calls
    # ``ShardEnvelope.model_rebuild()`` at its module bottom to wire the ref.
    content_edits: list["ContentEdit"] = Field(default_factory=list)  # noqa: F821
    confidence: float = Field(ge=0.0, le=1.0)
    # 15. BFO mini-classification.
    bfo_category: Literal[
        "continuant_independent",
        "continuant_dependent",
        "occurrent_process",
        "occurrent_event",
    ]

    # ── BITEMPORAL (SHARD-10, D-03, D-04, D-12) ──
    valid_time_start: datetime | None = None
    valid_time_end: datetime | None = None
    transaction_time: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )

    # ── Phase 8 D-03 vocab pin (Plan 08-02) — Pydantic belt of D-04 two-belt ──
    # The default_factory pins the field to the module constant ``VOCAB_VERSION``
    # so every existing Phase 2-7 fixture auto-inherits the pin. The SHACL belt
    # (``fi:VocabPinShape``) lives in ``src/folio_insights/vocab/shapes.ttl`` and
    # ships in Plan 08-01.
    vocab_version: str = Field(
        default_factory=lambda: VOCAB_VERSION,
        description=(
            "Phase 8 D-03 vocab pin — Pydantic belt of the two-belt D-04 "
            "enforcement; SHACL belt lives in "
            "src/folio_insights/vocab/shapes.ttl::fi:VocabPinShape."
        ),
    )

    # ── SUPERSESSION (link pair — chain enforcement lands in Phase 5 / 7) ──
    supersedes: str | None = None
    superseded_by: str | None = None

    # ── CONTEST STATE (first-class per PRD §6.1 field 9 extension) ──
    contested: bool = False
    contest_votes: dict[str, str] = Field(default_factory=dict)

    # ── Phase 8 D-03 vocab pin validator (Plan 08-02) ─────────────────────
    #
    # NOTE: This is the FIRST ``@field_validator`` in the codebase. The
    # established "refuse-mismatched-value" idiom elsewhere is
    # ``@model_validator(mode="after")`` (see ``envelope.py:_content_edits_forward_only``
    # below and ``shards/subtypes.py:_disputed_invariants`` at line 105). Both
    # primitives yield identical behavior for this single-field check; D-03
    # calls for ``field_validator`` verbatim because it is the narrower fit
    # (single-field validation) and aligns with the per-field framing of D-04
    # ("the field's value must equal the module constant"). Future single-field
    # "refuse-mismatched-value" gates should prefer ``field_validator``; the
    # existing ``model_validator`` precedents stay because they assert
    # cross-field invariants that ``field_validator`` cannot express.
    @field_validator("vocab_version")
    @classmethod
    def _check_vocab_pin(cls, v: str) -> str:
        """D-03 / D-04: refuse any vocab_version != VOCAB_VERSION module constant."""
        if v != VOCAB_VERSION:
            raise ValueError(
                f"vocab_version must equal module constant {VOCAB_VERSION!r}; "
                f"got {v!r} (Phase 8 D-03 / D-04 two-belt enforcement)."
            )
        return v

    @model_validator(mode="after")
    def _content_edits_forward_only(self) -> "ShardEnvelope":
        """AUTHORITATIVE forward-only gate over ``content_edits`` (D-07.1, D-08b).

        The ``content_edits`` chain must be monotonic in ``edited_at``: no edit
        may be back-dated before its predecessor (a back-dated insert is an
        "edit to a past version"). Equal adjacent timestamps are ALLOWED — a tie
        is broken by append order (D-09), so only a *strictly* decreasing
        ``edited_at`` is a violation.

        This is the authoritative, always-on monotonicity gate (mirrors the
        ``shards/subtypes.py`` ``@model_validator(mode="after")`` idiom). The
        pyshacl forward-only shape (Plan 03, ``revision/``) is *defense-in-depth*
        over the same invariant — it cannot live here because ``shards/`` is kept
        RDF-free (``tests/shards/test_dep_leak_guard.py``).

        The OTHER half of D-08 — immutability of past entries (D-08a: no mutation
        or deletion of an existing ``ContentEdit``) — is NOT carried by this
        validator. A SHACL shape / Pydantic validator sees only a single snapshot
        and cannot detect a deletion (RESEARCH L115-124). That half is carried
        structurally by ``ContentEdit`` ``frozen=True`` (an entry can't be mutated
        in place) plus the Plan 02 ``IMMUTABLE_FIELD_PATHS`` gate listing
        ``content_edits`` as a whole (append-only — reorder/remove/replace
        forbidden).
        """
        edits = self.content_edits
        for prev, curr in zip(edits, edits[1:]):
            if curr.edited_at < prev.edited_at:
                raise ValueError(
                    "content_edits must be monotonic in edited_at "
                    "(no back-dated insert — forward-only, D-08b); "
                    f"got edit at {curr.edited_at!r} after {prev.edited_at!r}."
                )
        return self


# Resolve the AttestedSignature.cosigners self-reference (D-13). With
# `from __future__ import annotations`, the `list["AttestedSignature"]`
# annotation is a forward string-ref at class-body evaluation; calling
# model_rebuild() now (after the class exists in module namespace) wires the
# real type so list items validate as AttestedSignature instances rather than
# bare dicts. Mirrors the audit.py ShardEnvelope.model_rebuild() pattern.
AttestedSignature.model_rebuild()


__all__ = [
    "AttestedSignature",
    "ShardEnvelope",
    "ShardType",
    "SignedAction",
    "Triple",
]
