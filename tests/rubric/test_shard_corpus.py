"""ShardCorpus adapter: SHACL criteria computed on a corpus, AE3, and the pass rule (R7)."""
from __future__ import annotations

from pathlib import Path

import pytest

from folio_insights.rubric.adapters import AdapterError, ShardCorpus
from folio_insights.rubric.criteria import JUDGED_CRITERIA
from folio_insights.rubric.harness import score

from tests.rubric.conftest import (
    RUSSIA,
    SHARD_SPANS,
    SOURCE,
    SOURCE_FILE,
    build_corpus,
    judged_all,
)

pytestmark = pytest.mark.storage
CORPUS = "rubric-corpus"


@pytest.fixture
def sources(tmp_path: Path) -> Path:
    d = tmp_path / "sources"
    d.mkdir()
    (d / SOURCE_FILE).write_text(SOURCE, encoding="utf-8")
    return d


async def test_ae3_no_judged_scores_reports_five_det_numbers(
    tmp_path: Path, sources: Path, oracle  # noqa: ANN001
) -> None:
    """AE3: all five DET criteria with numbers, publishable false, nine not_scored."""
    root = tmp_path / "storage"
    shards = await build_corpus(root)
    art = await ShardCorpus.load(root, CORPUS, sources)
    assert art.kind == "shard_corpus" and len(art.units) == len(shards)
    report = score(art, oracle)
    for cid in ("RUB-EXTRACT-03", "RUB-EXTRACT-05", "RUB-EXTRACT-09",
                "RUB-EXTRACT-10", "RUB-EXTRACT-11"):
        c = report.criterion(cid)
        assert c.status == "computed" and isinstance(c.score, float), cid
    assert report.criterion("RUB-EXTRACT-05").score == 3.0
    assert report.criterion("RUB-EXTRACT-10").score == 3.0  # signed shards: no warnings
    assert report.criterion("RUB-EXTRACT-11").score == 3.0
    assert report.criterion("RUB-EXTRACT-03").det.details["tags_checked"] == 2  # the references
    assert report.not_scored == tuple(JUDGED_CRITERIA)
    assert report.not_scored == ("RUB-EXTRACT-01", "RUB-EXTRACT-02", "RUB-EXTRACT-04",
                                 "RUB-EXTRACT-06", "RUB-EXTRACT-07", "RUB-EXTRACT-08",
                                 "RUB-EXTRACT-12", "RUB-EXTRACT-13", "RUB-EXTRACT-14")
    assert report.publishable is False


async def test_publishable_only_with_green_gates_judged_scores_and_threshold(
    tmp_path: Path, sources: Path, oracle  # noqa: ANN001
) -> None:
    root = tmp_path / "storage"
    await build_corpus(root)
    art = await ShardCorpus.load(root, CORPUS, sources)
    ids = [u.id for u in art.units]

    good = score(art, oracle, judged_all(3, unit_ids=ids))
    assert good.publishable is True, good.reasons
    assert good.reasons == ()
    assert good.normalized == 1.0

    # Weighted below 0.80: judged criteria at 1.5 (-06 per unit at 3)
    # -> (43*3 + 57*1.5) / 300 = 0.715 (the five DET criteria carry 31 of the weight).
    low = score(art, oracle, judged_all(1.5, unit_ids=ids))
    assert low.normalized == pytest.approx(0.715)
    assert low.publishable is False
    assert any("below 0.80" in r for r in low.reasons)

    # Completeness floor: -08 at 1 fails even when the weighted score clears 0.80.
    judged = judged_all(3, unit_ids=ids, **{"RUB-EXTRACT-08": 1})
    floor = score(art, oracle, judged)
    assert floor.normalized is not None and floor.normalized >= 0.80
    assert floor.publishable is False
    assert any("completeness floor" in r for r in floor.reasons)

    # One fabricated unit is an automatic fail, never averaged away.
    judged = judged_all(3, unit_ids=ids)
    judged["scores"]["RUB-EXTRACT-06"] = {"per_unit": {ids[0]: 0, ids[1]: 3}}
    fab = score(art, oracle, judged)
    assert fab.publishable is False and "gate RUB-EXTRACT-06 failed" in fab.reasons

    # The proposed-class bonus never offsets a gate.
    judged["bonus"] = {"genuine_proposed_gaps": 5}
    assert score(art, oracle, judged).publishable is False


async def test_proposed_class_bonus_is_capped(tmp_path: Path, sources: Path, oracle) -> None:  # noqa: ANN001
    root = tmp_path / "storage"
    await build_corpus(root)
    art = await ShardCorpus.load(root, CORPUS, sources)
    ids = [u.id for u in art.units]
    # Judged criteria at 1.9, -06 per unit at 3, -08 at the floor 2
    # -> (43*3 + 14*2 + 43*1.9) / 300 = 0.795667: below the bar by itself, above it with
    # one genuine gap (+0.05).
    judged = judged_all(1.9, unit_ids=ids, **{"RUB-EXTRACT-08": 2})
    assert score(art, oracle, judged).publishable is False
    judged["bonus"] = {"genuine_proposed_gaps": 1}
    with_bonus = score(art, oracle, judged)
    assert with_bonus.bonus == 0.05 and with_bonus.publishable is True
    assert with_bonus.normalized == pytest.approx(0.845667)
    judged["bonus"] = {"genuine_proposed_gaps": 9}
    assert score(art, oracle, judged).bonus == 0.10


