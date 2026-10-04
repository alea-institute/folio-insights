"""Gate 5 over time: every input that reaches the image bytes stays pinned.

Back-to-back builds (tests/bench/test_gate5_digest.py) only prove determinism at
one moment. These static checks keep the inputs from floating, so a rebuild
months later fetches the same bytes: digest-pinned images, hash-pinned Python
locks that match uv.lock, hash-verified build backends, and exact apk versions.
"""
from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GATE5_DOCKERFILES = ("Dockerfile.web", "Dockerfile.worker")
_DIGEST_REF = re.compile(r"^[^\s@]+:[^\s@]+@sha256:[0-9a-f]{64}$")


def _read(name: str) -> str:
    return (REPO_ROOT / name).read_text(encoding="utf-8")


def _image_args(dockerfile: str) -> dict[str, str]:
    return dict(re.findall(r"^ARG (\w+_IMAGE)=(\S+)", _read(dockerfile), re.M))


@pytest.mark.parametrize("dockerfile", GATE5_DOCKERFILES)
def test_every_image_is_digest_pinned(dockerfile: str) -> None:
    text = _read(dockerfile)
    args = _image_args(dockerfile)
    for name, ref in args.items():
        assert _DIGEST_REF.match(ref), f"{dockerfile}: {name}={ref} is not tag@sha256"
    stages = set(re.findall(r"^FROM \S+ AS (\S+)", text, re.M))
    for ref in re.findall(r"^FROM (\S+)", text, re.M):
        assert ref.startswith("${") and ref[2:-1] in args, f"{dockerfile}: FROM {ref}"
    for src in re.findall(r"COPY --from=(\S+)", text):
        assert src in stages, f"{dockerfile}: COPY --from={src} is not a pinned stage"


def test_uv_image_matches_across_dockerfiles() -> None:
    web = _image_args("Dockerfile.web")["UV_IMAGE"]
    assert _image_args("Dockerfile.worker")["UV_IMAGE"] == web
    assert f"COPY --from={web} " in _read("Dockerfile")


def _instructions_of(text: str) -> list[str]:
    """Dockerfile instructions with comments dropped and continuations joined."""
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    return [ins.strip() for ins in "\n".join(lines).replace("\\\n", " ").splitlines()
            if ins.strip()]


def _instructions(dockerfile: str) -> list[str]:
    return _instructions_of(_read(dockerfile))


def test_no_floating_latest_tags() -> None:
    for name in ("Dockerfile", *GATE5_DOCKERFILES):
        for ins in _instructions(name):
            assert ":latest" not in ins, f"{name}: {ins}"


def test_web_installs_only_from_hashed_locks() -> None:
    installs = [
        part for ins in _instructions("Dockerfile.web") if ins.startswith("RUN")
        for part in ins.split("&&") if "uv pip install" in part
    ]
    assert len(installs) == 3, installs
    first = " ".join(installs[0].split())
    assert "--require-hashes --only-binary :all: -r requirements.lock" in first
    for cmd in installs[1:]:
        assert "--no-deps" in cmd and "--build-constraints requirements.build.lock" in cmd


def test_worker_installs_only_from_hashed_locks() -> None:
    text = _read("Dockerfile.worker")
    assert "--require-hashes" in text
    assert "--only-binary :all: --no-binary owlready2" in text
    assert "--build-constraints requirements.build.lock" in text
    assert "-r requirements.worker.lock" in text
    assert "pip install" not in text.replace("uv pip install", "")


def _lock_entries(name: str) -> dict[str, str]:
    """``{package: entry_text}`` for a pip-style hash lock."""
    out: dict[str, str] = {}
    current = None
    for line in _read(name).splitlines():
        match = re.match(r"^([A-Za-z0-9][\w.-]*)==\S+", line)
        if match:
            current = match.group(1).lower()
            out[current] = ""
        elif current and line.startswith("    "):
            out[current] += line
    return out


@pytest.mark.parametrize(
    "lock",
    [
        "requirements.lock", "requirements.worker.lock", "requirements.build.lock",
        "requirements.dev.lock",
    ],
)
def test_python_locks_hash_every_entry(lock: str) -> None:
    entries = _lock_entries(lock)
    assert entries, lock
    for name, body in entries.items():
        assert "--hash=sha256:" in body, f"{lock}: {name} has no hash"
    text = _read(lock)
    assert " @ " not in text, f"{lock}: direct-URL requirements cannot be hashed"


def test_vcs_lock_pins_full_commits() -> None:
    lines = [ln for ln in _read("requirements.vcs.lock").splitlines()
             if ln and not ln.startswith("#")]
    assert lines
    for line in lines:
        assert re.fullmatch(r"[\w.-]+ @ git\+https://\S+@[0-9a-f]{40}", line), line


