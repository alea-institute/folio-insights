"""RUB-EXTRACT [DET] criteria on synthetic unit runs (R7; rubric -03, -05, -09, -10, -11)."""
from __future__ import annotations

from pathlib import Path

import pytest

from folio_insights.rubric.adapters import (
    RubricArtifact,
    ShaclEvidence,
    StructuralCheck,
    UnitRun,
)
from folio_insights.rubric.criteria import (
    CATALOGUE,
    DET_CRITERIA,
    JUDGED_CRITERIA,
    SPECS,
    iri_validity,
    precision_no_padding,
    shape_conformance,
    source_anchoring,
    structural_integrity,
)
from folio_insights.services.anchoring import MIN_ANCHOR_SCORE, resolve_anchor

from tests.rubric.conftest import (
    CROSS,
    DAUBERT,
    RUSSIA,
    SOURCE,
    SYNTHETIC_IRI,
    tag,
    unit,
    write_run,
)

NEAR_QUOTE = "Keep every question on cross short."  # partial-ratio 0.88 against SOURCE
NEAR_MISS = "Ask leading questions so witnesses agree."  # 0.83: below the bar
EXACT = "Ask leading questions so the witness can only agree."


def _load(tmp_path: Path, units: list[dict], **kw) -> RubricArtifact:  # noqa: ANN003
    run, src = write_run(tmp_path, units, **kw)
    return UnitRun.load(run, src)


# ── catalogue (rubric §3) ──────────────────────────────────────────────────


def test_catalogue_matches_rubric_weights_and_gates() -> None:
    weights = {s.id: s.weight for s in CATALOGUE}
    assert weights == {
        "RUB-EXTRACT-01": 10, "RUB-EXTRACT-02": 6, "RUB-EXTRACT-03": 5, "RUB-EXTRACT-04": 4,
        "RUB-EXTRACT-05": 10, "RUB-EXTRACT-06": 12, "RUB-EXTRACT-07": 8,
        "RUB-EXTRACT-08": 14, "RUB-EXTRACT-09": 6,
        "RUB-EXTRACT-10": 6, "RUB-EXTRACT-11": 4,
        "RUB-EXTRACT-12": 6, "RUB-EXTRACT-13": 5, "RUB-EXTRACT-14": 4,
    }
    dims = {}
    for s in CATALOGUE:
        dims[s.dimension] = dims.get(s.dimension, 0) + s.weight
    assert dims == {"A": 25, "B": 30, "C": 20, "D": 10, "E": 15}
    assert {s.id for s in CATALOGUE if s.gate == "gate"} == {
        "RUB-EXTRACT-05", "RUB-EXTRACT-06", "RUB-EXTRACT-10", "RUB-EXTRACT-11"}
    assert SPECS["RUB-EXTRACT-03"].gate == "gate_soft"
    assert DET_CRITERIA == ("RUB-EXTRACT-03", "RUB-EXTRACT-05", "RUB-EXTRACT-09",
                            "RUB-EXTRACT-10", "RUB-EXTRACT-11")
    assert set(JUDGED_CRITERIA) == {f"RUB-EXTRACT-{n:02d}" for n in (1, 2, 4, 6, 7, 8, 12, 13, 14)}


def test_fuzzy_fixture_scores_sit_in_the_intended_bands() -> None:
    near = resolve_anchor(NEAR_QUOTE, SOURCE)
    miss = resolve_anchor(NEAR_MISS, SOURCE)
    assert MIN_ANCHOR_SCORE <= near.score <= 0.92
    assert miss.score < MIN_ANCHOR_SCORE


# ── RUB-EXTRACT-03 ─────────────────────────────────────────────────────────


