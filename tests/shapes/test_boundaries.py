"""R9 / KTD6: rdflib and pyshacl stay adapter-only.

Only ``shapes/pyshacl_adapter.py`` imports them. The write-path engine, the
corpus tier, the suite, the renderer and the generator parse and evaluate
with pyoxigraph and plain Python. The storage package's own scan
(``tests/storage/test_rdflib_adapter_only.py``) covers ``storage/``.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import folio_insights.shapes as shapes_pkg

SHAPES = Path(shapes_pkg.__file__).parent
FORBIDDEN = {"rdflib", "pyshacl", "oxrdflib"}


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


@pytest.mark.parametrize(
    "path",
    sorted(p for p in SHAPES.rglob("*.py") if p.name != "pyshacl_adapter.py"),
    ids=lambda p: p.name,
)
def test_only_the_adapter_imports_rdflib_or_pyshacl(path: Path) -> None:
    assert not _imports(path) & FORBIDDEN, path


def test_the_adapter_is_the_one_that_does() -> None:
    assert {"rdflib", "pyshacl"} <= _imports(SHAPES / "pyshacl_adapter.py")
