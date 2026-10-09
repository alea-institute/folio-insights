"""Phase 9 U1 (KTD4, RISK-1): the cluster validator's worker-tier boundary.

HermiT (owlready2 + a JVM) ships only in the worker image. The validator's
reasoning modules — ``validation.consistency``, ``validation.hermit`` and
``validation.validator`` (``WORKER_TIER_MODULES``) — are worker-tier, and the
web tier must never import them, or owlready2, at module level. Modelled on
``tests/shards/test_dep_leak_guard.py`` (static source scan) and
``tests/reason/test_el_profile.py`` (a clean-interpreter import check).

Function-scoped (lazy) imports are allowed: that is how the CLI command and
``reason.reasoner`` reach the worker tier only when they run.
"""
from __future__ import annotations

import ast
import pathlib
import subprocess
import sys

import folio_insights
from folio_insights.validation import WORKER_TIER_MODULES

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = pathlib.Path(folio_insights.__file__).parent
FORBIDDEN = (*WORKER_TIER_MODULES, "owlready2", "folio_insights.reason.hermit_harness")

# Modules allowed to import the worker tier at module level: the worker-tier
# modules themselves and the HermiT harness (worker-only since Phase 4).
WORKER_TIER_FILES = {
    SRC / "validation" / "consistency.py",
    SRC / "validation" / "hermit.py",
    SRC / "validation" / "validator.py",
    SRC / "reason" / "hermit_harness.py",
}


def module_level_imports(source: str) -> list[str]:
    """Dotted names imported at module level (top-level statements, including
    those nested in module-level ``if``/``try`` blocks; never function bodies)."""
    tree = ast.parse(source)
    names: list[str] = []
    stack: list[ast.AST] = list(tree.body)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
            names.extend(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, (ast.If, ast.Try, ast.With)):
            # ``if TYPE_CHECKING:`` blocks never execute at runtime.
            if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.unparse(node.test):
                stack.extend(node.orelse)
                continue
            for field in ("body", "orelse", "finalbody", "handlers"):
                stack.extend(getattr(node, field, []) or [])
        elif isinstance(node, ast.ExceptHandler):
            stack.extend(node.body)
    return names


def leaks(path: pathlib.Path) -> list[str]:
    """Forbidden worker-tier imports at module level in ``path``."""
    imported = module_level_imports(path.read_text(encoding="utf-8"))
    return sorted(
        {name for name in imported for bad in FORBIDDEN if name == bad or name.startswith(bad + ".")}
    )


def web_tier_files() -> list[pathlib.Path]:
    files = [p for p in SRC.rglob("*.py") if p not in WORKER_TIER_FILES]
    files += list((REPO_ROOT / "api").rglob("*.py"))
    return sorted(files)


def test_guard_flags_a_web_module_that_imports_the_consistency_checker(tmp_path) -> None:
    """The guard is not vacuous: a web-tier module importing
    ``validation.consistency`` (directly, from-style, or under a module-level
    ``try``) fails it; a lazy import inside a function or a TYPE_CHECKING
    import does not."""
    offender = tmp_path / "route.py"
    offender.write_text(
        "from folio_insights.validation.consistency import ConsistencyChecker\n"
        "try:\n    import owlready2\nexcept ImportError:\n    pass\n"
        "import folio_insights.validation.hermit as h\n"
    )
    assert leaks(offender) == [
        "folio_insights.validation.consistency",
        "folio_insights.validation.consistency.ConsistencyChecker",
        "folio_insights.validation.hermit",
        "owlready2",
    ]
    lazy = tmp_path / "lazy.py"
    lazy.write_text(
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n    from folio_insights.validation.consistency import X\n"
        "def run():\n    from folio_insights.validation.validator import validate_corpus\n"
    )
    assert leaks(lazy) == []


def test_no_web_tier_module_imports_the_worker_tier() -> None:
    files = web_tier_files()
    assert len(files) > 100  # the scan covers src/folio_insights and api/
    offenders = {
        str(path.relative_to(REPO_ROOT)): found for path in files if (found := leaks(path))
    }
    assert offenders == {}, (
        "web-tier modules import a worker-tier module at module level; import it inside "
        "the function that needs it (KTD4: the web tier never imports owlready2 or the "
        f"cluster reasoner): {offenders}"
    )


def test_web_entry_points_load_without_the_worker_tier() -> None:
    """A clean interpreter imports the API app, the CLI (with the validate
    group registered) and the web-safe validation modules without loading
    owlready2 or any worker-tier validation module."""
    forbidden = list(FORBIDDEN)
    code = (
        "import sys\n"
        "import api.main, folio_insights.cli\n"
        "import folio_insights.validation, folio_insights.validation.cli\n"
        "import folio_insights.validation.clusters, folio_insights.validation.coverage\n"
        "import folio_insights.validation.crossref, folio_insights.validation.formal\n"
        "import folio_insights.validation.nli, folio_insights.validation.report\n"
        "assert 'validate' in folio_insights.cli.cli.commands\n"
        f"loaded = [m for m in {forbidden!r} if m in sys.modules]\n"
        "assert not loaded, loaded\n"
        "assert 'sentence_transformers' not in sys.modules\n"
        "print('ok')\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False, cwd=REPO_ROOT,
        timeout=120,
    )
    assert out.returncode == 0 and out.stdout.strip().endswith("ok"), out.stderr
