"""FP-rate + Wilson CI + LLM audit-pass test suite (Plan 01-06 RED → GREEN).

Flips the three Wave-0 xfails to real tests plus nine additional regression
guards (A6 detector_confidence, stale `.reason` attr, scipy absence, OQ-5
single-flag, etc). Every fixture constructs a canonical 01-02
DispositionRecord (proposed_fork required, detector_verdict: dict,
reviewed_at_iso) and canned PolysemyVerdicts (polysemy_vs_homonymy_reasoning
+ rationale — never `.reason`).

D-4 lock: the LLM audit pass emits DISAGREEMENTS ONLY.
PRINCIPLE-06 lock (Phase 9 U6, KTD9): the Wilson CI UPPER bound is the gate,
not the point estimate and not the lower bound; an FP is a detector miscall
(detector said polysemy, reviewer rejected with a rationale).
QUALITY-03 lock: wilson_score_interval is hand-coded — NO scipy import.
"""
from __future__ import annotations

import pathlib
import re
from unittest import mock

import pytest

from folio_insights.polysemy.detector import PolysemyVerdict
from folio_insights.polysemy.dispositions import (
    DispositionRecord,
    ProposedFork,
    append_disposition,
)

pytestmark = pytest.mark.polysemy_spike


# ---------------------------------------------------------------------------
# Canonical fixtures — field-perfect with 01-02 DispositionRecord + 01-03
# PolysemyVerdict schemas. Do NOT drift (see plan <critical> block).
# ---------------------------------------------------------------------------


def _sample_record(
    *,
    cluster_id: str = "fi:PrototypeCluster_deadbeef",
    term: str = "consideration",
    decision: str = "accept",
    rationale: str = "ok",
    detector_decision: str = "polysemy",
) -> DispositionRecord:
    """Build a canonical DispositionRecord — matches 01-02 Task 1 schema exactly."""
    return DispositionRecord(
        cluster_id=cluster_id,
        term=term,
        proposed_fork=ProposedFork(
            cluster_id=cluster_id,
            term=term,
            frameworks=["CommonLaw", "Restatement", "FRE"],
            uses_analogousTo=False,
            distinction_kind="analogica",
        ),
        decision=decision,
        rationale=rationale,
        reviewer_did="did:key:z6Mkpz0000000000000000000000000000000000000000",
        reviewed_at_iso="2026-04-23T12:00:00+00:00",
        detector_verdict={
            "kind": "rule",
            "decision": detector_decision,
            "rule_confidence": 0.72,
            "matched_rules": ["R1-R2-R3-pass"],
            "evidence_score": 0.67,
        },
    )


def _seed_jsonl(tmp_path: pathlib.Path, records: list[DispositionRecord]) -> pathlib.Path:
    """Write records as JSONL; returns the path."""
    p = tmp_path / "dispositions.jsonl"
    for r in records:
        append_disposition(r, p)
    return p


# ---------------------------------------------------------------------------
# Wilson CI tests (3)
# ---------------------------------------------------------------------------

def test_wilson_score_interval_basic() -> None:
    """wilson(5, 20) gives a 95% CI with lower~0.09, upper~0.49."""
    from folio_insights.polysemy.fp_audit import wilson_score_interval

    lower, upper = wilson_score_interval(5, 20)
    assert 0.08 < lower < 0.12, f"expected lower ~0.09, got {lower}"
    assert 0.45 < upper < 0.50, f"expected upper ~0.49, got {upper}"
    assert lower < upper


def test_wilson_score_interval_edge_cases() -> None:
    """n=0 → (0, 1); 0/20 lower==0; 20/20 upper==1."""
    from folio_insights.polysemy.fp_audit import wilson_score_interval

    assert wilson_score_interval(0, 0) == (0.0, 1.0)
    low_zero, _ = wilson_score_interval(0, 20)
    assert low_zero == 0.0
    _, upper_all = wilson_score_interval(20, 20)
    assert upper_all == 1.0


def test_wilson_score_interval_no_scipy_import() -> None:
    """QUALITY-03 image-size discipline: NO scipy in fp_audit.py."""
    from folio_insights.polysemy import fp_audit

    source = pathlib.Path(fp_audit.__file__).read_text(encoding="utf-8")
    assert "import scipy" not in source
    assert "from scipy" not in source


