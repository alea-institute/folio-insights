"""Synthetic pipeline stages for the durable-job tests (no source text, no network).

1. ``fake_ingest``   -- adds three synthetic units (its output must never be duplicated);
2. ``fake_llm``      -- one structured LLM call through ``LLMBridge`` / the port (only when
                        ``FAKE_LLM_KEY`` is set);
3. ``fake_slow``     -- blocks until ``FAKE_PIPELINE_RELEASE`` exists (so a test can kill the
                        process mid-stage), then finishes.

Every stage appends a line to ``$FAKE_PIPELINE_LOG`` so a test can count executions. Importing
this module changes nothing global; ``tests.jobs.fake_pipeline`` (subprocess only) patches the
orchestrator to use these stages.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from folio_insights.models.knowledge_unit import KnowledgeType, KnowledgeUnit, Span
from folio_insights.pipeline.stages.base import InsightsPipelineStage

def _log(line: str) -> None:
    path = os.environ.get("FAKE_PIPELINE_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())


class FakeIngest(InsightsPipelineStage):
    @property
    def name(self) -> str:
        return "fake_ingest"

    async def execute(self, job):
        _log("fake_ingest")
        for i in range(3):
            text = f"Synthetic unit {i}: object before the answer."
            job.units.append(KnowledgeUnit(
                text=text, original_span=Span(start=0, end=len(text), source_file="synthetic.md"),
                unit_type=KnowledgeType.ADVICE, source_file="synthetic.md"))
        return job


class FakeLLM(InsightsPipelineStage):
    @property
    def name(self) -> str:
        return "fake_llm"

    async def execute(self, job):
        _log("fake_llm")
        if not os.environ.get("FAKE_LLM_KEY"):
            return job
        from folio_insights.llm.schemas import DistilledOutput
        from folio_insights.llm.templates import DISTILL
        from folio_insights.services.bridge.llm_bridge import LLMBridge

        llm = LLMBridge().get_llm_for_task("distiller")
        try:
            out = await llm.structured(DISTILL.render(text=job.units[0].text, section_path="S"),
                                       schema=DistilledOutput, temperature=0)
            job.units[0].text = out["distilled_text"]
            _log("fake_llm:ok")
        except Exception as exc:  # the stage degrades per call, like the real distiller
            _log(f"fake_llm:error:{type(exc).__name__}")
        return job


class FakeSlow(InsightsPipelineStage):
    @property
    def name(self) -> str:
        return "fake_slow"

    async def execute(self, job):
        _log("fake_slow:start")
        release = os.environ.get("FAKE_PIPELINE_RELEASE")
        while release and not Path(release).exists():
            await asyncio.sleep(0.05)
        _log("fake_slow:done")
        return job




def fake_stages() -> list[InsightsPipelineStage]:
    return [FakeIngest(), FakeLLM(), FakeSlow()]
