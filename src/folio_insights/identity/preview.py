"""DID-07 "what will I be signing?" preview — canonical hash + human-readable diff.

Exit Criterion 5 (PRD §6.5 / 06-CONTEXT D-domain): the operator-facing CLI
preview MUST render for **all 8 signed-action types** in the DID-07
governance subset before the operator commits a signature. This module is
the CLI/API form of that preview; the styled web preview defers (D-02, post-
Phase-14).

The 8-action **governance subset** (DID-02 / DID-07; reconciled in Plan-01's
``SignedAction`` Literal): extract, promote, demote, contest, supersede,
retract, distinguo, role_assertion. The renderer dispatch covers each by a
single per-action ``_render_*`` function so adding/removing an action is a
single switch.

Note (06-CONTEXT D-13 / OQ1): the ``SignedAction`` Literal also carries 4
additional reviewer/governance verbs that exist in PRD §3.1 / §6.1
vocabulary but live OUTSIDE the DID-07 8-action subset — ``content_edit``,
``reparent``, ``reconcile``, ``resolve_contest``. ``build_signing_preview``
accepts ALL Literal members (so the audit-path stub still works) — only the
EC5 test parametrizes over the 8-action subset.

What the preview shows:

* ``content_hash`` — the canonical JCS hash from
  ``revision.content_edit.canonical_content_hash``. That is the EXACT value
  the signer signs over (``signer.sign_attestation`` signs the hex string's
  UTF-8 bytes), so the preview shows the operator the *signed-payload*
  binding, not a re-hash they have to trust.
* ``human_readable`` — a per-action one/few-line description of the state
  transition the signature attests to. For edit-shaped actions, an old →
  new field diff; for governance actions, the kind of attestation being
  recorded (the operator can spot a wrong-shard or wrong-action mistake
  BEFORE the keystroke).

The preview is structured (a Pydantic model with ``extra="forbid"``) so the
deferred web phase can render the SAME data through a styled component
without re-deriving anything — and so a CliRunner test can assert structure
without parsing prose.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from folio_insights.revision.content_edit import canonical_content_hash
from folio_insights.shards.envelope import ShardEnvelope, SignedAction


# ── The DID-07 8-action governance subset (EC5) ─────────────────────────────


GOVERNANCE_ACTIONS: tuple[SignedAction, ...] = (
    "extract",
    "promote",
    "demote",
    "contest",
    "supersede",
    "retract",
    "distinguo",
    "role_assertion",
)
"""The 8 signed-action types DID-07 / EC5 requires preview for.

Locked here so the test parametrization and the CLI's ``preview`` /
``sign --action`` choices stay in sync with one canonical list. The full
``SignedAction`` Literal carries 4 additional reviewer verbs
(``content_edit``, ``reparent``, ``reconcile``, ``resolve_contest``) —
``build_signing_preview`` handles them too (so the audit-stub paths still
work), but they're not subject to the DID-07 8-action exit criterion.
"""


# ── SigningPreview model — the structured preview output ────────────────────


class SigningPreview(BaseModel):
    """Structured ``what will I be signing?`` preview (DID-07 / EC5).

    Pure-data; the CLI ``did preview`` / ``did sign`` commands stringify
    this for terminal output. The deferred web phase will render the SAME
    fields through a styled component without re-deriving them.

    * ``action`` — the SignedAction the signature will carry.
    * ``content_hash`` — the canonical JCS hash from
      ``canonical_content_hash``. The signer signs the hex string's UTF-8
      bytes (signer.py); showing it here means the operator sees EXACTLY
      what their key is about to bind.
    * ``shard_iri`` — the IRI of the shard the signature targets (echoed
      for the operator's sanity, since a wrong-shard signature is the most
      common F1-class mistake).
    * ``human_readable`` — per-action one/few-line description of the
      state transition the signature attests to.
    """

    model_config = ConfigDict(extra="forbid")

    action: SignedAction
    content_hash: str
    shard_iri: str
    human_readable: str = Field(min_length=1)


# ── per-action renderers ────────────────────────────────────────────────────
#
# Each renderer takes the shard + an optional `change` dict carrying the
# action-shaped state transition (e.g. for `promote`: {"from": "hypothesis",
# "to": "demonstrable"}; for `content_edit`: {"field_path": "sense",
# "old": "...", "new": "..."}).  The renderer returns a plain-text line the
# CLI can print directly.  The renderer dispatch (`_RENDERERS`) is keyed by
# the SignedAction Literal so adding/removing an action is one entry.


def _render_extract(shard: ShardEnvelope, change: Optional[dict[str, Any]]) -> str:
    """First-extraction signature: the extractor attests the shard's content."""
    return (
        f"EXTRACT {shard.shard_iri}: attest first-extraction of "
        f"sense={shard.sense!r} from source={shard.source_uri!r} "
        f"span={shard.source_span!r}."
    )