# ---------------------------------------------------------------------------
# compute_fp_rate tests (3)
# ---------------------------------------------------------------------------

def _append_raw(path: pathlib.Path, record: DispositionRecord) -> None:
    """Write a record the way a Phase 1 log holds it, bypassing the write check
    (``append_disposition`` now refuses a reject without a rationale)."""
    with path.open("a", encoding="utf-8") as fh:
        fh.write(record.model_dump_json() + "\n")


def test_compute_fp_rate_counts_detector_miscalls_only(tmp_path: pathlib.Path) -> None:
    """KTD9: an FP is a detector miscall — detector said polysemy, the reviewer
    rejected it WITH a rationale. Rejects of a non-polysemy verdict agree with
    the detector; an empty-rationale reject is invalid: not an FP, not in N.

    Mix: 3 accept + 2 reject-with-rationale of a polysemy call (2 FPs) +
    1 reject of a coincidence call (agreement) + 1 modify + 1 legacy
    empty-rationale reject (invalid) -> 2 FPs over N = 7.
    """
    from folio_insights.polysemy.fp_audit import compute_fp_rate

    path = _seed_jsonl(tmp_path, [
        _sample_record(decision="accept", rationale="ok1"),
        _sample_record(decision="accept", rationale="ok2"),
        _sample_record(decision="accept", rationale="ok3"),
        _sample_record(decision="reject", rationale="framework conflict"),       # FP
        _sample_record(decision="reject", rationale="axiom mismatch"),           # FP
        _sample_record(decision="reject", rationale="agrees: no fork",
                       detector_decision="coincidence"),                        # not an FP
        _sample_record(decision="modify", rationale="distinguo override"),
    ])
    _append_raw(path, _sample_record(decision="reject", rationale="  "))       # invalid

    result = compute_fp_rate(path)
    assert result["total"] == 7
    assert result["false_positives"] == 2
    assert result["invalid_dispositions"] == 1
    assert abs(result["fp_rate"] - 2 / 7) < 1e-9


def test_empty_rationale_reject_is_never_an_fp(tmp_path: pathlib.Path) -> None:
    """The Phase 1 definition counted exactly these; KTD9 counts none of them."""
    from folio_insights.polysemy.fp_audit import compute_fp_rate

    path = tmp_path / "dispositions.jsonl"
    for _ in range(3):
        _append_raw(path, _sample_record(decision="reject", rationale=""))
    _append_raw(path, _sample_record(decision="accept"))
    result = compute_fp_rate(path)
    assert result["false_positives"] == 0
    assert result["total"] == 1
    assert result["invalid_dispositions"] == 3


def test_compute_fp_rate_reports_wilson_ci(tmp_path: pathlib.Path) -> None:
    """Returned dict MUST have keys {total, false_positives, fp_rate, ci_lower, ci_upper, status}."""
    from folio_insights.polysemy.fp_audit import compute_fp_rate

    records = [_sample_record(decision="accept") for _ in range(5)] + [
        _sample_record(decision="reject", rationale="miscall")
    ]
    path = _seed_jsonl(tmp_path, records)

    result = compute_fp_rate(path)
    expected_keys = {"total", "false_positives", "fp_rate", "ci_lower", "ci_upper", "status"}
    assert expected_keys.issubset(result.keys())
    assert 0.0 <= result["ci_lower"] <= result["fp_rate"] <= result["ci_upper"] <= 1.0


def test_fp_rate_gate_reads_the_upper_bound(tmp_path: pathlib.Path) -> None:
    """Landmine demo: 1/20 point estimate = 5% but Wilson ci_upper > 10%, so the gate fails."""
    from folio_insights.polysemy.fp_audit import compute_fp_rate

    records = [_sample_record(decision="accept") for _ in range(19)] + [
        _sample_record(decision="reject", rationale="miscall")
    ]
    path = _seed_jsonl(tmp_path, records)

    result = compute_fp_rate(path)
    assert result["fp_rate"] < 0.10, f"point estimate should be <10%, got {result['fp_rate']}"
    assert result["ci_upper"] > 0.10, result["ci_upper"]
    assert result["status"] == "fail"


# ---------------------------------------------------------------------------
# LLM audit-pass tests (2) — disagreements only (D-4)
# ---------------------------------------------------------------------------

