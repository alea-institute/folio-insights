"""Wave-0 placeholder for FP-rate harness. Impl lands in 01-06."""
import pytest

pytestmark = pytest.mark.polysemy_spike


@pytest.mark.xfail(reason="Wave-0 scaffold; impl in 01-06", strict=False)
def test_fp_rate_within_target() -> None:
    """FP rate <= 10% on the hand-labeled gold-set fixture (PRINCIPLE-06 gate;
    target per PRD §16 Risk 2)."""
    raise NotImplementedError("Wave-0 placeholder")


@pytest.mark.xfail(reason="Wave-0 scaffold; impl in 01-06", strict=False)
def test_reports_wilson_ci() -> None:
    """FP-rate report includes Wilson 95% CI (D-4 lock; small-sample-safe CI)."""
    raise NotImplementedError("Wave-0 placeholder")


@pytest.mark.xfail(reason="Wave-0 scaffold; impl in 01-06", strict=False)
def test_audit_disagreements_only() -> None:
    """LLM audit pass (instructor-driven second labeler) reports disagreements
    only; user reconciles and provides authoritative labels (D-4 lock)."""
    raise NotImplementedError("Wave-0 placeholder")