def test_iri_validity_wrong_branch_soft_fails(tmp_path: Path, oracle) -> None:  # noqa: ANN001
    art = _load(tmp_path, [
        unit("ok", EXACT, tags=[tag(CROSS, "Cross-Examination of Witness", "Event")]),
        unit("wrong-branch", NEAR_QUOTE, span=(0, 5),
             tags=[tag(RUSSIA, "Rule 26(a)(1)", "Service", "llm")]),
    ])
    r = iri_validity(art, oracle)
    assert r.computed and r.gate == "soft_fail"
    assert r.per_unit["ok"]["score"] == 3
    assert r.per_unit["wrong-branch"]["score"] == 0
    assert r.per_unit["wrong-branch"]["gate"] == "soft_fail"
    assert r.per_unit["wrong-branch"]["issues"] == [
        f"branch_mismatch:{RUSSIA}:claimed=Service:actual=Location"]
    assert r.score == 1.5
    assert r.details["capped_units"] == ["wrong-branch"]


def test_iri_validity_empty_iri_needs_proposed_class(tmp_path: Path, oracle) -> None:  # noqa: ANN001
    art = _load(tmp_path, [
        unit("llm-empty", EXACT, tags=[tag("", "orphan concept", "", "llm")]),
        unit("proposed", NEAR_QUOTE, span=(0, 5),
             tags=[tag("", "New Concept", "", "proposed_class")]),
    ])
    r = iri_validity(art, oracle)
    assert r.per_unit["llm-empty"]["issues"] == ["empty_iri_not_proposed:orphan concept"]
    assert r.per_unit["proposed"] == {"score": 3, "gate": "pass", "issues": []}
    assert r.gate == "soft_fail"


def test_iri_validity_unresolvable_iri_and_branch_matching(tmp_path: Path, oracle) -> None:  # noqa: ANN001
    art = _load(tmp_path, [
        unit("ghost", EXACT, tags=[tag(SYNTHETIC_IRI, "SYNTHETIC", "Service", "llm")]),
        # Multi-branch concept: either branch matches; case and spacing do not matter.
        unit("multi", NEAR_QUOTE, span=(0, 5), tags=[tag(CROSS, "x", " service ")]),
        unit("unclaimed", NEAR_MISS, span=(0, 5), tags=[tag(DAUBERT, "x", "")]),
    ])
    r = iri_validity(art, oracle)
    assert r.per_unit["ghost"]["issues"] == [f"iri_unresolvable:{SYNTHETIC_IRI}"]
    assert r.per_unit["multi"]["score"] == 3
    assert r.per_unit["unclaimed"]["score"] == 3
    assert r.details["branch_unclaimed"] == 1
    assert r.details["tags_checked"] == 3


def test_iri_validity_without_oracle_is_not_computed(tmp_path: Path) -> None:
    r = iri_validity(_load(tmp_path, [unit("u", EXACT)]), None)
    assert not r.computed and r.score is None and r.gate is None
    assert "oracle" in r.reason


# ── RUB-EXTRACT-05 ─────────────────────────────────────────────────────────


def test_anchor_exact_span_scores_three(tmp_path: Path) -> None:
    r = source_anchoring(_load(tmp_path, [unit("u", EXACT)]))
    assert r.per_unit["u"]["score"] == 3 and r.per_unit["u"]["route"] == "span"
    assert r.gate == "pass" and r.score == 3.0


def test_paraphrase_without_verifying_anchor_fails_the_gate(tmp_path: Path) -> None:
    """Books Q1: a fluent paraphrase whose offsets slice an unrelated fragment."""
    r = source_anchoring(_load(tmp_path, [
        unit("para", "Lead the witness through every exhibit.", span=(0, 12)),
        unit("good", EXACT),
    ]))
    assert r.per_unit["para"]["score"] == 0
    assert r.gate == "fail"
    assert r.details["failing_units"] == ["para"]
    assert r.score == 1.5


def test_pipeline_snippet_at_low_recorded_score_fails(tmp_path: Path) -> None:
    """AE1-style: the stored snippet equals its slice, but the pipeline recorded 0.62."""
    start = SOURCE.index("Keep each question")
    snippet = SOURCE[start:start + 40]
    r = source_anchoring(_load(tmp_path, [
        unit("fluent", "Witnesses must never be led on direct.", span=(start, start + 40),
             snippet=snippet, anchor_score=0.62, anchor_verified=False),
    ]))
    assert r.per_unit["fluent"]["score"] == 0
    assert "stored_anchor_unverified:0.6200" in r.per_unit["fluent"]["issues"]
    assert r.gate == "fail"


