"""Versioned prompt templates and their identity hashes (KTD4).

Every LLM call goes through a registered :class:`PromptTemplate`. A template's hash covers its
id, version, system and user prompt templates and the output schema's JSON, and never the unit
text that fills it, so identical templates always give identical hashes and any edit to a
prompt or schema changes the hash. The shard minter (a later unit) combines the per-stage hashes
into ``extraction_prompt_hash`` with :func:`combined_prompt_hash`.

The registry maps each LLM task name (the ``LLM_{TASK}_PROVIDER/MODEL`` routing key) to its
default template. A task may own more than one template (``polysemy_fallback`` serves both the
detector and the FP audit); callers then name the template explicitly.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from functools import cached_property
from importlib import metadata
from typing import Any

from pydantic import BaseModel

from folio_insights.llm import schemas
from folio_insights.services.prompts.boundary import BOUNDARY_REFINEMENT_PROMPT
from folio_insights.services.prompts.classification import CLASSIFICATION_PROMPT
from folio_insights.services.prompts.contradiction import CONTRADICTION_ANALYSIS_PROMPT
from folio_insights.services.prompts.distillation import DISTILLATION_PROMPT
from folio_insights.services.prompts.novelty import NOVELTY_SCORING_PROMPT
from folio_insights.services.prompts.task_discovery import (
    TASK_DISCOVERY_PROMPT,
    TASK_ORDERING_PROMPT,
)


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class PromptTemplate:
    """One versioned prompt. ``user``/``system`` are ``str.format`` templates."""

    id: str
    version: str
    task: str
    user: str
    system: str = ""
    output_schema: type[BaseModel] | None = field(default=None, compare=False)
    #: Output-token cap for this template's calls (a generation parameter, not prompt identity,
    #: so it is outside the hash). It also bounds the spend-cap worst case. The folio-enrich
    #: bridge sent 4096 to Anthropic and nothing to the other providers; these caps are sized
    #: to each task's output schema instead. ``FOLIO_INSIGHTS_LLM_MAX_TOKENS`` overrides them.
    max_tokens: int = field(default=4096, compare=False)

    @cached_property
    def schema_json(self) -> dict[str, Any] | None:
        return None if self.output_schema is None else self.output_schema.model_json_schema()

    @cached_property
    def hash(self) -> str:
        """sha256 over template identity: id, version, prompt templates and output schema."""
        payload = {
            "id": self.id,
            "version": self.version,
            "system": self.system,
            "user": self.user,
            "output_schema": self.schema_json,
        }
        return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()

    def render(self, **values: Any) -> str:
        """Render the user prompt."""
        return self.user.format(**values)

    def messages(self, prompt: str | None = None, **values: Any) -> list[dict[str, str]]:
        """Chat messages for this template: an optional system turn and the user turn.

        ``prompt`` is an already-rendered user prompt (the compatibility path for call sites
        that render before calling); otherwise ``values`` fill :attr:`user`.
        """
        out: list[dict[str, str]] = []
        if self.system:
            out.append({"role": "system", "content": self.system.format(**values)})
        out.append({"role": "user", "content": prompt if prompt is not None else self.render(**values)})
        return out


def combined_prompt_hash(stage_hashes: list[str] | tuple[str, ...] | set[str]) -> str:
    """The ``extraction_prompt_hash`` of a shard: sha256 over its sorted per-stage hashes."""
    joined = "\n".join(sorted(set(stage_hashes)))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


_REGISTRY: dict[str, PromptTemplate] = {}
_TASK_DEFAULT: dict[str, str] = {}


def register(template: PromptTemplate, *, default_for_task: bool = True) -> PromptTemplate:
    """Add ``template``; re-registering an id with different content is an error."""
    existing = _REGISTRY.get(template.id)
    if existing is not None and existing.hash != template.hash:
        raise ValueError(
            f"prompt template {template.id!r} re-registered with different content; "
            "bump its version instead"
        )
    _REGISTRY[template.id] = template
    if default_for_task:
        _TASK_DEFAULT.setdefault(template.task, template.id)
    return template


def get_template(template_id: str) -> PromptTemplate:
    try:
        return _REGISTRY[template_id]
    except KeyError:
        raise KeyError(f"no prompt template registered as {template_id!r}") from None


def template_for_task(task: str) -> PromptTemplate:
    """The default template for an LLM task name."""
    template_id = _TASK_DEFAULT.get(task)
    if template_id is None:
        raise KeyError(f"no prompt template registered for LLM task {task!r}")
    return _REGISTRY[template_id]


def all_templates() -> list[PromptTemplate]:
    return sorted(_REGISTRY.values(), key=lambda t: t.id)


def _folio_resolve_version() -> str:
    try:
        return metadata.version("folio-resolve")
    except metadata.PackageNotFoundError:  # pragma: no cover - pinned core dependency
        return "unknown"


# ---- The registry ------------------------------------------------------------------------------

DISTILL = register(PromptTemplate(
    id="distiller.distill", version="1", task="distiller",
    user=DISTILLATION_PROMPT, output_schema=schemas.DistilledOutput,
    max_tokens=2048,
))

CLASSIFY = register(PromptTemplate(
    id="knowledge_classifier.classify", version="1", task="classifier",
    user=CLASSIFICATION_PROMPT, output_schema=schemas.ClassificationOutput,
    max_tokens=1024,
))

NOVELTY = register(PromptTemplate(
    id="knowledge_classifier.novelty", version="1", task="novelty",
    user=NOVELTY_SCORING_PROMPT, output_schema=schemas.NoveltyOutput,
    max_tokens=1024,
))

CONCEPT = register(PromptTemplate(
    id="folio_tagger.concept", version="1", task="concept",
    user=(
        "Identify FOLIO legal ontology concepts in this text. "
        "Return concept labels and confidence scores.\n\n"
        "Text: {text}\n"
        "Section context: {context}"
    ),
    output_schema=schemas.ConceptOutput,
    max_tokens=2048,
))

# The judge prompt itself is built by the pinned folio-resolve (build_judge_prompt), so its
# identity is that package's version: a folio-resolve bump changes this template's hash.
BRANCH_JUDGE = register(PromptTemplate(
    id="folio_tagger.branch_judge",
    version=f"1+folio-resolve-{_folio_resolve_version()}",
    task="branch_judge",
    user="{judge_system}\n\n{judge_user}",
    output_schema=schemas.JudgeOutput,
    max_tokens=2048,
))

BOUNDARY = register(PromptTemplate(
    id="boundary.llm_refine", version="1", task="boundary",
    user=BOUNDARY_REFINEMENT_PROMPT, output_schema=schemas.BoundaryRefinementResponse,
    max_tokens=4096,
))

CONTRADICTION = register(PromptTemplate(
    id="discovery.contradiction", version="1", task="contradiction",
    user=CONTRADICTION_ANALYSIS_PROMPT,
    max_tokens=2048,
))

TASK_DISCOVERY = register(PromptTemplate(
    id="discovery.task_label", version="1", task="task_discovery",
    user=TASK_DISCOVERY_PROMPT,
    max_tokens=2048,
))

TASK_ORDERING = register(PromptTemplate(
    id="discovery.task_ordering", version="1", task="task_ordering",
    user=TASK_ORDERING_PROMPT,
    max_tokens=2048,
))

POLYSEMY_DETECTOR = register(PromptTemplate(
    id="polysemy.detector_fallback", version="1", task="polysemy_fallback",
    user=(
        "Term: {term!r}\n"
        "Framework-labeled axioms (one representative per framework):\n"
        "{axioms_block}\n\n"
        "Question: Are these uses the SAME CONCEPT APPLIED DIFFERENTLY across "
        "frameworks (polysemy — a distinguo fork is appropriate) OR DIFFERENT "
        "CONCEPTS that happen to share the same spelling (homonymy — NOT a "
        "fork) OR an accidental surface overlap with no semantic relation "
        "(coincidence)?\n\n"
        "If you cannot discriminate with high confidence, return 'uncertain' — "
        "do not guess.\n"
        "{extra_prompt}"
    ),
    output_schema=schemas.PolysemyVerdict,
    max_tokens=1024,
))

POLYSEMY_FP_AUDIT = register(PromptTemplate(
    id="polysemy.fp_audit", version="1", task="polysemy_fallback",
    user=(
        "Term: {term}\n"
        "Cluster: {cluster_id}\n"
        "Reviewer disposition: {decision}\n"
        "Reviewer rationale: {rationale}\n"
        "Detector verdict (snapshot): {detector_verdict}\n\n"
        "Independently classify this cluster as polysemy, homonymy, "
        "coincidence, or uncertain. Provide both polysemy_vs_homonymy_reasoning "
        "and rationale fields. Be brief."
    ),
    output_schema=schemas.PolysemyVerdict,
    max_tokens=1024,
), default_for_task=False)

FRAMEWORK_DETECT = register(PromptTemplate(
    id="frameworks.detector_fallback", version="1", task="framework_detector",
    user=(
        "Choose the legal framework a source belongs to. Answer ONLY with one of these "
        "registered framework ids, or null if none fits:\n{candidates}\n\n"
        "Source title: {title}\n"
        "Source jurisdiction: {jurisdiction}\n"
        "Citations in the source: {citations}\n\n"
        "Never invent a framework id. Give your confidence (0-1) and a one-sentence rationale."
    ),
    output_schema=schemas.FrameworkChoice,
    max_tokens=512,
))
