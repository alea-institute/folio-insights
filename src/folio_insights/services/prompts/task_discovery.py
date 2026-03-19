"""Prompt templates for Phase 2 task discovery LLM calls.

Used by ContentClusteringStage, HierarchyConstructionStage,
and ContradictionDetectionStage for structured LLM output.
"""

TASK_DISCOVERY_PROMPT = """You are an expert legal knowledge organizer analyzing advocacy knowledge units.

Below are knowledge units that were clustered together by semantic similarity. Your job is to identify the advocacy task they belong to.

Knowledge units:
{unit_texts}

Based on these knowledge units, determine:
1. **task_label**: A concise label for the advocacy task (e.g., "Cross-Examination", "Opening Statement Preparation", "Expert Witness Challenges")
2. **task_description**: A one-sentence description of what this task involves
3. **is_procedural**: True if the steps must be performed in a specific order (preparation -> execution -> follow-up), False if this is a collection of techniques/skills
4. **subtask_labels**: If procedural, provide an ordered list of subtask labels. If not procedural, leave empty.
5. **folio_concept_suggestion**: Suggest the most specific FOLIO legal ontology concept label this maps to
6. **confidence**: Your confidence (0.0-1.0) that this represents a distinct, coherent advocacy task

Return your answer as JSON with exactly these fields:
{{
  "task_label": "...",
  "task_description": "...",
  "is_procedural": true/false,
  "subtask_labels": ["...", "..."],
  "folio_concept_suggestion": "...",
  "confidence": 0.0
}}"""

TASK_ORDERING_PROMPT = """You are an expert legal practitioner analyzing the subtasks of an advocacy task.

Task: {task_label}

Subtasks to order:
{subtask_labels}

Determine the canonical ordering of these subtasks from preparation through execution to follow-up. If no meaningful order exists, return them in their current order and set "is_ordered" to false.

Return your answer as JSON:
{{
  "ordered_labels": ["...", "..."],
  "is_ordered": true/false,
  "ordering_rationale": "..."
}}"""

JURISDICTION_DETECTION_PROMPT = """You are a legal knowledge analyst checking for jurisdictional variation.

Knowledge unit text:
{unit_text}

Determine whether this knowledge unit contains advice that varies by jurisdiction (e.g., "in federal court...", "some states require...", "under California law...").

Return your answer as JSON:
{{
  "is_jurisdiction_sensitive": true/false,
  "jurisdictions_mentioned": ["federal", "California", ...],
  "explanation": "..."
}}"""