def test_snippet_between_085_and_092_scores_two(tmp_path: Path) -> None:
    near = resolve_anchor(NEAR_QUOTE, SOURCE)
    start = SOURCE.index("Keep each question")
    r = source_anchoring(_load(tmp_path, [
        # A pipeline snippet at its slice with a recorded 0.88 anchor score.
        unit("stored", "Keep cross questions short.", span=(near.start, near.end),
             snippet=near.snippet, anchor_score=near.score, anchor_verified=True),
        # A quoted snippet that is not at its span but fuzzy-matches the source at 0.88.
        unit("quoted", "Short questions on cross.", span=(start, start + 10),
             snippet=NEAR_QUOTE, anchor_score=near.score, anchor_verified=True),
        # The same near-quote as the unit's own text (pre-snippet format).
        unit("text", NEAR_QUOTE, span=(start, start + len(NEAR_QUOTE))),
    ]))
    assert {uid: e["score"] for uid, e in r.per_unit.items()} == {
        "stored": 2, "quoted": 2, "text": 2}
    assert r.gate == "pass"


def test_exact_quote_with_shifted_span_is_loose(tmp_path: Path) -> None:
    start = SOURCE.index(EXACT) + 4
    r = source_anchoring(_load(tmp_path, [unit("shift", EXACT, span=(start, start + len(EXACT)))]))
    assert r.per_unit["shift"]["score"] == 2
    assert "span_does_not_slice_quote" in r.per_unit["shift"]["issues"]


def test_near_miss_quote_and_bad_spans_fail(tmp_path: Path) -> None:
    n = len(SOURCE)
    r = source_anchoring(_load(tmp_path, [
        unit("miss", NEAR_MISS, span=(0, 5)),
        unit("oob", "Words that are not there at all.", span=(n - 2, n + 50)),
        unit("empty", "Another sentence not in the text.", span=(20, 20)),
    ]))
    assert all(e["score"] == 0 for e in r.per_unit.values())
    assert "span_out_of_bounds_or_empty" in r.per_unit["oob"]["issues"]
    assert "span_out_of_bounds_or_empty" in r.per_unit["empty"]["issues"]


def test_inconsistent_stored_anchor_is_not_trusted(tmp_path: Path) -> None:
    start = SOURCE.index(EXACT)
    r = source_anchoring(_load(tmp_path, [
        unit("liar", "A paraphrase of the passage.", span=(start, start + len(EXACT)),
             snippet=EXACT, anchor_score=0.40, anchor_verified=True),
    ]))
    assert r.per_unit["liar"]["score"] == 0
    assert "stored_anchor_inconsistent" in r.per_unit["liar"]["issues"]


def test_missing_and_escaping_sources_fail_per_unit(tmp_path: Path) -> None:
    (tmp_path / "outside.txt").write_text(SOURCE, encoding="utf-8")
    r = source_anchoring(_load(tmp_path, [
        unit("missing", EXACT, source_file="absent.txt"),
        unit("escape", EXACT, source_file="../outside.txt"),
    ]))
    assert r.per_unit["missing"]["issues"] == ["source_not_found"]
    # "../outside.txt" is outside the sources dir; its file name is not inside it either.
    assert r.per_unit["escape"]["score"] == 0
    assert r.gate == "fail"


def test_anchoring_without_sources_is_not_computed(tmp_path: Path) -> None:
    run, _ = write_run(tmp_path, [unit("u", EXACT)])
    r = source_anchoring(UnitRun.load(run))
    assert not r.computed and r.score is None and r.gate is None
    assert "--sources" in r.reason


# ── RUB-EXTRACT-09 ─────────────────────────────────────────────────────────


def _sources() -> dict[str, str]:
    lines = ["Chapter 4 Opening Statements", "B. Preparing the Witness"]
    lines += [f"Synthetic advice sentence number {w} for the opening." for w in
              ("one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
               "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
               "seventeen", "eighteen", "nineteen", "twenty")]
    return {"opening.txt": "\n\n".join(lines) + "\n"}


def _opening_unit(uid: str, text: str, **kw) -> dict:  # noqa: ANN003
    return unit(uid, text, source=_sources()["opening.txt"], source_file="opening.txt", **kw)


