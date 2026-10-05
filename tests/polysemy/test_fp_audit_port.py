"""Phase 9 U2 — the FP audit reaches the LLM only through the Phase 10 port.

The plan listed ``fp_audit``'s stale provider interface (an instructor-style
``client.chat.completions.create`` that the bridge providers never exposed).
Phase 10 U1 rerouted it through ``LLMBridge.get_llm_for_task`` ->
``TaskLLM.structured_model_sync``; these tests pin that route, including the
default (no injected bridge) path. No provider is called.
"""
from __future__ import annotations

import ast
import pathlib

from folio_insights.llm.port import TaskLLM
from folio_insights.llm.schemas import PolysemyVerdict
from folio_insights.llm.templates import POLYSEMY_FP_AUDIT
from folio_insights.polysemy import fp_audit

from tests.polysemy.test_fp_rate import _sample_record, _seed_jsonl


def test_fp_audit_has_no_stale_provider_interface() -> None:
    source = pathlib.Path(fp_audit.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "completions" not in attrs and "chat" not in attrs
    assert {"get_llm_for_task", "structured_model_sync"} <= attrs


def test_default_path_goes_through_the_port(tmp_path: pathlib.Path, monkeypatch) -> None:  # noqa: ANN001
    calls = []

    def fake_structured(self, prompt, schema=None, *, template=None, temperature=0.0):  # noqa: ANN001, ANN202
        calls.append((self.task, schema, template))
        return PolysemyVerdict(decision="polysemy", polysemy_vs_homonymy_reasoning="r",
                               rationale="synthetic")

    monkeypatch.setattr(TaskLLM, "structured_model_sync", fake_structured)
    path = _seed_jsonl(tmp_path, [_sample_record(cluster_id="fi:C_x", decision="accept",
                                                 rationale="ok")])
    result = fp_audit.run_llm_audit_pass(path, tmp_path / "audit.md",
                                         llm_provider="claude-haiku-4-5")
    assert result == {"total": 1, "agreements": 1, "disagreements": 0}
    assert calls == [("polysemy_fallback", PolysemyVerdict, POLYSEMY_FP_AUDIT)]
