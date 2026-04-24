"""Phase 1 polysemy detector — 4-rule gate + provider-agnostic LLM fallback.

Rules (CONTEXT.md D-2, PITFALLS L647-653):
  R1  SPARQL owl:disjointWith between term-scoped framework classes (OQ-1 lock).
      Authoritative for axiom conflict. Embedding distance is NOT a fallback.
  R2  N ≥ 3 shards per framework (PITFALLS L651). Otherwise insufficient-evidence.
  R3  TERMS_OF_ART raise threshold to 0.8 (PITFALLS L652).
  R4  HOMONYMS force LLM-fallback (CONTEXT.md D-2 Rule 4).

Centroid cosine distance is an EVIDENCE SCORE surfaced on every verdict
(RuleVerdict.evidence_score, LLMVerdict.evidence_score) — never the final
signal. This is the Pitfall 1 discipline made mechanical.

LLM fallback (OQ-5 lock): provider-agnostic via instructor.from_provider.
Accepts 'claude-*' | 'gpt-*' | 'gemini-*' | 'ollama/*' model strings.
Response model is a Literal-typed discriminated union — NO raw float
confidence field (Pitfall A6: bands ≠ calibrated probabilities).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from folio_insights.polysemy.similarity_query import has_framework_conflicting_axiom
from folio_insights.polysemy.whitelists import (
    DEFAULT_DISTINGUO_THRESHOLD,
    HOMONYMS,
    TERMS_OF_ART,
    TERMS_OF_ART_THRESHOLD,
)

if TYPE_CHECKING:
    from folio_insights.polysemy.prototype_cluster import PrototypeCluster
    from folio_insights.store.pyoxigraph_store import PyoxigraphStore

logger = logging.getLogger(__name__)


class RuleVerdict(BaseModel):
    """Returned when rules alone decide (short-circuit paths R1 / R2 / R3,
    or all-rules-pass → tentative polysemy)."""

    kind: Literal["rule"] = "rule"
    decision: Literal["polysemy", "homonymy", "coincidence", "uncertain"]
    rule_confidence: float = Field(ge=0.0, le=1.0)
    matched_rules: list[str]
    evidence_score: float = Field(ge=0.0, le=2.0)


class LLMVerdict(BaseModel):
    """Returned when Rule 4 (HOMONYMS) triggers LLM fallback.

    `provider` is the instructor provider family ('anthropic' | 'openai' |
    'google' | 'ollama'), not the specific model string. Specific model
    routing is opaque to downstream consumers (CLI review + FP audit).

    NO raw float confidence field (Pitfall A6): confidence-band strings
    are NOT calibrated probabilities; we carry a Literal decision + prose
    reasoning instead.
    """

    kind: Literal["llm"] = "llm"
    decision: Literal["polysemy", "homonymy", "coincidence", "uncertain"]
    polysemy_vs_homonymy_reasoning: str
    rationale: str
    provider: str  # "anthropic" | "openai" | "google" | "ollama"
    matched_rules: list[str]
    evidence_score: float = Field(ge=0.0, le=2.0)


class PolysemyVerdict(BaseModel):
    """Instructor response model for the LLM-fallback call.

    Kept separate from LLMVerdict so that the instructor contract (what
    the LLM is asked to produce) is decoupled from the detector output
    contract (what downstream consumers read). LLMVerdict adds provider
    + matched_rules + evidence_score fields that the LLM does not supply.
    """

    decision: Literal["polysemy", "homonymy", "coincidence", "uncertain"]
    polysemy_vs_homonymy_reasoning: str
    rationale: str


_PROVIDER_FAMILY_MAP = {
    "claude": "anthropic",
    "gpt": "openai",
    "gemini": "google",
}


def _resolve_provider_family(model: str) -> str:
    """Map an llm_provider string to an instructor provider family.

    Rules:
      - 'ollama/*'  → 'ollama'
      - starts with 'claude' → 'anthropic'
      - starts with 'gpt'    → 'openai'
      - starts with 'gemini' → 'google'
      - otherwise            → 'anthropic' (safe default — Claude is primary)
    """
    if model.startswith("ollama/"):
        return "ollama"
    for prefix, family in _PROVIDER_FAMILY_MAP.items():
        if model.startswith(prefix):
            return family
    return "anthropic"  # safe default — Claude is Phase 1 primary


def _invoke_llm_fallback(
    cluster: "PrototypeCluster",
    *,
    llm_provider: str,
    matched_rules: list[str],
    extra_prompt: str = "",
) -> LLMVerdict:
    """Provider-agnostic instructor call. OQ-5 per orchestrator lock.

    Uses `instructor.from_provider(f"{family}:{model}")`. For 'ollama/llama3.2'
    the family is 'ollama' and the model string after the '/' is forwarded
    verbatim. For other families the full llm_provider string is forwarded
    as the model component.

    The prompt includes ONE representative axiom_summary per framework (not
    extracted_text — Pitfall 1) plus explicit polysemy-vs-homonymy framing
    per PITFALLS L1248.

    Any exception (import error, network fault, provider auth rejection) is
    caught and converted to an LLMVerdict(decision='uncertain', ...) — the
    detector MUST NOT raise from a rule run (T-01-09 mitigation).
    """
    provider_family = _resolve_provider_family(llm_provider)
    model_for_family = (
        llm_provider.removeprefix("ollama/")
        if llm_provider.startswith("ollama/")
        else llm_provider
    )
    axioms_block = "\n".join(
        f"  {fw}: {shard_list[0].axiom_summary}"
        for fw, shard_list in cluster.shards_by_framework.items()
        if shard_list
    )
    evidence_score = max(cluster.cross_framework_cosine_distance.values(), default=0.0)
    prompt = (
        f"Term: {cluster.term!r}\n"
        f"Framework-labeled axioms (one representative per framework):\n"
        f"{axioms_block}\n\n"
        "Question: Are these uses the SAME CONCEPT APPLIED DIFFERENTLY across "
        "frameworks (polysemy — a distinguo fork is appropriate) OR DIFFERENT "
        "CONCEPTS that happen to share the same spelling (homonymy — NOT a "
        "fork) OR an accidental surface overlap with no semantic relation "
        "(coincidence)?\n\n"
        "If you cannot discriminate with high confidence, return 'uncertain' — "
        "do not guess.\n"
        f"{extra_prompt}"
    )
    try:
        import instructor  # lazy — keeps detector importable even if provider libs missing

        client = instructor.from_provider(f"{provider_family}:{model_for_family}")
        verdict: PolysemyVerdict = client.chat.completions.create(
            response_model=PolysemyVerdict,
            messages=[{"role": "user", "content": prompt}],
        )
        return LLMVerdict(
            decision=verdict.decision,
            polysemy_vs_homonymy_reasoning=verdict.polysemy_vs_homonymy_reasoning,
            rationale=verdict.rationale,
            provider=provider_family,
            matched_rules=matched_rules,
            evidence_score=evidence_score,
        )
    except Exception as exc:  # defensive — detector never raises
        logger.warning(
            "LLM fallback failed for term=%r provider=%s: %s",
            cluster.term, provider_family, exc,
        )
        return LLMVerdict(
            decision="uncertain",
            polysemy_vs_homonymy_reasoning=(
                f"LLM fallback raised {type(exc).__name__}: {exc}"
            ),
            rationale="",
            provider=provider_family,
            matched_rules=matched_rules,
            evidence_score=evidence_score,
        )


def detect_polysemy(
    cluster: "PrototypeCluster",
    store: "PyoxigraphStore",
    *,
    llm_provider: str = "claude-haiku-4-5",
    threshold_override: float | None = None,
) -> RuleVerdict | LLMVerdict:
    """Run the 4-rule gate on a PrototypeCluster. Return a discriminated-union
    verdict (RuleVerdict | LLMVerdict) — never a raw dict, never None, never
    a raw float.

    Args:
        cluster: PrototypeCluster from prototype_cluster.build_prototype_cluster.
        store: PyoxigraphStore hosting the shard TTL (used for Rule 1 SPARQL).
            May be None when the caller patches has_framework_conflicting_axiom
            (test paths) — production paths MUST pass a live store.
        llm_provider: OQ-5 model string. One of:
            'claude-haiku-4-5' | 'gpt-4o-mini' | 'gemini-1.5-flash' |
            'ollama/llama3.2' (or any other model string with those prefixes).
            Default is 'claude-haiku-4-5' (Phase 1 primary).
        threshold_override: Force a specific evidence threshold (bypasses
            TERMS_OF_ART_THRESHOLD and DEFAULT_DISTINGUO_THRESHOLD). Used by
            the 01-06 FP-audit sweep to explore threshold sensitivity.

    Rule ordering (short-circuits on first decisive result):
        R1 — SPARQL owl:disjointWith.       NO conflict → 'coincidence'.
        R2 — N ≥ 3 shards per framework.    Any < 3 → 'coincidence'.
        R3 — evidence ≥ threshold.          Below → 'coincidence'.
        R4 — term ∈ HOMONYMS.               Force LLM fallback.
        Else: tentative 'polysemy' with rule_confidence = evidence_score.
    """
    frameworks = list(cluster.shards_by_framework.keys())
    evidence_score = max(cluster.cross_framework_cosine_distance.values(), default=0.0)

    # Rule 1 — SPARQL owl:disjointWith (OQ-1 lock).
    # This is the authoritative axiom-conflict signal. If the TBox does NOT
    # carry an explicit owl:disjointWith between framework-scoped classes,
    # we short-circuit to 'coincidence' rather than falling through to
    # embedding heuristics. Pitfall 1 mitigation.
    if not has_framework_conflicting_axiom(store, cluster.term, frameworks):
        return RuleVerdict(
            decision="coincidence",
            rule_confidence=0.9,
            matched_rules=["R1-no-conflict"],
            evidence_score=evidence_score,
        )

    # Rule 2 — N ≥ 3 per framework (PITFALLS L651 — small-N kills power).
    for fw, shards in cluster.shards_by_framework.items():
        if len(shards) < 3:
            return RuleVerdict(
                decision="coincidence",
                rule_confidence=0.85,
                matched_rules=["R2-insufficient-evidence"],
                evidence_score=evidence_score,
            )

    # Rule 3 — terms-of-art threshold (raise to 0.8) — PITFALLS L652.
    # threshold_override lets 01-06 FP-audit sweep thresholds without editing
    # whitelists.py constants.
    base_threshold = (
        TERMS_OF_ART_THRESHOLD if cluster.term in TERMS_OF_ART
        else DEFAULT_DISTINGUO_THRESHOLD
    )
    threshold = threshold_override if threshold_override is not None else base_threshold
    if evidence_score < threshold:
        return RuleVerdict(
            decision="coincidence",
            rule_confidence=max(0.0, threshold - evidence_score),
            matched_rules=["R3-below-threshold"],
            evidence_score=evidence_score,
        )

    # Rule 4 — known homonym forces LLM-fallback (CONTEXT.md D-2 Rule 4).
    # HOMONYMS are tokens where rules 1-3 could false-positive a polysemy
    # verdict but the tokens are actually homonyms (different concepts sharing
    # a spelling) — we ask the LLM to discriminate explicitly per PITFALLS L1248.
    if cluster.term in HOMONYMS:
        return _invoke_llm_fallback(
            cluster,
            llm_provider=llm_provider,
            matched_rules=["R1-pass", "R2-pass", "R3-pass", "R4-homonym-flag"],
            extra_prompt=(
                "The token is on the known-homonym whitelist. Discriminate "
                "polysemy vs homonymy explicitly."
            ),
        )

    # All rules passed — tentative polysemy. rule_confidence mirrors
    # evidence_score (capped at 1.0) so downstream reviewers can sort
    # proposals by confidence without treating it as a calibrated probability.
    return RuleVerdict(
        decision="polysemy",
        rule_confidence=min(1.0, evidence_score),
        matched_rules=["R1-R2-R3-pass"],
        evidence_score=evidence_score,
    )
