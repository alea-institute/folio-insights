"""Phase 9 U8 — the seven principles together on one synthetic corpus.

One end-to-end run (``bench.phase9_rollup.run_phase9_rollup``) over the
synthetic multi-framework corpus (``bench.multiframework``): every R4–R10
acceptance check is asserted on that single run's report. Disposable roots,
a generated did:key admin, deterministic fakes for every model (NLI,
framework LLM, BFO LLM, polysemy Rule 4 LLM), no network (the embedding
model loads offline from the local cache). HermiT steps run when a JRE and
owlready2 are present and are reported as skipped otherwise.

The P6 FP gate is reported as computed: the test asserts the roll-up carries
exactly what ``polysemy gate`` prints, never that it passes.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from folio_insights.bench.multiframework import (
    REGISTERED_FRAMEWORK,
    UNTYPEABLE_PREFIX,
    MultiFrameworkCorpusGenerator,
    unit_iri,
)
from folio_insights.bench.phase9_rollup import RollupFakes, run_phase9_rollup
from folio_insights.bfo.classifier import BfoLLMChoice
from folio_insights.frameworks.detector import FrameworkLLMChoice
from folio_insights.polysemy.labeled_set import AlwaysPolysemyLLM
from folio_insights.validation.hermit import hermit_available

from tests.storage.conftest import new_identity

LABELED_SET = Path(__file__).resolve().parents[1] / "polysemy" / "fixtures" / "labeled_set.json"


class NegationNli:
    """Contradiction iff two texts differ by exactly one inserted ``not``."""

    name = "nli:fake-negation"

    @staticmethod
    def _norm(text: str) -> str:
        return " ".join(text.lower().replace(".", "").split())

    def contradiction_probabilities(self, pairs):  # noqa: ANN001, ANN201
        out = []
        for a, b in pairs:
            na, nb = self._norm(a), self._norm(b)
            negated = na != nb and (na.replace(" not ", " ") == nb or nb.replace(" not ", " ") == na)
            out.append(0.95 if negated else 0.02)
        return out


class TitleFrameworkLLM:
    """Places the English source; for the rogue source it tries to mint an ID."""

    def choose(self, metadata, candidates):  # noqa: ANN001, ANN201
        if metadata.title == "synthetic english source":
            return FrameworkLLMChoice(framework_id="uk.england.common_law", confidence=0.9)
        if metadata.title == "rogue synthetic source":
            return FrameworkLLMChoice(framework_id="zz.unregistered.body", confidence=0.99)
        return FrameworkLLMChoice()


class SubjectBfoLLM:
    """Types every untagged subject except the ones marked untypeable."""

    def classify(self, item):  # noqa: ANN001, ANN201
        if item.subject.startswith(UNTYPEABLE_PREFIX):
            return BfoLLMChoice()
        return BfoLLMChoice(category="continuant_dependent", confidence=0.9)


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """No Hugging Face network calls: the embedding model loads from cache."""
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    try:
        from huggingface_hub import constants
    except ImportError:  # pragma: no cover
        return
    monkeypatch.setattr(constants, "HF_HUB_OFFLINE", True, raising=False)


def _fakes() -> RollupFakes:
    return RollupFakes(nli=NegationNli(), framework_llm=TitleFrameworkLLM(),
                       bfo_llm=SubjectBfoLLM(), polysemy_llm=AlwaysPolysemyLLM())


async def _rollup(tmp_path: Path, **kw):  # noqa: ANN003, ANN202
    admin = new_identity()
    generator = MultiFrameworkCorpusGenerator(seed=kw.pop("seed", 9),
                                              units_per_source=kw.pop("units_per_source", 8))
    report = await run_phase9_rollup(
        tmp_path / "storage", signing_key=admin.sk, did=admin.did, fakes=_fakes(),
        labeled_set=LABELED_SET, workdir=tmp_path / "work", generator=generator, **kw,
    )
    return generator.generate(), report


# ── the generator ─────────────────────────────────────────────────────────


def test_corpus_generator_is_deterministic_and_seeded() -> None:
    generator = MultiFrameworkCorpusGenerator(seed=9)
    a = generator.generate()
    b = MultiFrameworkCorpusGenerator(seed=9).generate()
    c = MultiFrameworkCorpusGenerator(seed=10).generate()
    assert a == b
    assert generator.generate() == a  # a second call on one generator yields the same corpus
    assert a != c
    assert [s.key for s in a.sources] == [s.key for s in c.sources]  # only values vary
    keys = [u.key for _, u in a.units()]
    assert len(keys) == len(set(keys))
    iris = [unit_iri(s.uri, u.span) for s, u in a.units()]
    assert len(iris) == len(set(iris))
    assert set(a.frameworks) >= {"us.common_law", "us.louisiana.civil_code", "us.federal.fre",
                                 "us.federal.frcp", "uk.england.common_law",
                                 REGISTERED_FRAMEWORK.id}


def test_generator_rejects_a_corpus_too_small_to_plant_in() -> None:
    with pytest.raises(ValueError):
        MultiFrameworkCorpusGenerator(units_per_source=3)


# ── the roll-up ───────────────────────────────────────────────────────────


# One run is ~12-30 s here (embedding-model load and two JVM starts dominate),
# above the suite's 30 s default per-test timeout on a loaded machine but well
# under the ~60 s at which it would move to the slow suite.
@pytest.mark.timeout(180)
async def test_phase9_rollup_all_principles_on_one_corpus(tmp_path: Path, offline: None) -> None:
    data, report = await _rollup(tmp_path)
    print("PHASE9_ROLLUP_REPORT " + json.dumps(report, sort_keys=True))
    (tmp_path / "rollup-report.json").write_text(json.dumps(report, indent=2, sort_keys=True))
    p = report["principles"]
    hermit = hermit_available()[0]

    # Corpus: every framework but the rogue source's minted, hardware recorded.
    assert report["corpus"]["sources_minted"] == len(data.sources) - 1
    assert set(report["corpus"]["frameworks"]) == set(data.frameworks)
    assert report["hardware"]["logical_cpus"]
    assert report["timings_s"]["total"] > 0

    # P2 / R5: registry, detection paths, gate, write check, valid time.
    p2 = p["P2"]
    assert p2["expected_frameworks_matched"] and p2["deterministic"]
    assert p2["registered"] == [REGISTERED_FRAMEWORK.id]
    assert set(p2["detection_sources"]) == {"metadata", "citation", "llm"}
    assert p2["detections"]["rogue"]["gate"] is False
    assert p2["detections"]["rogue"]["framework_id"] is None
    assert p2["detections"]["la-a"]["migration_warnings"]
    assert p2["detections"]["fre-2011"]["valid_time"] == [
        "2011-12-01T00:00:00+00:00", "2023-12-01T00:00:00+00:00"]
    assert p2["unregistered_write_refused"]
    assert p2["rule_at_t"]["picks_version"]

    # P7 / R10: >= 95% non-default, defaults recorded, strict refuses.
    p7 = p["P7"]
    assert p7["coverage"] >= 0.95
    assert p7["provenance"]["unrecorded"] == 0
    assert p7["provenance"]["rule"] > 0 and p7["provenance"]["llm"] > 0
    assert p7["provenance"]["default"] == p7["defaults"] > 0
    assert p7["strict_refused_defaults"] == p7["defaults"]
    assert p7["sources_reported"] == report["corpus"]["sources_minted"]
    assert p7["projected_spine_class"] == report["corpus"]["shards"]

    # P3 / R6: DAG, cycle refused and reported, revision effects derived.
    p3 = p["P3"]
    assert p3["dag"]["acyclic"] and p3["dag"]["edges"] > 0
    assert p3["dag"]["build_seconds"] < 5.0
    assert len(p3["planted_cycle_refused_by_storage"]) == 4  # a -> b -> c -> a
    assert p3["planted_cycle_journal_unchanged"]
    assert len(p3["planted_cycle_reported"]) == 1 and p3["cycle_is_planted"]
    assert p3["retraction_preview"] == {"policy": "prefer_latest", "auto_rederive": 2,
                                        "aporetic": 0, "review_needed": 1, "depths": [1, 1, 2]}
    state = p3["effective_state"]
    assert state["retracted"] == "retracted"
    assert state["successor"] == "current"
    assert state["direct_dependents"] == ["auto_rederive", "auto_rederive"]
    assert state["deep_dependents"] == ["review_needed"]
    assert state["superseded"] == "superseded" and state["superseding"] == "current"
    assert state["superseded_valid_time_end"] == "2023-12-01T00:00:00+00:00"
    assert state["contested"] == "contested" and state["resolved"] == "resolved"

    # P4 / R7: EL by default, expressive warns, a non-EL axiom is named.
    p4 = p["P4"]
    assert p4["el_export"] == {"profile": "EL", "el_conformant": True, "reasoner": "hermit"}
    assert p4["shipped_tbox_el_violations"] == 0
    assert p4["expressive_export"]["profile"] == "DL" and p4["expressive_export"]["warnings"] >= 1
    [planted] = p4["planted_violation"]
    assert planted["rule"] == "inverse-functional-property"
    assert "urn:synthetic:tbox#hasSyntheticId" in json.dumps(planted)
    if hermit:
        assert p4["hermit_dl_tbox"]["consistent"] is True
    else:
        assert p4["hermit_dl_tbox"] == "skipped"

    # P5 / R8: closed only inside the declared island; open elsewhere.
    p5 = p["P5"]
    assert p5["declared_scopes_in_store"] == []
    assert p5["membership_source"] == "persisted signed declaration"
    assert p5["persisted_scopes"] == [p5["scope"]]
    assert p5["open_lacking"]["world_assumption"] == "open" and p5["open_lacking"]["count"] is None
    assert p5["open_lacking"]["incomplete_note"]
    assert p5["closed_lacking"] == {
        "world_assumption": "closed", "count": p5["expected_lacking"], "incomplete_note": False,
        "total_instances": p5["island_members"],
        "asserted_with_property": p5["island_members"] - p5["expected_lacking"],
    }
    assert p5["open_related"]["world_assumption"] == "open"
    assert p5["closed_related"]["world_assumption"] == "closed"
    assert p5["open_related"]["count"] == p5["closed_related"]["count"] == 1
    assert p5["reopened_lacking"] == p5["closed_lacking"]

    # P1 / R4: the planted pair flagged with cluster context and strategies.
    p1 = p["P1"]
    [contra] = p1["planted_contradiction"]
    assert contra["checker"] == "nli" and contra["clusters"] >= 1 and contra["proposals"]
    [cite] = p1["planted_cross_framework_citation"]
    assert cite["checker"] == "crossref" and cite["proposals"]
    assert p1["coverage_gaps"] == ["task-gap"]
    assert p1["applied"] is False and p1["journal_unchanged"]
    if hermit:
        assert p1["checkers"]["hermit"] == "available"
        [clash] = p1["planted_formal_clash"]
        assert clash["checker"] == "hermit"
    else:
        assert p1["planted_formal_clash"] == []
        assert "nli_fallback" in p1["summary"]["cluster_modes"]

    # P6 / R9: candidates from P1 + P2, the seeded term passes Rule 1, the FP
    # gate is whatever `polysemy gate` computes.
    p6 = p["P6"]
    assert p6["candidates"] >= 1 and p6["journal_unchanged"] and p6["fork_applied"] is False
    assert "R1-no-conflict" not in p6["planted_term"]["matched_rules"]
    assert p6["planted_term"]["decision"] == "polysemy"  # passed Rules 1-3, as the plan records
    gate = p6["fp_gate"]
    assert gate["status"] in {"pass", "provisional", "fail"}
    assert (gate["status"] == "fail") == (gate["wilson_upper"] > gate["threshold"])
    cli = CliRunner().invoke(_cli(), ["polysemy", "gate", "--labeled-set", str(LABELED_SET)],
                             terminal_width=200)
    assert cli.exit_code == 0, cli.output
    assert re.search(rf"status\s*│\s*{gate['status']}\b", cli.output)
    assert f"{gate['wilson_upper']:.1%}" in cli.output
    assert f"N (valid dispositions) │ {gate['n']}" in re.sub(r" +│", " │", cli.output)

    # R1 / R2.
    assert report["cross_cutting"]["R1_undeclared"] == []
    assert report["cross_cutting"]["R2_shard_bytes_unchanged"]

    # Skips are recorded, never silent.
    assert bool(report["skipped"]) is (not hermit)


@pytest.mark.timeout(180)
async def test_rollup_without_hermit_reports_the_skips(tmp_path: Path, offline: None) -> None:
    """The no-JRE path, forced: HermiT steps are reported skipped with the
    reason, the formal clash goes unflagged (no NLI contradiction in it) and
    every other principle still holds on a smaller corpus."""
    _, report = await _rollup(tmp_path, units_per_source=6, seed=3, use_hermit=False)
    p = report["principles"]
    assert report["hermit"] != "available"
    assert len(report["skipped"]) == 2 and all("HermiT" in s for s in report["skipped"])
    assert p["P4"]["hermit_dl_tbox"] == "skipped" and "p4_hermit_dl_tbox" not in report["timings_s"]
    assert p["P1"]["checkers"]["hermit"] == "disabled"
    assert p["P1"]["planted_formal_clash"] == []
    assert len(p["P1"]["planted_contradiction"]) == 1
    assert p["P7"]["coverage"] >= 0.95
    assert p["P3"]["effective_state"]["direct_dependents"] == ["auto_rederive", "auto_rederive"]
    assert p["P5"]["closed_lacking"]["world_assumption"] == "closed"
    assert p["P2"]["expected_frameworks_matched"]
    assert report["cross_cutting"]["R2_shard_bytes_unchanged"]


def _cli():  # noqa: ANN202
    from folio_insights.cli import cli

    return cli
