"""Prompt templates for contradiction detection LLM calls.

Used by ContradictionDetectionStage for deep analysis of
potential contradictions identified by NLI cross-encoder screening.
"""

CONTRADICTION_ANALYSIS_PROMPT = """You are an expert legal knowledge analyst evaluating whether two knowledge units contain contradictory advice.

These two knowledge units are linked to the same advocacy task: **{task_label}**

**Unit A:**
{text_a}

**Unit B:**
{text_b}

Analyze whether these two units contain contradictory advice. Consider:
- Full contradictions: direct opposite advice ("always do X" vs "never do X")
- Partial contradictions: qualified disagreement ("do X" vs "never do X except when Y")
- Jurisdictional contradictions: advice that differs by jurisdiction ("in federal court, do X" vs "in state court, do Y")
- False positives: units that address different aspects of the same task and don't actually conflict

Return your analysis as JSON with exactly these fields:
{{
  "is_contradiction": true/false,
  "contradiction_type": "full" | "partial" | "jurisdictional",
  "explanation": "Clear explanation of why these positions conflict (or why they don't)",
  "context_dependency": "Conditions under which each position is valid (empty if not a contradiction)",
  "suggested_resolution": "keep_both" | "prefer_a" | "prefer_b" | "merge" | "jurisdiction"
}}

If not a contradiction, set contradiction_type to "full", context_dependency to "", and suggested_resolution to "keep_both"."""
