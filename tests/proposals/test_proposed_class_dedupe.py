"""Deterministic dedupe: FOLIO matches, proposal merges, alias guardrail, survivors."""
from __future__ import annotations

import pytest

from folio_insights.proposals.dedupe import DeterministicDeduper, _stem
from folio_insights.proposals.lexicon import FolioLexicon


@pytest.fixture
def lex():
    by_iri = {
        "IRI:enc": {"label": "Encumbrance",
                    "definition": "A property-law burden on title (lien, charge, mortgage).",
                    "english_labels": ["Encumbrance", "charge", "lien"]},
        "IRI:law": {"label": "Lawyer",
                    "definition": "A person licensed to practise law.",
                    "english_labels": ["Lawyer", "attorney", "counsel"]},
        "IRI:vd": {"label": "Voir Dire",
                   "definition": "Preliminary examination of prospective jurors.",
                   "english_labels": ["Voir Dire"]},
    }
    by_norm = {}
    forms = {"Encumbrance": ("IRI:enc", "primary"), "charge": ("IRI:enc", "alt"),
             "lien": ("IRI:enc", "alt"), "Lawyer": ("IRI:law", "primary"),
             "attorney": ("IRI:law", "alt"), "counsel": ("IRI:law", "alt"),
             "Voir Dire": ("IRI:vd", "primary")}
    from folio_insights.proposals.lexicon import normalize
    for surface, (iri, form) in forms.items():
        by_norm.setdefault(normalize(surface), []).append(
            (iri, by_iri[iri]["label"], form))
    return FolioLexicon(by_iri, by_norm)


def _entry(pid, label, norm=None, judge=None):
    from folio_insights.proposals.registry import normalize_label
    return {"proposal_id": pid, "proposed_label": label,
            "normalized_label": norm or normalize_label(label), "judge": judge}


def test_primary_label_hit_is_duplicate(lex):
    d = DeterministicDeduper(lex)
    e = _entry("PC-1", "Encumbrance")
    counts = d.judge_registry([e])
    assert e["judge"]["verdict"] == "DUPLICATE_OF"
    assert e["judge"]["target_iri"] == "IRI:enc"
    assert "guardrail" not in e["judge"]
    assert counts["DUPLICATE_OF"] == 1


def test_alias_hit_carries_guardrail(lex):
    """'charge' matches only an ALT label of Encumbrance -> candidate, not auto."""
    d = DeterministicDeduper(lex)
    e = _entry("PC-2", "charge")
    d.judge_registry([e])
    assert e["judge"]["verdict"] == "DUPLICATE_OF"
    assert e["judge"]["target_iri"] == "IRI:enc"
    assert e["judge"]["guardrail"] == "alias-hit-verify-definition"
    assert "charge→Encumbrance" in e["judge"]["reasoning"] or "ALIAS" in e["judge"]["reasoning"]


def test_novel_proposal_is_survivor(lex):
    d = DeterministicDeduper(lex)
    e = _entry("PC-3", "Case Preparation Checklist")
    d.judge_registry([e])
    assert e["judge"] is None
    assert d.survivors([e]) == [e]


def test_proposal_merge_on_plural_stem(lex):
    d = DeterministicDeduper(lex)
    a = _entry("PC-a", "Advocate")
    b = _entry("PC-b", "Advocates")
    counts = d.judge_registry([a, b])
    verdicts = {e["proposal_id"]: (e["judge"] or {}).get("verdict") for e in (a, b)}
    # exactly one is merged into the other; the survivor stays None
    assert list(verdicts.values()).count("MERGE_WITH") == 1
    assert counts["MERGE_WITH"] == 1


def test_stem_collapses_inflections():
    assert _stem("advocates") == "advocate"
    assert _stem("strategies") == "strategy"
    assert _stem("duties") == "duty"
    assert _stem("witness") == "witness"  # -ss preserved


def test_does_not_clobber_claude_judgment(lex):
    d = DeterministicDeduper(lex)
    e = _entry("PC-9", "Encumbrance",
               judge={"verdict": "NOVEL", "judged_by": "claude-code:opus"})
    d.judge_registry([e])
    assert e["judge"]["verdict"] == "NOVEL"  # preserved


def test_idempotent_rejudge(lex):
    d = DeterministicDeduper(lex)
    e = _entry("PC-1", "Encumbrance")
    d.judge_registry([e])
    first = dict(e["judge"])
    d.judge_registry([e])
    assert e["judge"] == first
