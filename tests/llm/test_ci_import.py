"""CI can import every LLM path with no folio-enrich checkout (Phase 10 U1).

The Dagger test container has no sibling folio-enrich tree, so before U1 the LLM call sites
could only be exercised through fakes. This test runs in a fresh interpreter whose
``FOLIO_INSIGHTS_FOLIO_ENRICH_PATH`` points at an empty directory and whose import system
refuses folio-enrich's ``app`` package, then imports every LLM call site, resolves a TaskLLM for
every task and builds an SDK client for every provider.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

_PROBE = r"""
import importlib, importlib.abc, json, sys

class _NoFolioEnrich(importlib.abc.MetaPathFinder):
    refused = []
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "app" or fullname.startswith("app."):
            self.refused.append(fullname)
            raise ImportError("folio-enrich is not available in this interpreter")
        return None

guard = _NoFolioEnrich()
sys.meta_path.insert(0, guard)

modules = [
    "folio_insights.llm",
    "folio_insights.services.bridge.llm_bridge",
    "folio_insights.pipeline.stages.distiller",
    "folio_insights.pipeline.stages.knowledge_classifier",
    "folio_insights.pipeline.stages.folio_tagger",
    "folio_insights.pipeline.stages.boundary_detection",
    "folio_insights.services.boundary.llm_refiner",
    "folio_insights.services.contradiction_detector",
    "folio_insights.pipeline.discovery.stages.content_clustering",
    "folio_insights.pipeline.discovery.stages.hierarchy_construction",
    "folio_insights.polysemy.detector",
    "folio_insights.polysemy.fp_audit",
]
for name in modules:
    importlib.import_module(name)

from folio_insights.llm.providers import PROVIDERS, build_client
from folio_insights.llm.templates import template_for_task
from folio_insights.services.bridge.llm_bridge import LLMBridge

bridge = LLMBridge()
routed = {}
for task in ("boundary", "classifier", "distiller", "novelty", "concept", "branch_judge",
             "task_discovery", "task_ordering", "contradiction", "polysemy_fallback"):
    llm = bridge.get_llm_for_task(task)
    routed[task] = template_for_task(task).id

clients = {name: type(build_client(spec, api_key=None, timeout=5.0)).__name__
           for name, spec in PROVIDERS.items()}
print(json.dumps({
    "modules": len(modules),
    "routed": routed,
    "clients": clients,
    "refused": guard.refused,
    "folio_enrich_loaded": any(m == "app" or m.startswith("app.") for m in sys.modules),
}))
"""


def test_every_llm_path_imports_without_folio_enrich(tmp_path: Path) -> None:
    empty = tmp_path / "no-folio-enrich"
    empty.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY")}
    env["FOLIO_INSIGHTS_FOLIO_ENRICH_PATH"] = str(empty)
    env["PYTHONPATH"] = f"{REPO / 'src'}{os.pathsep}{REPO}"
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    report = json.loads(proc.stdout.strip().splitlines()[-1])
    assert report["folio_enrich_loaded"] is False
    assert report["refused"] == []  # nothing even tried to import folio-enrich
    assert set(report["clients"]) == {"openai", "anthropic", "google", "ollama"}
    assert all(v == "AsyncInstructor" for v in report["clients"].values())
    assert len(report["routed"]) == 10
