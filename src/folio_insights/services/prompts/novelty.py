"""Prompt template for novelty/surprise scoring."""

NOVELTY_SCORING_PROMPT = """Rate how surprising or counterintuitive this legal advocacy insight is.

Score 0.0: Completely expected -- any legal AI or experienced attorney would know this without being told.
Score 0.3: Standard knowledge -- commonly taught but worth having in a structured form.
Score 0.5: Moderately novel -- a useful insight that many practitioners might not have articulated explicitly.
Score 0.7: Quite surprising -- contradicts common assumptions or reveals a non-obvious technique.
Score 1.0: Highly counterintuitive -- unlikely to be in any LLM's training data, contradicts standard advice.

Knowledge unit: {text}
Context: {section_path}

Rate the novelty/surprise score and explain why."""
