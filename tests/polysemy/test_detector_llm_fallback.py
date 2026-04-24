"""Wave-0 placeholder for detector LLM fallback. Impl lands in 01-03."""
import pytest

pytestmark = pytest.mark.polysemy_spike


@pytest.mark.xfail(reason="Wave-0 scaffold; impl in 01-03", strict=False)
def test_llm_fallback_returns_discriminated_union() -> None:
    """Instructor LLM fallback returns discriminated-union verdict (per A6:
    Literal[...] discriminated union, no numeric probability score)."""
    raise NotImplementedError("Wave-0 placeholder")
