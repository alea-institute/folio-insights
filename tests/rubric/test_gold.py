"""The books gold set and the mapping-gold check run in CI with zero drift (R8, KTD5)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from folio_insights.rubric.adapters import ShardCorpus
from folio_insights.rubric.gold import (
    GoldSetError,
    case_dirs,
    compare_case,
    mapping_gold,
    repo_root,
    run_gold,
    score_case,
)
from folio_insights.rubric.harness import score

from tests.rubric.conftest import (
    GOLD_DIR,
    ORACLE_PATH,
    SOURCE,
    SOURCE_FILE,
    build_corpus,
    judged_all,
)

CORRECTIONS = repo_root() / "docs/evidence/books/mapping-corrections.gold.json"
# One case per books-UAT failure mode (DE-RISK-FINDINGS.md, pack.json) plus an exemplar.
EXPECTED_CASES = {
    "ep001_generative_unanchored",
    "ep002_iri_exists_not_correct",
    "q1_paraphrase_offsets",
    "b6_heading_as_unit",
    "dedup_not_held",
    "ep008_place_agency_mismap",
    "empty_and_unresolvable_iris",
    "clean_exemplary",
}


def test_gold_set_has_every_failure_mode_case() -> None:
    names = {p.name for p in case_dirs(GOLD_DIR)}
    assert names == EXPECTED_CASES
    for case in case_dirs(GOLD_DIR):
        assert (case / "extraction.json").is_file() and any((case / "source").iterdir())


def test_gold_set_has_zero_drift() -> None:
    """CI gate: every case matches expected.json and the mapping baseline holds."""
    result = run_gold()
    assert result.drift == [], "\n".join(result.drift)
    assert len(result.cases) == len(EXPECTED_CASES)
    assert result.ok


@pytest.mark.parametrize("case", sorted(EXPECTED_CASES))
def test_gold_case_matches_expected(case: str, oracle) -> None:  # noqa: ANN001
    case_dir = GOLD_DIR / case
    expected = json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))
    report = score_case(case_dir, oracle)
    assert compare_case(report, expected, case=case) == []
    # No file gold case is publishable: a unit run never computes the SHACL gates
    # (the shard-corpus case below covers the publishable path).
    assert report.publishable is False and expected["publishable"] is False
    for c in report.criteria:
        if c.status == "not_scored":
            assert c.score is None and c.gate is None


def test_gold_cases_reproduce_their_failure_modes(oracle) -> None:  # noqa: ANN001
    def crit(case: str, cid: str):  # noqa: ANN202
        return score_case(GOLD_DIR / case, oracle).criterion(cid)

    assert crit("ep001_generative_unanchored", "RUB-EXTRACT-05").gate == "fail"
    # EP-INSIGHTS-BOOKS-001: the fabricated units are judged 0 -> story fail on -06.
    ep001 = score_case(GOLD_DIR / "ep001_generative_unanchored", oracle)
    assert ep001.gates["RUB-EXTRACT-06"] == "fail"
    assert "gate RUB-EXTRACT-06 failed" in ep001.reasons
    assert crit("q1_paraphrase_offsets", "RUB-EXTRACT-05").gate == "fail"
    assert crit("ep002_iri_exists_not_correct", "RUB-EXTRACT-03").gate == "soft_fail"
    assert crit("empty_and_unresolvable_iris", "RUB-EXTRACT-03").gate == "soft_fail"
    assert crit("b6_heading_as_unit", "RUB-EXTRACT-09").score == 0.0
    assert crit("dedup_not_held", "RUB-EXTRACT-09").score == 0.0
    # "IRI exists" != "IRI correct": the wrong concepts pass the deterministic check...
    assert crit("ep008_place_agency_mismap", "RUB-EXTRACT-03").gate == "pass"
    # ...and only judged concept correctness could catch them, which is never assumed.
    assert crit("ep008_place_agency_mismap", "RUB-EXTRACT-01").status == "not_scored"
    clean = score_case(GOLD_DIR / "clean_exemplary", oracle)
    assert {clean.criterion(c).score for c in ("RUB-EXTRACT-03", "RUB-EXTRACT-05",
                                               "RUB-EXTRACT-09")} == {3.0}


def test_drift_is_detected(tmp_path: Path) -> None:
    gold = tmp_path / "gold"
    shutil.copytree(GOLD_DIR, gold)
    path = gold / "clean_exemplary" / "expected.json"
    expected = json.loads(path.read_text(encoding="utf-8"))
    expected["criteria"]["RUB-EXTRACT-05"]["score"] = 2.0
    expected["criteria"]["RUB-EXTRACT-05"]["per_unit"]["cl-01"] = 2
    path.write_text(json.dumps(expected), encoding="utf-8")
    result = run_gold(gold)
    assert not result.ok
    assert any("RUB-EXTRACT-05 score 3.0 != expected 2.0" in d for d in result.drift)
    assert any("unit cl-01 3 != expected 2" in d for d in result.drift)


def test_expected_must_pin_every_criterion(tmp_path: Path, oracle) -> None:  # noqa: ANN001
    case_dir = GOLD_DIR / "dedup_not_held"
    expected = json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))
    del expected["criteria"]["RUB-EXTRACT-14"]
    drift = compare_case(score_case(case_dir, oracle), expected, case="dedup_not_held")
    assert drift == ["dedup_not_held: expected.json does not pin RUB-EXTRACT-14"]


def test_mapping_gold_reproduces_recorded_baseline(oracle) -> None:  # noqa: ANN001
    result = mapping_gold(CORRECTIONS, oracle)
    assert (result["corrections"], result["agree"], result["agreement_rate"]) == (1, 0, 0.0)
    assert result["correct_iri_resolves"] == 1
    case = result["cases"][0]
    assert case["ep_id"] == "EP-INSIGHTS-BOOKS-009" and case["agree"] is False
    assert case["correct_branches"] == ["Service"]


def test_mapping_gold_agreement_and_drift(tmp_path: Path) -> None:
    corrections = tmp_path / "corrections.json"
    corrections.write_text(json.dumps({"corrections": [
        {"ep_id": "A", "pipeline_mapping": {"iri": "x"}, "correct_mapping": {"iri": "x"}},
        {"ep_id": "B", "pipeline_mapping": {"label": "Same"},
         "correct_mapping": {"iri": "y", "label": "same"}},
        {"ep_id": "C", "pipeline_mapping": {"iri": "z"}, "correct_mapping": {"iri": "y"}},
    ]}), encoding="utf-8")
    result = mapping_gold(corrections)
    assert (result["agree"], result["agreement_rate"]) == (2, 0.666667)
    run = run_gold(corrections_path=corrections)
    assert any(d.startswith("mapping-gold: agree 2 != expected baseline 0") for d in run.drift)


def test_gold_errors(tmp_path: Path) -> None:
    with pytest.raises(GoldSetError, match="not found"):
        case_dirs(tmp_path / "absent")
    with pytest.raises(GoldSetError, match="no gold cases"):
        case_dirs(tmp_path)
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"corrections": []}), encoding="utf-8")
    with pytest.raises(GoldSetError, match="non-empty"):
        mapping_gold(empty)


def test_gold_fixtures_pass_the_exclusion_scan() -> None:
    """Committed fixtures carry no snippet values and no long text values (KTD5)."""
    import sys

    sys.path.insert(0, str(repo_root() / "scripts"))
    try:
        import check_exclusions as ce
    finally:
        sys.path.pop(0)
    findings = []
    for path in sorted((repo_root() / "tests/rubric/fixtures").rglob("*")):
        rel = str(path.relative_to(repo_root()))
        if path.is_file() and ce.is_scanned(rel):
            findings.extend(ce.scan_text(rel, path.read_text(encoding="utf-8")))
    assert [f.render() for f in findings] == []
    assert ORACLE_PATH.is_file()


# The shard-corpus gold case. Committed fixtures cannot hold minted shards (their spans
# are long text the exclusion scan treats as possible book material), so the corpus is
# built in a temp directory here and pinned like a file case with ``compare_case``.
SHARD_CORPUS_EXPECTED = {
    "format": 1,
    "case": "shard_corpus_publishable",
    "covers": ["exemplar", "pass-rule"],
    "failure_mode": "None: signed, anchored shards with exemplary judged scores (both "
                    "halves of RUB-EXTRACT-05 included). The SHACL gates -10/-11 are "
                    "computed on the corpus and the story is publishable.",
    "publishable": True,
    "criteria": {
        **{cid: {"status": "judged", "score": 3.0, "gate": None}
           for cid in ("RUB-EXTRACT-01", "RUB-EXTRACT-02", "RUB-EXTRACT-04", "RUB-EXTRACT-07",
                       "RUB-EXTRACT-08", "RUB-EXTRACT-12", "RUB-EXTRACT-13", "RUB-EXTRACT-14")},
        "RUB-EXTRACT-03": {"status": "computed", "score": 3.0, "gate": "pass"},
        "RUB-EXTRACT-05": {"status": "computed+judged", "score": 3.0, "gate": "pass"},
        "RUB-EXTRACT-06": {"status": "judged", "score": 3.0, "gate": "pass"},
        "RUB-EXTRACT-09": {"status": "computed", "score": 3.0, "gate": None},
        "RUB-EXTRACT-10": {"status": "computed", "score": 3.0, "gate": "pass"},
        "RUB-EXTRACT-11": {"status": "computed", "score": 3.0, "gate": "pass"},
    },
}


@pytest.mark.storage
async def test_shard_corpus_gold_case_is_publishable(tmp_path: Path, oracle) -> None:  # noqa: ANN001
    """The gold set's publishable path: -10/-11 computed on a corpus, every gate green."""
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / SOURCE_FILE).write_text(SOURCE, encoding="utf-8")
    root = tmp_path / "storage"
    await build_corpus(root)
    art = await ShardCorpus.load(root, "rubric-corpus", sources)
    report = score(art, oracle, judged_all(3, unit_ids=[u.id for u in art.units]))
    assert compare_case(report, SHARD_CORPUS_EXPECTED, case="shard_corpus_publishable") == []
    assert report.publishable is True and report.reasons == ()
    assert report.normalized == 1.0
    # Without the judged [LLM] half of -05 the same corpus is not publishable.
    judged = judged_all(3, unit_ids=[u.id for u in art.units])
    del judged["scores"]["RUB-EXTRACT-05"]
    mechanical = score(art, oracle, judged)
    assert mechanical.publishable is False
    assert mechanical.gates["RUB-EXTRACT-05"] == "pending_llm"