def test_audit_disagreements_only(tmp_path: pathlib.Path) -> None:
    """Only disagreement rows land in the report. Agreements are silently counted.

    Fixture: 4 records (2 agreement, 2 disagreement) with canned PolysemyVerdicts
    constructed with canonical field names (polysemy_vs_homonymy_reasoning +
    rationale — NEVER `.reason`).
    """
    from folio_insights.polysemy import fp_audit

    records = [
        # agreement: reviewer=accept, llm=polysemy
        _sample_record(cluster_id="fi:C_agree1", decision="accept", rationale="ok"),
        # disagreement: reviewer=accept, llm=homonymy
        _sample_record(cluster_id="fi:C_disagree1", decision="accept", rationale="ok"),
        # agreement: reviewer=reject, llm=homonymy
        _sample_record(cluster_id="fi:C_agree2", decision="reject", rationale="not same"),
        # disagreement: reviewer=reject, llm=polysemy
        _sample_record(cluster_id="fi:C_disagree2", decision="reject", rationale="not same"),
    ]
    path = _seed_jsonl(tmp_path, records)
    report_path = tmp_path / "fp-labeling-audit.md"

    # Canonical PolysemyVerdict constructions — field-perfect with 01-03.
    verdicts_by_cluster = {
        "fi:C_agree1": PolysemyVerdict(
            decision="polysemy",
            polysemy_vs_homonymy_reasoning="Same doctrine across CL/Restatement.",
            rationale="Bargained-for exchange axiom is common.",
        ),
        "fi:C_disagree1": PolysemyVerdict(
            decision="homonymy",
            polysemy_vs_homonymy_reasoning="FRE 'consideration' = relevance weighing.",
            rationale="Different concept, shared spelling only.",
        ),
        "fi:C_agree2": PolysemyVerdict(
            decision="homonymy",
            polysemy_vs_homonymy_reasoning="Surface overlap only; concepts disjoint.",
            rationale="Reviewer correctly rejected.",
        ),
        "fi:C_disagree2": PolysemyVerdict(
            decision="polysemy",
            polysemy_vs_homonymy_reasoning="Prime analogate + proportional relation present.",
            rationale="LLM thinks a fork is warranted.",
        ),
    }

    # Fake client: records the calls and returns canned responses by cluster_id.
    class _FakeClient:
        @staticmethod
        def structured_model_sync(prompt, response_model, **_kwargs):
            for cid, v in verdicts_by_cluster.items():
                if cid in prompt:
                    return v
            raise RuntimeError(f"no canned verdict for prompt: {prompt!r}")

    fake_bridge = mock.MagicMock()
    fake_bridge.get_llm_for_task.return_value = _FakeClient()

    result = fp_audit.run_llm_audit_pass(
        path, report_path,
        llm_provider="claude-haiku-4-5",
        llm_bridge=fake_bridge,
    )

    assert result["total"] == 4
    assert result["agreements"] == 2
    assert result["disagreements"] == 2

    report = report_path.read_text(encoding="utf-8")
    assert "fi:C_disagree1" in report
    assert "fi:C_disagree2" in report
    assert "fi:C_agree1" not in report, "agreements must NOT appear in report (D-4)"
    assert "fi:C_agree2" not in report, "agreements must NOT appear in report (D-4)"


def test_audit_llm_swallow_exception(tmp_path: pathlib.Path) -> None:
    """LLM failure on one record must not crash the whole audit run."""
    from folio_insights.polysemy import fp_audit

    records = [
        _sample_record(cluster_id="fi:C_ok1", decision="accept", rationale="ok"),
        _sample_record(cluster_id="fi:C_crash", decision="accept", rationale="ok"),
        _sample_record(cluster_id="fi:C_ok2", decision="reject", rationale="bad"),
    ]
    path = _seed_jsonl(tmp_path, records)
    report_path = tmp_path / "fp-labeling-audit.md"

    class _FakeClient:
        @staticmethod
        def structured_model_sync(prompt, response_model, **_kwargs):
            if "fi:C_crash" in prompt:
                raise RuntimeError("network blip")
            if "fi:C_ok1" in prompt:
                return PolysemyVerdict(
                    decision="polysemy",
                    polysemy_vs_homonymy_reasoning="agree",
                    rationale="ok",
                )
            if "fi:C_ok2" in prompt:
                return PolysemyVerdict(
                    decision="homonymy",
                    polysemy_vs_homonymy_reasoning="agree",
                    rationale="ok",
                )
            raise RuntimeError("unexpected")

    fake_bridge = mock.MagicMock()
    fake_bridge.get_llm_for_task.return_value = _FakeClient()

    result = fp_audit.run_llm_audit_pass(
        path, report_path,
        llm_provider="claude-haiku-4-5",
        llm_bridge=fake_bridge,
    )

    # Total = 3, but fi:C_crash is skipped (not counted as agreement or disagreement).
    assert result["total"] == 3
    assert result["agreements"] == 2
    assert result["disagreements"] == 0


