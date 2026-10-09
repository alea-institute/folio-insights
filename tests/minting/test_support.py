"""Deterministic support gates, with synthetic claims and injected NLI scores."""
from types import SimpleNamespace

import pytest

from folio_insights.minting.support import (
    SupportPolicy,
    SupportUnavailable,
    check_support,
    unsupported_specifics_only,
)
from folio_insights.rubric.adapters import AnchorClaim, RubricUnit, shard_claim
from folio_insights.rubric.criteria import assess_anchor


@pytest.mark.parametrize(('claim', 'passage', 'missing'), [
    ('Rule 26(a)(2) requires disclosure.', 'Rule 26 requires disclosure.', ('citation',)),
    ('Rule 26 requires disclosure.', 'Rule 26(a)(2) requires disclosure.', ()),
    ('FRE 702 governs experts.', 'Rule 702 governs experts under the Rules of Evidence.', ()),
    ('FRE 702 governs experts.', 'Rule 702 governs experts.', ('citation',)),
    ('28 U.S.C. § 1332 governs jurisdiction.', '28 U.S.C. § 1331 governs jurisdiction.', ('citation',)),
    ('Smith v. Jones requires disclosure.', 'Smith v. Adams requires disclosure.', ('case_name',)),
    ('A hearing on January 12, 2026.', 'A hearing on 2026-01-12.', ()),
    ('A hearing on January 12, 2026.', 'A hearing on 2026-01-13.', ('date',)),
    ('The award was $5 million.', 'The award was 5,000,000 dollars.', ()),
    ('The award was $5 million.', 'The award was 5 million votes.', ('money',)),
    ('The fee was fifteen percent.', 'The fee was 15%.', ()),
    ('The fee was 15%.', 'The fee was 15 dollars.', ('percentage',)),
    ('The court allowed fourteen days.', 'The court allowed 14 days.', ()),
    ('The court allowed fourteen days.', 'The court allowed 10 days.', ('number',)),
    ('Acme Corporation must disclose documents.', 'The corporation must disclose documents.', ('proper_noun',)),
])
def test_specifics_must_be_supported(claim, passage, missing):
    assert unsupported_specifics_only(claim, passage) == missing


def test_lexical_support_refuses_unrelated_claim_without_repeating_prose():
    result = check_support('Witnesses disclose documents before hearings.',
                           'Counsel argues objections during examination.')
    assert not result.supported and result.ratio == 0
    assert result.failures()[0][0] == 'claim_unsupported'
    assert 'Witnesses' not in str(result.as_dict()) + str(result.failures())


def test_supported_compression_and_policy_floor():
    result = check_support('Counsel prepares witnesses before trial.',
                           'Before trial, counsel prepares witnesses and reviews exhibits.')
    assert result.supported and result.ratio == 1
    with pytest.raises(ValueError):
        SupportPolicy(min_recall=1.1)


class Scorer:
    name = 'synthetic-entailment'

    def __init__(self, score):
        self.score = score
        self.pairs = []

    def entailment_probabilities(self, pairs):
        self.pairs.extend(pairs)
        return [self.score] * len(pairs)


def test_nli_is_optional_and_runs_after_deterministic_checks():
    scorer = Scorer(0.2)
    policy = SupportPolicy(nli=True, scorer=scorer).resolve_scorer()
    passage = 'Counsel prepares witnesses before trial.'
    result = check_support(passage, passage, policy)
    assert result.failures()[0][0] == 'claim_not_entailed'
    assert scorer.pairs == [(passage, passage)]
    check_support('Counsel invented Rule 26.', passage, policy)
    assert len(scorer.pairs) == 1
    with pytest.raises(SupportUnavailable):
        check_support(passage, passage, SupportPolicy(nli=True))


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -0.1, 1.1])
def test_invalid_nli_probabilities_refuse_instead_of_accepting(value):
    passage = 'Counsel prepares witnesses before trial.'
    with pytest.raises(SupportUnavailable):
        check_support(passage, passage, SupportPolicy(nli=True, scorer=Scorer(value)))


def test_verbatim_anchor_does_not_validate_an_invented_shard_claim():
    passage = 'Counsel prepares witnesses before trial and reviews exhibits.'
    anchor = AnchorClaim('synthetic.txt', passage, snippet=passage,
                         claim='Rule 26 requires counsel to prepare witnesses before trial.')
    assessment = assess_anchor(RubricUnit('u', anchor.claim, 'c', 'hash', (), anchor))
    assert assessment.score == 0
    assert 'unsupported_specifics:citation' in assessment.issues


def test_shard_claim_uses_literal_object_then_sense():
    shard = SimpleNamespace(sense='abstract sense', triple=SimpleNamespace(
        object='distilled claim', object_datatype='http://www.w3.org/2001/XMLSchema#string'))
    assert shard_claim(shard) == 'distilled claim'
    shard.triple.object_datatype = None
    assert shard_claim(shard) == 'abstract sense'
