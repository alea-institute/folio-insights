"""Prompt template for Tier 3 LLM boundary refinement."""

BOUNDARY_REFINEMENT_PROMPT = """You are analyzing legal advocacy text to identify distinct knowledge unit boundaries.

Each knowledge unit should capture exactly ONE of these:
- A technique or strategy (actionable advice)
- A foundational principle or rule
- A case citation with its holding
- A procedural requirement or deadline
- A warning about a common mistake (pitfall)

A paragraph with 3 tips should become 3 separate units.

Given this text segment, identify the exact character positions where one knowledge unit ends and the next begins.

IMPORTANT: Do NOT include any knowledge, principles, or advice not present in the provided text.

Text:
{text}

Return boundary positions as a list of objects with start_char, end_char, and a brief rationale for each split."""
