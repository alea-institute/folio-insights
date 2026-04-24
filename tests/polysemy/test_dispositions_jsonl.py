"""Wave-0 placeholder for dispositions JSONL contract. Impl lands in 01-02."""
import pytest

pytestmark = pytest.mark.polysemy_spike


@pytest.mark.xfail(reason="Wave-0 scaffold; impl in 01-02", strict=False)
def test_jsonl_schema_matches_phase15_contract() -> None:
    """JSONL disposition matches Phase 15 consumer schema exactly:
    {cluster_id, proposed_fork, disposition, rationale, reviewer_did, ts,
    detector_confidence, schema_version} (D-3 lock; A7 sole consumer)."""
    raise NotImplementedError("Wave-0 placeholder")


@pytest.mark.xfail(reason="Wave-0 scaffold; impl in 01-02", strict=False)
def test_append_only() -> None:
    """Append-only semantics: no rewrite, no truncation — re-running review
    appends new rows rather than overwriting existing ones."""
    raise NotImplementedError("Wave-0 placeholder")