def test_duplicates_and_headings_fail_precision(tmp_path: Path) -> None:
    advice = "Synthetic advice sentence number one for the opening."
    art = _load(tmp_path, [
        _opening_unit("h1", "Chapter 4 Opening Statements"),
        _opening_unit("h2", "B. Preparing the Witness"),
        _opening_unit("a1", advice),
        _opening_unit("a2", advice),
    ], sources=_sources())
    r = precision_no_padding(art)
    flags = {uid: e["flags"] for uid, e in r.per_unit.items()}
    assert flags == {"h1": ["heading_as_unit"], "h2": ["heading_as_unit"], "a1": [],
                     "a2": ["duplicate_of:a1"]}
    assert r.score == 0.0  # 3 of 4 flagged: noisy
    assert r.computed and r.gate is None


@pytest.mark.parametrize(("flagged", "expected"), [(0, 3), (1, 2), (2, 1), (3, 0)])
def test_precision_bands(tmp_path: Path, flagged: int, expected: int) -> None:
    words = ("one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
             "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
             "seventeen", "eighteen", "nineteen", "twenty")
    units = [_opening_unit(f"u{i}", f"Synthetic advice sentence number {w} for the opening.")
             for i, w in enumerate(words)]
    for i in range(flagged):  # duplicate the first unit's hash into the next ones
        units[i + 1]["content_hash"] = units[0]["content_hash"]
    r = precision_no_padding(_load(tmp_path, units, sources=_sources()))
    assert r.details["per_chapter"]["opening.txt"]["flagged"] == flagged
    assert r.score == expected  # 20 units: 2 flagged = 10% (several), 3 = 15% (noisy)


def test_unit_anchored_to_a_heading_is_flagged(tmp_path: Path) -> None:
    src = _sources()["opening.txt"]
    start = src.index("B. Preparing the Witness")
    art = _load(tmp_path, [
        _opening_unit("gen", "Prepare the witness thoroughly before trial.",
                      span=(start, start + 24), snippet=src[start:start + 24],
                      anchor_score=1.0, anchor_verified=True),
    ], sources=_sources())
    assert precision_no_padding(art).per_unit["gen"]["flags"] == ["anchored_to_heading"]


# ── RUB-EXTRACT-10 / -11 ───────────────────────────────────────────────────


def test_shacl_criteria_are_not_computed_on_a_unit_run(tmp_path: Path) -> None:
    art = _load(tmp_path, [unit("u", EXACT)])
    for result in (shape_conformance(art), structural_integrity(art)):
        assert not result.computed and result.score is None and result.gate is None
        assert "unit run has no RDF" in result.reason


def _corpus_artifact(**kw) -> RubricArtifact:  # noqa: ANN003
    return RubricArtifact(kind="shard_corpus", ref="synthetic", units=(), **kw)


@pytest.mark.parametrize(("conforms", "warnings", "score", "gate"), [
    (True, 0, 3.0, "pass"), (True, 4, 2.0, "pass"), (False, 0, 0.0, "fail")])
def test_shape_conformance_scale(conforms: bool, warnings: int, score: float, gate: str) -> None:
    ev = ShaclEvidence(conforms=conforms, violations=0 if conforms else 2, warnings=warnings,
                       suite_digest="d", shards=1, events=0)
    r = shape_conformance(_corpus_artifact(shacl=ev))
    assert (r.computed, r.score, r.gate) == (True, score, gate)


@pytest.mark.parametrize(("statuses", "score", "gate"), [
    (("PASS", "PASS", "PASS"), 3.0, "pass"),
    (("PASS", "FAIL", "PASS"), 0.0, "fail"),
    (("PASS", "PASS", "WARN"), 2.0, "pass"),
])
def test_structural_integrity_scale(statuses: tuple[str, ...], score: float, gate: str) -> None:
    names = ("IRI Uniqueness", "Referential Integrity", "Namespace Consistency")
    checks = tuple(StructuralCheck(n, s, "") for n, s in zip(names, statuses, strict=True))
    r = structural_integrity(_corpus_artifact(structural=checks))
    assert (r.computed, r.score, r.gate) == (True, score, gate)
