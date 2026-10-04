"""Deterministic dedupe (governance plan U2, Stage B1).

Cheap, reproducible label matching, so the human or model judge only sees
real survivors. Pure: it reads a folded ``ProposalRegistry`` and returns the
judgment changes for ``ProposalStore`` to append. It never mutates state.

Verdicts:

* ``DUPLICATE_OF`` + ``target_iri``: the normalized label equals the primary
  (``rdfs:label``) label of a FOLIO concept.
* ``ALIAS_CANDIDATE`` + ``target_iri`` + guardrail
  ``alias-hit-verify-definition``: the label equals only a non-primary
  form (pref, alt, hidden). The proposal stays distinct and stays in the
  worklist, because a label collision can join semantically unrelated
  concepts. Only a definition-level judgment may call it a duplicate.
* ``MERGE_WITH`` + ``target_proposal_id``: its plural stem collides with an
  earlier-collected proposal (the first collected is canonical).

Rules:

* A judgment recorded by anything other than ``deterministic`` (a human or
  model judgment) is never overwritten or cleared by dedupe.
* A deterministic judgment that no longer applies (the lexicon changed, for
  instance) is cleared, and the ledger keeps the earlier record.
* Re-running against unchanged state yields no changes.
"""
from __future__ import annotations

from typing import Any

from folio_insights.proposals.lexicon import PRIMARY, FolioLexicon
from folio_insights.proposals.registry import (
    DETERMINISTIC,
    Proposal,
    ProposalRegistry,
    judgment_core,
    stem_label,
)

ALIAS_GUARDRAIL = "alias-hit-verify-definition"
VERDICT_DUPLICATE = "DUPLICATE_OF"
VERDICT_ALIAS = "ALIAS_CANDIDATE"
VERDICT_MERGE = "MERGE_WITH"


def is_preserved(proposal: Proposal) -> bool:
    """True when the current judgment came from a human or model judge."""
    j = proposal.judgment
    return j is not None and j.get("judged_by") != DETERMINISTIC


class DeterministicDeduper:
    def __init__(self, lexicon: FolioLexicon) -> None:
        self.lex = lexicon

    def judge(self, proposal: Proposal, canonical_by_stem: dict[str, str]) -> dict[str, Any] | None:
        """The deterministic judgment for ``proposal``, or ``None`` (survivor)."""
        norm = proposal.normalized_label
        hits = self.lex.lookup(norm)
        if hits:
            primary = sorted(h for h in hits if h[2] == PRIMARY)
            iri, label, form = primary[0] if primary else sorted(hits)[0]
            nearest = [{"iri": iri, "label": label, "match_form": form, "score": None}]
            if form == PRIMARY:
                return {
                    "verdict": VERDICT_DUPLICATE,
                    "target_iri": iri,
                    "target_proposal_id": None,
                    "nearest": nearest,
                    "reasoning": (
                        "The normalized label equals the primary label of the FOLIO "
                        "concept target_iri."
                    ),
                    "judged_by": DETERMINISTIC,
                }
            return {
                "verdict": VERDICT_ALIAS,
                "target_iri": iri,
                "target_proposal_id": None,
                "nearest": nearest,
                "reasoning": (
                    f"The normalized label equals only a {form} label of the FOLIO "
                    "concept target_iri. An alias collision is not a duplicate until "
                    "the definitions are compared."
                ),
                "guardrail": ALIAS_GUARDRAIL,
                "judged_by": DETERMINISTIC,
            }
        canonical = canonical_by_stem.get(stem_label(norm))
        if canonical and canonical != proposal.proposal_id:
            return {
                "verdict": VERDICT_MERGE,
                "target_iri": None,
                "target_proposal_id": canonical,
                "nearest": [],
                "reasoning": (
                    "The plural stem collides with target_proposal_id (an inflection "
                    "variant collected earlier)."
                ),
                "judged_by": DETERMINISTIC,
            }
        return None

    def changes(self, registry: ProposalRegistry) -> list[dict[str, Any]]:
        """Judgment changes to append, sorted by proposal ID. Empty when the
        registry already reflects the deterministic verdicts."""
        canonical_by_stem: dict[str, str] = {}
        for p in sorted(
            registry.proposals.values(),
            key=lambda x: (x.first_seen_position, x.proposal_id),
        ):
            canonical_by_stem.setdefault(stem_label(p.normalized_label), p.proposal_id)

        out: list[dict[str, Any]] = []
        for p in registry.all():
            if is_preserved(p):
                continue
            block = self.judge(p, canonical_by_stem)
            if judgment_core(block) != judgment_core(p.judgment):
                out.append({"proposal_id": p.proposal_id, "judgment": block})
        return out


def survivors(registry: ProposalRegistry) -> list[Proposal]:
    """Proposals that still need a definition-level judgment: no judgment,
    or an alias candidate under the guardrail."""
    return [
        p for p in registry.all()
        if p.judgment is None or p.judgment.get("verdict") == VERDICT_ALIAS
    ]


__all__ = [
    "ALIAS_GUARDRAIL",
    "VERDICT_ALIAS",
    "VERDICT_DUPLICATE",
    "VERDICT_MERGE",
    "DeterministicDeduper",
    "is_preserved",
    "survivors",
]
