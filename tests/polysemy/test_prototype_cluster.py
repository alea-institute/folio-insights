"""Wave-0 placeholder for prototype cluster centroid math. Impl lands in 01-03."""
import pytest

pytestmark = pytest.mark.polysemy_spike


@pytest.mark.xfail(reason="Wave-0 scaffold; impl in 01-03", strict=False)
def test_centroid_per_framework() -> None:
    """Prototype cluster computes centroid per framework via sentence-transformers
    (all-MiniLM-L6-v2 reused from services/boundary/semantic.py, per CONTEXT.md
    Claude's Discretion)."""
    raise NotImplementedError("Wave-0 placeholder")
