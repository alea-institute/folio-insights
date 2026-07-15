"""Deterministic dedupe — Stage B1 ($0, tested).

Cheap, reproducible label matching that eliminates the obvious duplicates so the
Claude-side LLM-judge only sees genuine survivors. Two axes:

  1. Against the full FOLIO lexicon (all label forms).
  2. Against other registry entries (plural / stem variants).

The ``charge→Encumbrance`` lesson is honoured: an *alias* hit (the proposed
label matches a non-primary label form of a FOLIO concept) is only a **candidate**
duplicate — it is recorded with ``guardrail="alias-hit-verify-definition"`` and
left for the human to override on the concept's definition, never auto-approved.
"""
from __future__ import annotations
import re
from typing import Any

from folio_insights.proposals.lexicon import FolioLexicon, normalize

_PRIMARY_FORMS = {"primary"}


def _stem(norm: str) -> str:
    """Very light plural/gerund collapse for proposal↔proposal merges."""
    words = norm.split()
    out = []
    for w in words:
        if len(w) > 4 and w.endswith("ies"):
            w = w[:-3] + "y"
        elif w.endswith("ss"):
            pass
        elif len(w) > 3 and w.endswith("s"):
            w = w[:-1]
        out.append(w)
    return " ".join(out)


class DeterministicDeduper:
    def __init__(self, lexicon: FolioLexicon):
        self.lex = lexicon

    def judge_entry(self, entry: dict, registry_stems: dict[str, str]) -> dict | None:
        """Return a deterministic ``judge`` block, or None if entry is a survivor.

        ``registry_stems`` maps stem -> proposal_id for the whole registry (built
        by ``judge_registry``); used to detect proposal↔proposal merges.
        """
        norm = entry["normalized_label"]
        hits = self.lex.lookup(norm)
        if hits:
            primary = [h for h in hits if h[2] in _PRIMARY_FORMS]
            chosen = primary[0] if primary else hits[0]
            iri, label, form = chosen
            concept = self.lex.by_iri.get(iri, {})
            block = {
                "verdict": "DUPLICATE_OF",
                "target_iri": iri,
                "target_proposal_id": None,
                "nearest": [{
                    "iri": iri, "label": label,
                    "definition": concept.get("definition", ""),
                    "match_form": form,
                }],
                "reasoning": (
                    f"Normalized label '{norm}' matches the {form} label of FOLIO "
                    f"concept '{label}' ({iri})."
                    + ("" if form in _PRIMARY_FORMS else
                       " ALIAS hit — verify against the concept definition before "
                       "accepting; label collisions (cf. charge→Encumbrance) can be "
                       "semantically unrelated.")
                ),
                "judged_by": "deterministic",
            }
            if form not in _PRIMARY_FORMS:
                block["guardrail"] = "alias-hit-verify-definition"
            return block

        # proposal <-> proposal merge on stem collision
        stem = _stem(norm)
        other = registry_stems.get(stem)
        if other and other != entry["proposal_id"]:
            return {
                "verdict": "MERGE_WITH",
                "target_iri": None,
                "target_proposal_id": other,
                "nearest": [],
                "reasoning": f"Stem '{stem}' collides with proposal {other} (plural/inflection variant).",
                "judged_by": "deterministic",
            }
        return None

    def judge_registry(self, entries: list[dict]) -> dict[str, Any]:
        """Apply deterministic dedupe across a whole registry in place.

        Writes ``judge`` blocks for deterministic hits; leaves survivors' ``judge``
        as None. Returns a summary. Idempotent: only fills entries whose judge is
        None or was previously judged_by=deterministic.
        """
        # stem index (first-seen wins, sorted for determinism)
        stems: dict[str, str] = {}
        for e in sorted(entries, key=lambda x: x["proposal_id"]):
            stems.setdefault(_stem(e["normalized_label"]), e["proposal_id"])

        counts = {"DUPLICATE_OF": 0, "MERGE_WITH": 0, "alias_candidates": 0, "survivors": 0}
        for e in entries:
            if e.get("judge") and e["judge"].get("judged_by", "").startswith("claude"):
                continue  # never clobber a human/LLM judgment
            block = self.judge_entry(e, stems)
            if block is None:
                if not (e.get("judge") and e["judge"].get("judged_by", "").startswith("claude")):
                    e["judge"] = None
                counts["survivors"] += 1
            else:
                e["judge"] = block
                counts[block["verdict"]] += 1
                if block.get("guardrail"):
                    counts["alias_candidates"] += 1
        return counts

    def survivors(self, entries: list[dict]) -> list[dict]:
        return [e for e in entries if e.get("judge") is None]