def _render_promote(shard: ShardEnvelope, change: Optional[dict[str, Any]]) -> str:
    """Promote (hypothesis → attested): attest the epistemic_status transition."""
    new_status = (change or {}).get("to") or "demonstrable"
    return (
        f"PROMOTE {shard.shard_iri}: epistemic_status "
        f"{shard.epistemic_status!r} -> {new_status!r}."
    )


def _render_demote(shard: ShardEnvelope, change: Optional[dict[str, Any]]) -> str:
    """Demote (attested → hypothesis): attest the epistemic_status transition."""
    new_status = (change or {}).get("to") or "hypothesis"
    return (
        f"DEMOTE {shard.shard_iri}: epistemic_status "
        f"{shard.epistemic_status!r} -> {new_status!r}."
    )


def _render_contest(shard: ShardEnvelope, change: Optional[dict[str, Any]]) -> str:
    """Contest: attest a contested-state mark with the contesting position."""
    position = (change or {}).get("position") or "<position not given>"
    return (
        f"CONTEST {shard.shard_iri}: mark contested with position={position!r} "
        f"(current contested={shard.contested!r})."
    )


def _render_supersede(shard: ShardEnvelope, change: Optional[dict[str, Any]]) -> str:
    """Supersede: attest that the shard is superseded by a newer shard."""
    by = (change or {}).get("superseded_by") or "<new shard iri not given>"
    return (
        f"SUPERSEDE {shard.shard_iri}: attest superseded_by={by!r} "
        f"(current superseded_by={shard.superseded_by!r})."
    )


def _render_retract(shard: ShardEnvelope, change: Optional[dict[str, Any]]) -> str:
    """Retract: attest a retraction (and the cascade it implies)."""
    reason = (change or {}).get("reason") or "<reason not given>"
    return (
        f"RETRACT {shard.shard_iri}: attest retraction (cascade will fire); "
        f"reason={reason!r}."
    )


def _render_distinguo(shard: ShardEnvelope, change: Optional[dict[str, Any]]) -> str:
    """Distinguo: attest a sense-fork (one term, two senses)."""
    fork_into = (change or {}).get("fork_into") or "<new sense iri not given>"
    return (
        f"DISTINGUO {shard.shard_iri}: attest sense-fork "
        f"{shard.reference!r} -> {fork_into!r}."
    )


def _render_role_assertion(
    shard: ShardEnvelope, change: Optional[dict[str, Any]]
) -> str:
    """Role assertion: attest a role grant (extractor / reviewer / arbiter / corpus_admin)."""
    role = (change or {}).get("role") or "<role not given>"
    did = (change or {}).get("did") or "<did not given>"
    return (
        f"ROLE_ASSERTION {shard.shard_iri}: attest role={role!r} "
        f"for did={did!r}."
    )


# ── 4 OUTSIDE-EC5 action renderers (still need to work for callers) ─────────


def _render_content_edit(
    shard: ShardEnvelope, change: Optional[dict[str, Any]]
) -> str:
    """Content edit: show field_path: old -> new (the audit-record diff)."""
    field_path = (change or {}).get("field_path") or "<field_path not given>"
    old = (change or {}).get("old", "<unspecified>")
    new = (change or {}).get("new", "<unspecified>")
    return (
        f"CONTENT_EDIT {shard.shard_iri}: {field_path}: {old!r} -> {new!r}."
    )