async def test_unresolved_shard_sources_are_not_scored(tmp_path: Path, oracle) -> None:  # noqa: ANN001
    root = tmp_path / "storage"
    await build_corpus(root)
    art = await ShardCorpus.load(root, CORPUS)  # no sources directory
    c = score(art, oracle).criterion("RUB-EXTRACT-05")
    assert c.status == "not_scored" and c.score is None and c.gate is None
    assert "could not be resolved" in c.reason


async def test_shard_with_unverifiable_span_fails_anchoring(
    tmp_path: Path, sources: Path, oracle  # noqa: ANN001
) -> None:
    root = tmp_path / "storage"
    spans = (SHARD_SPANS[0], "Always file a motion in limine on expert fees.")
    await build_corpus(root, spans=spans)
    report = score(await ShardCorpus.load(root, CORPUS, sources), oracle)
    c = report.criterion("RUB-EXTRACT-05")
    assert c.gate == "fail" and sorted(e["score"] for e in c.det.per_unit.values()) == [0, 3]


async def test_dangling_dependency_fails_structural_integrity(
    tmp_path: Path, sources: Path, oracle  # noqa: ANN001
) -> None:
    root = tmp_path / "storage"
    ghost = "urn:folio:shard/" + "f" * 32
    await build_corpus(root, extra={2: {"depends_on_shards": [ghost]}})
    report = score(await ShardCorpus.load(root, CORPUS, sources), oracle)
    c = report.criterion("RUB-EXTRACT-11")
    assert c.score == 0.0 and c.gate == "fail"
    checks = {ch["name"]: ch for ch in c.det.details["checks"]}
    assert checks["Referential Integrity"]["status"] == "FAIL"
    assert any(ghost in m for m in checks["Referential Integrity"]["messages"])
    assert checks["IRI Uniqueness"]["status"] == "PASS"
    assert checks["Namespace Consistency"]["status"] == "PASS"


async def test_internal_dependency_is_not_dangling(tmp_path: Path, sources: Path, oracle) -> None:  # noqa: ANN001
    root = tmp_path / "storage"
    first = "urn:folio:shard/" + f"{1:032x}"
    await build_corpus(root, extra={2: {"depends_on_shards": [first], "elaborates": [first]}})
    report = score(await ShardCorpus.load(root, CORPUS, sources), oracle)
    assert report.criterion("RUB-EXTRACT-11").score == 3.0


async def test_unsigned_shards_conform_with_warnings(tmp_path: Path, sources: Path, oracle) -> None:  # noqa: ANN001
    root = tmp_path / "storage"
    await build_corpus(root, sign=False)
    c = score(await ShardCorpus.load(root, CORPUS, sources), oracle).criterion("RUB-EXTRACT-10")
    assert c.score == 2.0 and c.gate == "pass" and c.det.details["warnings"] > 0


async def test_shard_reference_iris_are_checked_for_existence(
    tmp_path: Path, sources: Path, oracle  # noqa: ANN001
) -> None:
    root = tmp_path / "storage"
    await build_corpus(root, reference="https://folio.openlegalstandard.org/SYNTHETIC-NOT-A-REAL-CONCEPT")
    c = score(await ShardCorpus.load(root, CORPUS, sources), oracle).criterion("RUB-EXTRACT-03")
    assert c.gate == "soft_fail" and c.score == 0.0
    root2 = tmp_path / "storage2"
    await build_corpus(root2, reference=RUSSIA)
    c2 = score(await ShardCorpus.load(root2, CORPUS, sources), oracle).criterion("RUB-EXTRACT-03")
    assert c2.gate == "pass"  # exists; a shard claims no branch


async def test_file_uri_source_resolves_inside_sources_dir(
    tmp_path: Path, sources: Path, oracle  # noqa: ANN001
) -> None:
    root = tmp_path / "storage"
    uri = (sources / SOURCE_FILE).as_uri()
    await build_corpus(root, extra={1: {"source_uri": uri}, 2: {"source_uri": uri}})
    art = await ShardCorpus.load(root, CORPUS, sources)
    assert all(u.anchor.source_text == SOURCE for u in art.units)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    confined = await ShardCorpus.load(root, CORPUS, elsewhere)
    assert {u.anchor.source_error for u in confined.units} == {"source_outside_sources_dir"}


async def test_unknown_corpus_is_refused_and_not_created(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    with pytest.raises(AdapterError, match="no corpus"):
        await ShardCorpus.load(root, "absent")
    assert not (root / "journal.sqlite3").exists()
