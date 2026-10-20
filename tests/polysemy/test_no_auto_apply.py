"""PRINCIPLE-06 (Phase 9 U6, decision 8): no CLI or API path applies a fork
without a recorded human disposition.

Extends the review command's flag-absence test (``test_cli_review.py``) to
every polysemy command and to the API route table, and pins the one code path
that renders TBox-bound fork triples to its disposition gate.
"""
from __future__ import annotations

import ast
import pathlib

import pytest
from fastapi.routing import APIRoute

from folio_insights.polysemy.cli import polysemy

pytestmark = pytest.mark.polysemy_spike

REPO = pathlib.Path(__file__).resolve().parents[2]
FORBIDDEN_FLAGS = {"auto", "yes", "batch", "accept_all", "no_prompt", "force", "apply",
                   "auto_apply", "non_interactive", "assume_yes"}
FORBIDDEN_COMMANDS = {"apply", "commit", "publish", "auto", "accept-all", "merge"}
POLYSEMY_WORDS = ("polysemy", "distinguo", "fork", "disposition")
READ_METHODS = {"GET", "HEAD", "OPTIONS"}


def test_no_polysemy_command_has_a_bypass_flag() -> None:
    for name, command in polysemy.commands.items():
        params = {p.name for p in command.params}
        assert not (FORBIDDEN_FLAGS & params), f"polysemy {name}: {FORBIDDEN_FLAGS & params}"


def test_no_polysemy_command_applies_anything() -> None:
    assert not (FORBIDDEN_COMMANDS & set(polysemy.commands)), set(polysemy.commands)
    assert set(polysemy.commands) == {"detect", "review", "audit", "gate"}, (
        "a new polysemy command needs a no-auto-apply review; extend this test deliberately"
    )


def _routes() -> list[tuple[str, set[str], str]]:
    """``(path, methods, endpoint module)`` of every API route as served.

    FastAPI 0.139 keeps included routers lazily; ``iter_route_contexts``
    resolves them (the same walk as ``tests/api/test_auth.py``)."""
    from api.main import app

    try:
        from fastapi.routing import iter_route_contexts
    except ImportError:  # pragma: no cover - FastAPI before lazy includes
        contexts = app.routes
    else:
        contexts = iter_route_contexts(app.routes)
    out = []
    for ctx in contexts:
        original = getattr(ctx, "original_route", ctx)
        if isinstance(original, APIRoute):
            out.append((ctx.path, set(ctx.methods or ()), original.endpoint.__module__))
    return out


def test_api_polysemy_routes_are_read_only() -> None:
    """Every route that touches polysemy, forks, distinguo or dispositions is a read."""
    routes = _routes()
    assert len(routes) > 20, "the route walk must see the included routers"
    touched = [r for r in routes
               if any(w in r[0].lower() or w in r[2].lower() for w in POLYSEMY_WORDS)]
    assert touched, "expected the Phase 0 polysemy read routes in the route table"
    for path, methods, _module in touched:
        assert methods <= READ_METHODS, (path, methods)


def test_no_api_module_reaches_the_polysemy_package() -> None:
    """No API handler imports polysemy code, so no route can emit or apply a fork."""
    offenders = []
    for path in sorted((REPO / "api").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            offenders += [f"{path.relative_to(REPO)}: {n}" for n in names
                          if n.startswith("folio_insights.polysemy")]
    assert offenders == []


def test_fork_emission_is_only_reachable_through_its_gate() -> None:
    """``emit_distinguo_fork_ttl`` is the one renderer of TBox-bound fork
    triples; it checks the disposition first. The private triple builder
    ``_distinguo_fork_triples`` is used nowhere else in ``src``, ``api`` or
    ``scripts``, and no API or script module calls the gated renderer."""
    def users(name: str) -> list[str]:
        """Modules whose code (not docstrings) names ``name``."""
        out = []
        for root in ("src", "api", "scripts"):
            for p in (REPO / root).rglob("*.py"):
                tree = ast.parse(p.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    named = (isinstance(node, ast.Name) and node.id == name) or (
                        isinstance(node, ast.Attribute) and node.attr == name) or (
                        isinstance(node, ast.alias) and node.name == name) or (
                        isinstance(node, ast.FunctionDef) and node.name == name)
                    if named:
                        out.append(str(p.relative_to(REPO)))
                        break
        return sorted(out)

    assert users("_distinguo_fork_triples") == ["src/folio_insights/polysemy/distinguo.py"]
    assert users("emit_distinguo_fork_ttl") == ["src/folio_insights/polysemy/distinguo.py"]
    from folio_insights.polysemy import distinguo

    body = ast.parse(pathlib.Path(distinguo.__file__).read_text(encoding="utf-8"))
    emit = next(n for n in body.body
                if isinstance(n, ast.FunctionDef) and n.name == "emit_distinguo_fork_ttl")
    calls = [n.func.id for n in ast.walk(emit)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    assert calls.index("check_fork_release") < calls.index("_distinguo_fork_triples")
