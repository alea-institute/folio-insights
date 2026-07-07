"""Tests for HYBRID-STRICT source anchoring (RUB-EXTRACT-05)."""

from folio_insights.services.anchoring import MIN_ANCHOR_SCORE, resolve_anchor

SOURCE = (
    "The advocate must obtain the full deposition regarding the factual basis "
    "of expert opinions before filing Daubert or Frye motions. Never rely on "
    "the report alone. Object to untimely witness disclosures during discovery."
)


def test_exact_match_scores_one_and_verifies():
    candidate = "Object to untimely witness disclosures during discovery."
    r = resolve_anchor(candidate, SOURCE)
    assert r is not None
    assert r.verified is True
    assert r.score == 1.0
    assert SOURCE[r.start : r.end] == candidate
    assert r.snippet == candidate


def test_fuzzy_paraphrase_above_threshold_verifies():
    # A true NON-substring (typo + dropped 's') must hit the fuzzy path, verify,
    # and align to the correct passage — not the first characters of the source.
    candidate = "obtain the full depositon regarding the factual basis of expert opinion"
    assert SOURCE.find(candidate) == -1  # genuinely not an exact substring
    r = resolve_anchor(candidate, SOURCE)
    assert r is not None
    assert r.score >= MIN_ANCHOR_SCORE
    assert r.verified is True
    # Located span sits inside the source, and the stored snippet equals the slice.
    assert 0 <= r.start < r.end <= len(SOURCE)
    assert SOURCE[r.start : r.end] == r.snippet
    # The matched window is the deposition passage, not the source's opening.
    assert "deposition regarding the factual basis" in r.snippet


def test_unrelated_text_below_threshold_flagged_unverified():
    candidate = "The parties agreed to arbitrate all disputes in Delaware chancery court."
    r = resolve_anchor(candidate, SOURCE)
    # A best-effort span may be returned, but it must be flagged unverified.
    assert r is None or r.verified is False


def test_empty_inputs_return_none():
    assert resolve_anchor("", SOURCE) is None
    assert resolve_anchor("something", "") is None
