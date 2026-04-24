"""Wave-0 placeholder for detector rule gates. Impl lands in 01-03."""
import pytest

pytestmark = pytest.mark.polysemy_spike


@pytest.mark.xfail(reason="Wave-0 scaffold; impl in 01-03", strict=False)
def test_rule1_axioms_not_contexts() -> None:
    """Rule 1: framework-conflicting axioms (not contexts) — SPARQL ASK over
    owl:disjointWith assertions in named graph urn:folio:corpus/consideration-spike."""
    raise NotImplementedError("Wave-0 placeholder")


@pytest.mark.xfail(reason="Wave-0 scaffold; impl in 01-03", strict=False)
def test_rule2_n_ge_3() -> None:
    """Rule 2: N >= 3 shards per framework gate (below that, detector returns
    `insufficient-evidence` rather than proposing a fork)."""
    raise NotImplementedError("Wave-0 placeholder")


@pytest.mark.xfail(reason="Wave-0 scaffold; impl in 01-03", strict=False)
def test_rule3_whitelist_threshold() -> None:
    """Rule 3: terms-of-art whitelist raises threshold to 0.8 (start value per
    PITFALLS #8 mitigation)."""
    raise NotImplementedError("Wave-0 placeholder")


@pytest.mark.xfail(reason="Wave-0 scaffold; impl in 01-03", strict=False)
def test_rule4_homonym_flag() -> None:
    """Rule 4: homonym whitelist triggers LLM fallback (per PHILOSOPHY.md
    L1247-1252 polysemy-vs-homonymy distinction)."""
    raise NotImplementedError("Wave-0 placeholder")
