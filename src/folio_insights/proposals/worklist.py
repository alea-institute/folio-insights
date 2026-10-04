"""Judgment worklist generation (governance plan U2, Stage B2 preparation).

Offline and deterministic. For every dedupe survivor this attaches the
lexically nearest FOLIO concepts **with their definitions**, because the
verdict must rest on definitions, not labels. It then splits the survivors:

* ``items``: a near candidate exists (best score at or above ``floor``), or
  the proposal is an alias candidate. These need a definition-level judgment.
* ``floored``: no FOLIO concept within lexical range. The recommendation is
  ``NOVEL``, and the nearest concepts are attached for reference.

Producing a worklist records nothing and approves nothing. It makes no model
or network call. Worklist items carry labels, provenance references (runs,
unit IDs, spans) and FOLIO definitions, never source text.
"""
from __future__ import annotations

from typing import Any

from folio_insights.proposals.dedupe import VERDICT_ALIAS, survivors
from folio_insights.proposals.lexicon import FolioLexicon
from folio_insights.proposals.registry import Proposal, ProposalRegistry

WORKLIST_SCHEMA = "proposed-class-worklist/v2"


def nearest_concepts(
    lexicon: FolioLexicon,
    normalized: str,
    *,
    k: int,
    min_score: float,
    primary: dict[str, tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Top-``k`` FOLIO primary labels by rapidfuzz ``token_sort_ratio``."""
    from rapidfuzz import fuzz, process

    primary = primary if primary is not None else lexicon.primary_labels()
    choices = sorted(primary)
    out = []
    for key, score, _ in process.extract(normalized, choices, scorer=fuzz.token_sort_ratio,
                                         limit=k):
        if score < min_score:
            continue
        iri, label = primary[key]
        out.append({
            "iri": iri,
            "label": label,
            "definition": lexicon.definition(iri),
            "score": round(float(score), 1),
        })
    out.sort(key=lambda c: (-c["score"], c["iri"]))
    return out


def _item(p: Proposal, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "proposal_id": p.proposal_id,
        "proposed_label": p.proposed_label,
        "normalized_label": p.normalized_label,
        "label_variants": list(p.label_variants),
        "occurrences": p.occurrences,
        "provenance": {
            "runs": list(p.runs),
            "units": [
                {"run": s["run"], "unit_id": s["unit_id"], "source_span": s.get("source_span")}
                for s in p.supporting_units
            ],
        },
        "current_judgment": p.judgment,
        "candidates": candidates,
    }


def build_worklist(
    registry: ProposalRegistry,
    lexicon: FolioLexicon,
    *,
    floor: float = 74.0,
    k: int = 4,
    min_candidate: float = 60.0,
) -> dict[str, Any]:
    primary = lexicon.primary_labels()
    items: list[dict[str, Any]] = []
    floored: list[dict[str, Any]] = []
    for p in survivors(registry):
        if p.decision.get("status") != "pending":
            continue
        cands = nearest_concepts(
            lexicon, p.normalized_label, k=k, min_score=min_candidate, primary=primary
        )
        is_alias = p.judgment is not None and p.judgment.get("verdict") == VERDICT_ALIAS
        if is_alias:
            target = p.judgment.get("target_iri")
            if target and all(c["iri"] != target for c in cands):
                cands.insert(0, {
                    "iri": target,
                    "label": lexicon.by_iri.get(target, {}).get("label", ""),
                    "definition": lexicon.definition(target),
                    "score": None,
                    "match": "alias",
                })
        best = max((c["score"] for c in cands if c["score"] is not None), default=0.0)
        item = _item(p, cands)
        if is_alias or best >= floor:
            item["recommendation"] = None
            items.append(item)
        else:
            item["recommendation"] = "NOVEL"
            item["reasoning"] = (
                f"No FOLIO concept within lexical range (best score {best} is below the "
                f"floor {floor}); the nearest concepts are attached for reference."
            )
            floored.append(item)
    return {
        "schema": WORKLIST_SCHEMA,
        "corpus": registry.corpus,
        "ledger_head": registry.head,
        "parameters": {"floor": floor, "k": k, "min_candidate": min_candidate},
        "counts": {"items": len(items), "floored": len(floored)},
        "items": items,
        "floored": floored,
    }


__all__ = ["WORKLIST_SCHEMA", "build_worklist", "nearest_concepts"]