def _render_reparent(shard: ShardEnvelope, change: Optional[dict[str, Any]]) -> str:
    """Reparent: attest a triple.object change (re-parenting; PRD §6.4)."""
    new_obj = (change or {}).get("new") or "<new object not given>"
    return (
        f"REPARENT {shard.shard_iri}: triple.object "
        f"{shard.triple.object!r} -> {new_obj!r}."
    )


def _render_reconcile(
    shard: ShardEnvelope, change: Optional[dict[str, Any]]
) -> str:
    """Reconcile: attest a reconciliation_strategy choice (conflicting-authorities)."""
    strategy = (change or {}).get("strategy") or "<strategy not given>"
    return (
        f"RECONCILE {shard.shard_iri}: reconciliation_strategy -> {strategy!r}."
    )


def _render_resolve_contest(
    shard: ShardEnvelope, change: Optional[dict[str, Any]]
) -> str:
    """Resolve a contested state: arbiter attests a resolution."""
    resolution = (change or {}).get("resolution") or "<resolution not given>"
    return (
        f"RESOLVE_CONTEST {shard.shard_iri}: resolve contested state "
        f"with resolution={resolution!r}."
    )


# ── renderer dispatch (one entry per SignedAction Literal value) ────────────


_RENDERERS: dict[str, Any] = {
    # 8-action DID-07 governance subset (EC5):
    "extract": _render_extract,
    "promote": _render_promote,
    "demote": _render_demote,
    "contest": _render_contest,
    "supersede": _render_supersede,
    "retract": _render_retract,
    "distinguo": _render_distinguo,
    "role_assertion": _render_role_assertion,
    # 4 PRD-vocab actions outside the EC5 subset:
    "content_edit": _render_content_edit,
    "reparent": _render_reparent,
    "reconcile": _render_reconcile,
    "resolve_contest": _render_resolve_contest,
}


# ── public entry point — build_signing_preview ──────────────────────────────


def build_signing_preview(
    action: SignedAction,
    shard: ShardEnvelope,
    *,
    change: Optional[dict[str, Any]] = None,
) -> SigningPreview:
    """Render a preview of what the signer will be signing (DID-07 / EC5).

    Drives the per-action renderer off the ``SignedAction`` Literal value
    and pairs it with the canonical JCS content hash the signer will sign
    over. The hash is computed via ``revision.content_edit.canonical_content_hash``
    — the SAME function ``signer.sign_attestation`` signs against — so the
    preview shows the operator EXACTLY what their key will bind.

    The renderer switch covers EVERY ``SignedAction`` Literal value (the 8
    DID-07 governance actions + the 4 PRD-vocab reviewer/governance verbs).
    Adding a new action is a single ``_RENDERERS`` entry; an unhandled value
    raises ``ValueError`` (defensive — the Literal narrows the type but the
    runtime still gets a string).

    ``change`` is the optional per-action transition descriptor (e.g.
    ``{"from": "hypothesis", "to": "demonstrable"}`` for promote;
    ``{"field_path": "sense", "old": "...", "new": "..."}`` for
    content_edit). When omitted the renderers fall back to placeholders so
    the preview still surfaces SOMETHING (the operator sees the slot is
    empty BEFORE keystroke).
    """
    renderer = _RENDERERS.get(action)
    if renderer is None:
        raise ValueError(
            f"No preview renderer for action={action!r}; expected one of "
            f"{sorted(_RENDERERS)}."
        )
    human_readable = renderer(shard, change)
    content_hash = canonical_content_hash(shard)
    return SigningPreview(
        action=action,
        content_hash=content_hash,
        shard_iri=shard.shard_iri,
        human_readable=human_readable,
    )


__all__ = [
    "GOVERNANCE_ACTIONS",
    "SigningPreview",
    "build_signing_preview",
]
