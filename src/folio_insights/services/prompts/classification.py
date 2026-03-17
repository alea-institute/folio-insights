"""Prompt template for knowledge type classification."""

CLASSIFICATION_PROMPT = """Classify this legal advocacy knowledge unit into exactly one type:

- advice: A technique, strategy, or actionable tip for a practitioner
- principle: A foundational legal principle or rule of thumb
- citation: A case citation with its holding or significance
- procedural_rule: A required procedural step, deadline, or filing requirement
- pitfall: A common mistake, trap, or warning about what NOT to do

Knowledge unit text: {text}
Document section: {section_path}

Return the type, your confidence (0-1), and brief reasoning."""