# ---------------------------------------------------------------------------
# Kappa caveat test (1)
# ---------------------------------------------------------------------------

def test_kappa_labeled_as_signal(tmp_path: pathlib.Path) -> None:
    """compute_fp_rate result must carry both `kappa` and a `kappa_caveat` string
    containing 'signal' OR 'not verdict' (RESEARCH.md §Measurement Landmines)."""
    from folio_insights.polysemy.fp_audit import compute_fp_rate

    records = [
        _sample_record(decision="accept"),
        _sample_record(decision="reject", rationale="x", detector_decision="homonymy"),
    ]
    path = _seed_jsonl(tmp_path, records)

    result = compute_fp_rate(path)
    assert "kappa" in result
    assert "kappa_caveat" in result
    caveat_lower = result["kappa_caveat"].lower()
    assert "signal" in caveat_lower or "not verdict" in caveat_lower


# ---------------------------------------------------------------------------
# Regression guards (3)
# ---------------------------------------------------------------------------

def test_no_detector_confidence_float_regression() -> None:
    """Pitfall A6 guard: `detector_confidence` string MUST NOT appear in fp_audit.py.

    Canonical schema (01-02) uses `detector_verdict: dict` snapshot — NOT a
    float `detector_confidence`.
    """
    from folio_insights.polysemy import fp_audit

    source = pathlib.Path(fp_audit.__file__).read_text(encoding="utf-8")
    assert "detector_confidence" not in source


def test_no_stale_reason_attribute_regression() -> None:
    """Stale `.reason` attribute on PolysemyVerdict raises AttributeError.

    Canonical PolysemyVerdict (01-03) has `polysemy_vs_homonymy_reasoning` +
    `rationale` — there is NO `.reason` attribute. The regex `\\.reason\\b`
    catches `.reason`, `.reason,`, `.reason)` without matching the substring
    inside `polysemy_vs_homonymy_reasoning`.
    """
    from folio_insights.polysemy import fp_audit

    source = pathlib.Path(fp_audit.__file__).read_text(encoding="utf-8")
    match = re.search(r"\.reason\b", source)
    assert match is None, (
        f"Stale `.reason` access found in fp_audit.py at offset {match.start() if match else '?'}; "
        f"canonical PolysemyVerdict uses polysemy_vs_homonymy_reasoning + rationale."
    )


def test_single_llm_provider_flag_in_audit() -> None:
    """OQ-5 RESOLVED regression guard: audit subcommand has exactly ONE
    --llm-provider option and ZERO --llm-model occurrences."""
    # Importing the polysemy package triggers cli registration.
    from folio_insights.polysemy.cli import polysemy as polysemy_group

    # Force a fresh import of cli.py text for source inspection.
    import folio_insights.polysemy.cli as cli_module
    source = pathlib.Path(cli_module.__file__).read_text(encoding="utf-8")
    assert '"--llm-model"' not in source, "OQ-5 W1: --llm-model must NOT appear"
    assert "--llm-model" not in source, "OQ-5 W1: --llm-model must NOT appear (any form)"

    audit_cmd = polysemy_group.commands["audit"]
    llm_provider_options = [
        p for p in audit_cmd.params
        if any(opt == "--llm-provider" for opt in getattr(p, "opts", []))
    ]
    assert len(llm_provider_options) == 1, (
        f"audit subcommand must carry exactly one --llm-provider option; "
        f"found {len(llm_provider_options)}"
    )
    # Affirmatively: no --llm-model on audit.
    llm_model_options = [
        p for p in audit_cmd.params
        if any(opt == "--llm-model" for opt in getattr(p, "opts", []))
    ]
    assert llm_model_options == [], "audit subcommand must NOT carry --llm-model"
