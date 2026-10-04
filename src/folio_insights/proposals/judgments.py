"""Judgment block validation (shared by recording, dedupe output and the worklist).

A judgment is the only free-form structure a caller can put into the proposal
ledger, so it is the main way an excerpt could slip in. Every block is
reduced to an exact schema:

* keys: ``verdict``, ``target_iri``, ``target_proposal_id``, ``nearest``,
  ``reasoning``, ``judged_by``, ``guardrail``. Any other key is refused, not
  dropped.
* ``nearest``: at most ``MAX_NEAREST`` items, each with keys from exactly
  ``{iri, label, match_form, score}`` (``iri`` required). FOLIO definitions are
  not stored; the worklist reads them from the lexicon.
* length caps on every string, ``reasoning`` included (``MAX_REASONING_CHARS``).
* verdict-specific targets: ``MERGE_WITH`` names an existing other proposal;
  ``DUPLICATE_OF``, ``SYNONYM_OF`` and ``ALIAS_CANDIDATE`` name a FOLIO IRI;
  any ``target_proposal_id`` must exist.

Errors name the item index and the rule, never the offending value, so
refused input does not end up in logs or tracebacks.
"""
from __future__ import annotations

from collections.abc import Mapping, Set
from typing import Any

VERDICTS = frozenset({
    "NOVEL", "DUPLICATE_OF", "SYNONYM_OF", "MERGE_WITH", "NEEDS_WORK", "ALIAS_CANDIDATE",
})
JUDGMENT_KEYS = frozenset({
    "verdict", "target_iri", "target_proposal_id", "nearest", "reasoning", "judged_by",
    "guardrail",
})
NEAREST_KEYS = frozenset({"iri", "label", "match_form", "score"})
MATCH_FORMS = frozenset({"primary", "pref", "alt", "hidden"})
MAX_NEAREST = 10
MAX_REASONING_CHARS = 500
MAX_IRI_CHARS = 500
MAX_LABEL_CHARS = 200
MAX_JUDGED_BY_CHARS = 100
MAX_GUARDRAIL_CHARS = 64
_NEEDS_IRI = frozenset({"DUPLICATE_OF", "SYNONYM_OF", "ALIAS_CANDIDATE"})


class JudgmentInvalid(ValueError):
    """A judgment failed validation. The message names the item and rule only."""


def _str(value: Any, limit: int, *, where: str, field: str, optional: bool = True) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or (not optional and not value.strip()):
        raise JudgmentInvalid(f"{where}: {field} must be a non-empty string")
    if len(value) > limit:
        raise JudgmentInvalid(f"{where}: {field} exceeds {limit} characters")
    return value


def _nearest(items: Any, *, where: str) -> list[dict[str, Any]]:
    if items is None:
        return []
    if not isinstance(items, list) or len(items) > MAX_NEAREST:
        raise JudgmentInvalid(f"{where}: nearest must be a list of at most {MAX_NEAREST} items")
    out = []
    for n, item in enumerate(items):
        here = f"{where}.nearest[{n}]"
        if not isinstance(item, Mapping) or not set(item) <= NEAREST_KEYS:
            raise JudgmentInvalid(
                f"{here}: only the keys {sorted(NEAREST_KEYS)} are allowed"
            )
        form = item.get("match_form")
        if form is not None and form not in MATCH_FORMS:
            raise JudgmentInvalid(f"{here}: match_form is not a FOLIO label form")
        score = item.get("score")
        if score is not None and (isinstance(score, bool) or not isinstance(score, (int, float))):
            raise JudgmentInvalid(f"{here}: score must be a number or null")
        out.append({
            "iri": _str(item.get("iri"), MAX_IRI_CHARS, where=here, field="iri",
                        optional=False),
            "label": _str(item.get("label"), MAX_LABEL_CHARS, where=here, field="label") or "",
            "match_form": form,
            "score": score,
        })
    return out


def validate_judgment(
    block: Mapping[str, Any],
    *,
    proposal_id: str,
    known_ids: Set[str],
    where: str,
) -> dict[str, Any]:
    """The canonical form of ``block``, or ``JudgmentInvalid``."""
    if not isinstance(block, Mapping):
        raise JudgmentInvalid(f"{where}: a judgment must be an object")
    extra = set(block) - JUDGMENT_KEYS
    if extra:
        raise JudgmentInvalid(
            f"{where}: {len(extra)} key(s) outside {sorted(JUDGMENT_KEYS)} are not allowed"
        )
    verdict = block.get("verdict")
    if verdict not in VERDICTS:
        raise JudgmentInvalid(f"{where}: verdict must be one of {sorted(VERDICTS)}")
    target_iri = _str(block.get("target_iri"), MAX_IRI_CHARS, where=where, field="target_iri")
    target_pid = _str(block.get("target_proposal_id"), 64, where=where,
                      field="target_proposal_id")
    if target_pid is not None and (target_pid not in known_ids or target_pid == proposal_id):
        raise JudgmentInvalid(
            f"{where}: target_proposal_id must name another existing proposal of this corpus"
        )
    if verdict == "MERGE_WITH" and target_pid is None:
        raise JudgmentInvalid(f"{where}: MERGE_WITH needs target_proposal_id")
    if verdict in _NEEDS_IRI and not target_iri:
        raise JudgmentInvalid(f"{where}: {verdict} needs target_iri")
    out: dict[str, Any] = {
        "verdict": verdict,
        "target_iri": target_iri,
        "target_proposal_id": target_pid,
        "nearest": _nearest(block.get("nearest"), where=where),
        "reasoning": _str(block.get("reasoning"), MAX_REASONING_CHARS, where=where,
                          field="reasoning") or "",
        "judged_by": _str(block.get("judged_by"), MAX_JUDGED_BY_CHARS, where=where,
                          field="judged_by", optional=False),
    }
    guardrail = _str(block.get("guardrail"), MAX_GUARDRAIL_CHARS, where=where, field="guardrail")
    if guardrail is not None:
        out["guardrail"] = guardrail
    return out


def judgment_view(judgment: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Only the validated fields of a stored judgment (for the worklist)."""
    if judgment is None:
        return None
    view = {k: judgment.get(k) for k in sorted(JUDGMENT_KEYS) if k in judgment}
    view["nearest"] = [
        {k: n.get(k) for k in sorted(NEAREST_KEYS)}
        for n in (judgment.get("nearest") or []) if isinstance(n, Mapping)
    ][:MAX_NEAREST]
    if isinstance(view.get("reasoning"), str):
        view["reasoning"] = view["reasoning"][:MAX_REASONING_CHARS]
    return view


__all__ = [
    "JUDGMENT_KEYS",
    "MAX_NEAREST",
    "MAX_REASONING_CHARS",
    "NEAREST_KEYS",
    "VERDICTS",
    "JudgmentInvalid",
    "judgment_view",
    "validate_judgment",
]
