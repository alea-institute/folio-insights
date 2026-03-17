"""Prompt template for knowledge unit distillation."""

DISTILLATION_PROMPT = """Distill the following legal advocacy text into its core insight. Rules:

1. Extract the IDEA, not the expression -- compress to the minimum words needed to fully convey the concept
2. Preserve tactical nuance (e.g., "Lock expert into reviewed-document list during deposition -- prevents expanding opinion basis at trial")
3. Strip filler, hedging, repetition, and attribution phrases
4. Keep specific procedural details that a practitioner needs (deadlines, rule numbers, specific techniques)
5. Do NOT add any information not present in the original text
6. Do NOT generalize specific advice into vague principles

Text to distill:
{text}

Section context: {section_path}"""
