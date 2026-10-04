"""The worker's jlink JRE carries every Java module HermiT needs at runtime.

Dockerfile.worker builds a trimmed JRE with ``jlink --add-modules``. A module
missing from that list does not fail the build: it fails the first
``sync_reasoner`` call, deep inside HermiT, with ``NoClassDefFoundError``. That is
how ``java.desktop`` went missing (HermiT's bundled ``rationals`` automaton
library uses ``java.awt.geom.Point2D``). These checks keep the list honest:

* a static check that the module list covers HermiT's runtime set, and
* a ``jdeps`` check (when a JDK and owlready2 are installed) that the runtime set
  still matches what owlready2's bundled ``HermiT.jar`` actually depends on, so an
  owlready2 bump that pulls in a new module fails here instead of in the worker.

The image-level proof (a real HermiT run inside the built worker) lives in
``tests/bench/test_worker_image_hermit.py``.
"""
from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Modules HermiT loads classes from when owlready2 runs it
# (``org.semanticweb.HermiT.cli.CommandLine``). jdeps omits java.xml from
# --print-module-deps because HermiT.jar bundles xml-apis split packages, but a
# package in a named module always wins over the classpath, so the JDK's java.xml
# is the one that loads.
HERMIT_RUNTIME_MODULES = frozenset({"java.base", "java.desktop", "java.logging", "java.xml"})

# Modules jdeps reports that HermiT never reaches, each with the reason. Adding
# one here needs the same evidence: no class HermiT runs references it.
HERMIT_UNREACHED_MODULES = {
    # Only org.semanticweb.owlapi.reasoner.TimedConsoleProgressMonitor uses
    # java.lang.management, and nothing in HermiT.jar references that class.
    "java.management": "OWLAPI TimedConsoleProgressMonitor only; unreferenced",
}


def _jlink_modules() -> set[str]:
    text = (REPO_ROOT / "Dockerfile.worker").read_text(encoding="utf-8")
    found = re.findall(r"jlink\"?\s*\\?\s*--add-modules\s+(\S+)", text)
    assert len(found) == 1, f"expected one jlink --add-modules list, found {found}"
    return set(found[0].split(","))


def test_jlink_includes_hermit_runtime_modules() -> None:
    missing = HERMIT_RUNTIME_MODULES - _jlink_modules()
    assert not missing, (
        f"Dockerfile.worker jlink --add-modules lacks {sorted(missing)}; HermiT "
        "fails at reasoning time with NoClassDefFoundError without them"
    )


def _hermit_jar() -> Path | None:
    spec = importlib.util.find_spec("owlready2")
    if spec is None or spec.origin is None:
        return None
    jar = Path(spec.origin).parent / "hermit" / "HermiT.jar"
    return jar if jar.is_file() else None


@pytest.mark.skipif(shutil.which("jdeps") is None, reason="jdeps (JDK) not on PATH")
def test_hermit_jar_module_deps_match_runtime_set() -> None:
    jar = _hermit_jar()
    if jar is None:
        pytest.skip("owlready2 with its bundled HermiT.jar is not installed")
    result = subprocess.run(
        [
            "jdeps", "--multi-release", "17", "--ignore-missing-deps",
            "--print-module-deps", "-cp", str(jar), str(jar),
        ],
        capture_output=True, text=True, check=False, timeout=25,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    # jdeps prints split-package warnings on stdout; the module list is the
    # last line that is not a warning.
    lines = [ln.strip() for ln in result.stdout.splitlines()
             if ln.strip() and not ln.startswith("Warning:")]
    assert lines, result.stdout + result.stderr
    reported = set(lines[-1].split(","))

    unexplained = reported - HERMIT_RUNTIME_MODULES - set(HERMIT_UNREACHED_MODULES)
    assert not unexplained, (
        f"HermiT.jar now depends on {sorted(unexplained)}. Add each to the "
        "jlink --add-modules list in Dockerfile.worker and to "
        "HERMIT_RUNTIME_MODULES (or justify it in HERMIT_UNREACHED_MODULES)."
    )
    needed = reported - set(HERMIT_UNREACHED_MODULES)
    assert needed <= _jlink_modules(), sorted(needed - _jlink_modules())
