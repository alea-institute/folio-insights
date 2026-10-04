"""HermiT reasons inside the built worker image (jlink JRE regression).

The worker runs HermiT on a jlink-trimmed JRE (Dockerfile.worker). A missing
Java module never fails the build; it fails the first ``sync_reasoner`` call with
``NoClassDefFoundError`` (``java/awt/geom/Point2D`` before ``java.desktop`` was
added). Only a reasoning run inside the image proves the JRE is complete, so this
test runs one on a tiny synthetic ontology that exercises the object-property
automata path where the crash happened.

Resolves the image like Gate 3: ``FOLIO_WORKER_IMAGE`` first, then local dev
tags; skips when no worker image is available. The static half of this check
is ``tests/test_worker_jre_modules.py``.
"""
from __future__ import annotations

import shutil
import subprocess

import pytest

from tests.bench.test_gate3_image import _resolve_worker_image

_REASONING_SCRIPT = """
import owlready2
from owlready2 import ObjectProperty, Thing, TransitiveProperty, World, sync_reasoner

w = World()
onto = w.get_ontology("http://test.org/worker-hermit.owl")
with onto:
    class Animal(Thing): pass
    class Dog(Animal): pass
    class hasParent(ObjectProperty): pass
    class hasAncestor(ObjectProperty, TransitiveProperty): pass
    hasParent.is_a.append(hasAncestor)
    class hasGrandparent(ObjectProperty): pass
    hasGrandparent.property_chain.append(owlready2.PropertyChain([hasParent, hasParent]))
    class Pet(Thing):
        equivalent_to = [Animal & hasParent.some(Thing)]
    a, b, c = Dog("a"), Dog("b"), Dog("c")
    a.hasParent = [b]
    b.hasParent = [c]
with onto:
    sync_reasoner(w, infer_property_values=True, debug=0)
assert Pet in a.is_a, a.is_a
assert c in a.hasAncestor, a.hasAncestor
assert c in a.hasGrandparent, a.hasGrandparent
print("HERMIT_OK")
"""


@pytest.mark.worker_image
@pytest.mark.slow
@pytest.mark.timeout(180)
def test_hermit_reasons_in_worker_image() -> None:
    if shutil.which("docker") is None:
        pytest.skip("docker not on PATH")
    image = _resolve_worker_image()
    if image is None:
        pytest.skip(
            "No worker image found locally. Build one or set FOLIO_WORKER_IMAGE "
            "(see tests/bench/test_gate3_image.py)."
        )
    result = subprocess.run(
        ["docker", "run", "--rm", "-i", "--network", "none", image, "python", "-"],
        input=_REASONING_SCRIPT, capture_output=True, text=True, check=False, timeout=170,
    )
    output = result.stdout + result.stderr
    assert "NoClassDefFoundError" not in output, (
        f"{image}: the jlink JRE lacks a module HermiT needs "
        f"(see Dockerfile.worker jre-builder).\n{output[-3000:]}"
    )
    assert result.returncode == 0 and "HERMIT_OK" in result.stdout, output[-3000:]