def test_build_constraints_cover_this_projects_backend() -> None:
    requires = tomllib.loads(_read("pyproject.toml"))["build-system"]["requires"]
    pinned = _lock_entries("requirements.build.lock")
    for req in requires:
        name = re.split(r"[\s<>=!~;\[]", req, maxsplit=1)[0].lower()
        assert name in pinned, f"build backend {name} not in requirements.build.lock"
    # owlready2's sdist [build-system] (worker): setuptools, wheel, Cython.
    for name in ("setuptools", "wheel", "cython"):
        assert name in pinned


def test_apk_lock_pins_exact_versions() -> None:
    pins = [ln for ln in _read("apk.worker-build.lock").splitlines()
            if ln and not ln.startswith("#")]
    assert {"gcc", "musl-dev", "binutils"} <= {p.split("=", 1)[0] for p in pins}
    for pin in pins:
        assert re.fullmatch(r"[\w.+-]+=[\w.]+-r\d+", pin), pin
    worker = _read("Dockerfile.worker")
    assert "apk add --no-cache $(grep -v '^#' apk.worker-build.lock)" in worker
    assert worker.count("apk add") == 1, "runtime stage must not install apk packages"


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not on PATH")
def test_web_locks_match_uv_lock() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/export_image_locks.py", "--check"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _load_export_script():
    spec = importlib.util.spec_from_file_location(
        "export_image_locks", REPO_ROOT / "scripts" / "export_image_locks.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not on PATH")
def test_dev_lock_matches_uv_lock() -> None:
    """The CI test container (ci/build.py ``_test``) installs requirements.dev.lock
    with --require-hashes; it must be the uv.lock closure plus the dev extra, not a
    stale one-off compile (it once still pinned folio-resolve 0.3.1, no fastapi)."""
    export = _load_export_script()
    expected = export.render(REPO_ROOT)[export.DEV_LOCK]
    assert _read("requirements.dev.lock") == expected, (
        "requirements.dev.lock is stale; run scripts/export_image_locks.py"
    )


def test_dev_lock_covers_runtime_and_dev_extra() -> None:
    dev = _lock_entries("requirements.dev.lock")
    runtime = _lock_entries("requirements.lock")
    assert set(runtime) <= set(dev), sorted(set(runtime) - set(dev))
    for name, body in runtime.items():
        hashes = set(re.findall(r"--hash=sha256:[0-9a-f]{64}", body))
        assert hashes == set(re.findall(r"--hash=sha256:[0-9a-f]{64}", dev[name])), (
            f"{name}: dev lock pins a different artifact set than requirements.lock"
        )
    project = tomllib.loads(_read("pyproject.toml"))["project"]
    for req in project["optional-dependencies"]["dev"]:
        name = re.split(r"[\s<>=!~;\[]", req, maxsplit=1)[0].lower()
        assert name in dev, f"dev extra {name} missing from requirements.dev.lock"


def test_env_example_mirrors_dockerfile_digests() -> None:
    digests = re.findall(r"^\w+_DIGEST=(sha256:[0-9a-f]{64})$", _read(".env.docker.example"), re.M)
    pinned = {ref.split("@", 1)[1] for df in GATE5_DOCKERFILES for ref in _image_args(df).values()}
    assert set(digests) == pinned


@pytest.mark.parametrize("dockerfile", GATE5_DOCKERFILES)
def test_every_run_stage_keys_its_cache_on_source_date_epoch(dockerfile: str) -> None:
    """A stage with RUN but no SOURCE_DATE_EPOCH ARG reuses layers cached under an
    earlier commit, whose mtimes predate the epoch and escape rewrite-timestamp."""
    stages = re.split(r"^FROM ", _read(dockerfile), flags=re.M)[1:]
    for stage in stages:
        name = stage.split("\n", 1)[0]
        if re.search(r"^RUN ", stage, re.M):
            assert re.search(r"^ARG SOURCE_DATE_EPOCH", stage, re.M), f"{dockerfile}: {name}"


@pytest.mark.parametrize(
    "dockerfile",
    [
        "Dockerfile.worker",
        pytest.param(
            "Dockerfile.web",
            marks=pytest.mark.xfail(
                strict=True,
                reason="known gap: the web runtime stage opens with WORKDIR /app, so "
                "that layer can be reused from an earlier commit's build",
            ),
        ),
    ],
)
def test_runtime_stage_starts_with_an_epoch_keyed_run(dockerfile: str) -> None:
    """A RUN's cache key includes SOURCE_DATE_EPOCH; COPY and WORKDIR keys do not
    (BuildKit keys COPY --from on source content, not mtimes). A filesystem step
    ahead of the runtime stage's first RUN is reused from a build under an earlier
    commit, carrying wall-clock mtimes older than the new epoch that
    rewrite-timestamp leaves alone, so warm and cold builds diverge."""
    final_stage = re.split(r"^FROM ", _read(dockerfile), flags=re.M)[-1]
    steps = [
        ins.split(None, 1)[0]
        for ins in _instructions_of(final_stage)
        if ins.split(None, 1)[0] in {"RUN", "COPY", "ADD", "WORKDIR"}
    ]
    assert steps and steps[0] == "RUN", f"{dockerfile}: runtime stage begins with {steps[:1]}"
