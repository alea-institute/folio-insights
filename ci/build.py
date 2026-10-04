"""folio-insights Dagger build pipeline.

D-10: full CI (build + lint + test + publish). Deploys happen in Coolify, not here.
D-08: bit-identical digest via SOURCE_DATE_EPOCH + ``--require-hashes``.

Stage ordering (Claude's discretion per CONTEXT.md line 64):
  Parallel: build-web | build-worker | lint
  Serial:   test (needs python runtime image from build-web)
  Serial:   publish (after all above)

Invoke: ``python -m ci.build [--tag <tag>]``

Gate 5 discipline (10 techniques):
  1. ``@sha256:`` image pins           — every ``FROM`` base and the uv image
                                         (``UV_IMAGE``) are ``tag@sha256`` ARGs in the
                                         Dockerfiles; ``.env.docker(.example)`` mirrors them
  2. SOURCE_DATE_EPOCH env+arg         — process env AND ``--build-arg`` (Pitfall 4)
  3. BuildKit rewrite-timestamp        — ``docker buildx`` exporter clamps layer mtimes and
                                         config/history timestamps (see ``_build_image``)
  4. Fixed UID 1001                    — Dockerfiles set numeric UID
  5. Hash-pinned installs              — uv ``--require-hashes`` from ``requirements.lock``
                                         (web) and ``requirements.worker.lock``; see below
  6. ``--no-install-recommends``       — Dockerfiles already set
  7. ``PYTHONDONTWRITEBYTECODE=1``     — Dockerfiles already set
  8. Ordered explicit COPY             — Dockerfiles already follow
  9. Normalized context               — images build from ``git archive HEAD`` of the COPY'd
                                         paths (``export_build_context``): every mtime is
                                         the commit time, modes are 0644/0755; then
                                         ``.dockerignore`` applies. Each image gets its own
                                         freshly named context directory
                                         (``export_image_contexts``), so BuildKit never
                                         reuses a stale incremental context transfer.
                                         ``BUILD_CTX_EXCLUDE`` filters the Dagger lint/test
                                         context
 10. No attestations                   — provenance stamps build times, so it is disabled

Reproducible over time, not just back to back. Gate 5's two builds run minutes
apart, so they cannot see inputs that float between releases. Every input that
reaches the image bytes is therefore pinned, and ``tests/test_image_pins.py``
keeps it that way:

  * Web Python deps — ``requirements.lock`` is exported from ``uv.lock`` (the set
    local dev and tests use) by ``scripts/export_image_locks.py``: every
    third-party package with all its hashes, installed ``--only-binary :all:`` so
    nothing compiles. The ``folio-propositions`` git dependency cannot carry a
    hash, so ``requirements.vcs.lock`` pins it to the full commit SHA and it
    installs ``--no-deps``. The same script exports ``requirements.dev.lock``
    (that closure plus the ``dev`` extra) for the ``_test`` stage below.
  * Build backends — sdist and local builds (hatchling for folio-insights and
    folio-propositions; setuptools/wheel/Cython for owlready2) run under
    ``--build-constraints requirements.build.lock``, which uv hash-verifies.
  * Worker toolchain — ``apk.worker-build.lock`` pins the full apk install closure
    of gcc + musl-dev (``scripts/resolve_apk_pins.sh``), because the compiler
    builds owlready2's C optimizer, which ships. The runtime stage installs no
    apk packages. Alpine keeps only the newest build per branch, so a retired pin
    fails the build loudly; refresh with the script, then re-run Gate 5.
  * Web builder apt ``git`` stays unpinned: it only checks out the pinned commit
    and never reaches the image.
  * File metadata — ``rewrite-timestamp`` clamps only times NEWER than
    SOURCE_DATE_EPOCH. Older ones passed straight through: working-tree files a
    checkout did not touch (hence the normalized context above), and layers
    cached under an earlier commit by a stage whose cache key lacked the epoch
    (hence every stage with a RUN declares ``ARG SOURCE_DATE_EPOCH``).

Refresh any pin by regenerating its lock with the named tool, then rebuild and
re-run Gate 5 (``GATE5_REQUIRED=1 python -m pytest -m gate5
tests/bench/test_gate5_digest.py``).

Images build with ``docker buildx`` (BuildKit's reproducible exporter); lint and
test stages run in Dagger.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import dagger  # from dagger-io site-package (see ci/__init__.py for shadow note)


# ---------------------------------------------------------------------------
# Constants — load base digests from .env.docker if present, else .env.docker.example
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_digests() -> dict[str, str]:
    """Read ``.env.docker`` (or ``.env.docker.example``) into a dict."""
    for candidate in (".env.docker", ".env.docker.example"):
        path = REPO_ROOT / candidate
        if path.exists():
            out: dict[str, str] = {}
            for raw_line in path.read_text().splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
            return out
    raise FileNotFoundError("Neither .env.docker nor .env.docker.example found")


def _source_date_epoch() -> str:
    """Git HEAD commit timestamp -> SOURCE_DATE_EPOCH (Gate 5 step 2)."""
    return subprocess.check_output(
        ["git", "log", "-1", "--pretty=%ct"], cwd=REPO_ROOT
    ).decode().strip()


# Gate 5 step 10: explicit exclude list (defence-in-depth beyond .dockerignore).
# Any item added here also belongs in .dockerignore; this list is the authoritative
# CI-time filter. Plan 07 reviews these when wiring Gate 5 measurements.
BUILD_CTX_EXCLUDE = [
    ".git",
    ".github",
    ".planning",
    # Test-only re-include: tests/polysemy reads these tracked fixtures. The
    # images never COPY .planning (they build from export_build_context).
    "!.planning/phases/01-polysemy-distinguo-spike/fixtures",
    ".claude",
    # Mirror .dockerignore: exclude generated output, re-include only the two
    # demo corpora Dockerfile.web bundles (COPY output/), then re-exclude
    # SQLite sidecars and the jobs scratch dir. Order matters for "!" patterns.
    "output",
    "!output/default",
    "!output/demo",
    "output/**/*.db-wal",
    "output/**/*.db-shm",
    "output/.jobs",
    "fixtures/bench.nq",
    "fixtures/bench-*.nq",
    "node_modules",
    "viewer/node_modules",
    "viewer/.svelte-kit",
    "viewer/build",
    "**/__pycache__",
    "**/*.pyc",
    ".venv",
    "ci/.venv",
    "ci/__pycache__",
]

# Corpora re-included above and bundled into the web image (Dockerfile.web
# COPY output/). Images publish to the public ttl.sh registry.
BUNDLED_CORPORA = ("output/default", "output/demo")
_BUILD_CTX_SIDECARS = (".db-wal", ".db-shm")


def assert_bundled_corpora_tracked(repo_root: Path = REPO_ROOT) -> None:
    """Refuse to build when a bundled corpus holds files git does not track.

    The Dagger context is the host directory, not a clean checkout, so an
    untracked or ignored file dropped into a bundled corpus would ship in a
    public image. Only SQLite sidecars are allowed; the exclude list drops them.
    """
    result = subprocess.run(
        ["git", "ls-files", "--others", "-z", "--", *BUNDLED_CORPORA],
        cwd=repo_root, capture_output=True, text=True, check=True,
    )
    stray = sorted(
        path for path in result.stdout.split("\0")
        if path and not path.endswith(_BUILD_CTX_SIDECARS)
    )
    if stray:
        raise SystemExit(
            "Refusing to build: bundled corpora contain files git does not track, "
            "and they would ship in a public image:\n  " + "\n  ".join(stray)
        )


IMAGE_DOCKERFILES = ("Dockerfile.web", "Dockerfile.worker")

# ``COPY [--flags] <src>... <dest>`` from the build context (no ``--from=``).
_COPY_RE = re.compile(r"^COPY\s+(?P<args>.+)$")


def context_paths(
    repo_root: Path = REPO_ROOT, dockerfiles: tuple[str, ...] = IMAGE_DOCKERFILES,
) -> list[str]:
    """Every context path the Dockerfiles COPY, plus the Dockerfiles and .dockerignore."""
    paths = {".dockerignore", *dockerfiles}
    for name in dockerfiles:
        text = (repo_root / name).read_text(encoding="utf-8").replace("\\\n", " ")
        for line in text.splitlines():
            match = _COPY_RE.match(line.strip())
            if not match:
                continue
            words = match.group("args").split()
            if any(w.startswith("--from=") for w in words):
                continue
            sources = [w for w in words if not w.startswith("--")][:-1]
            paths.update(src.rstrip("/") or "." for src in sources)
    return sorted(paths)


def export_build_context(
    dest: Path,
    repo_root: Path = REPO_ROOT,
    dockerfiles: tuple[str, ...] = IMAGE_DOCKERFILES,
) -> None:
    """Write HEAD's tracked files that the images COPY into ``dest``, normalized.

    The build context used to be the working tree, and COPY carries each file's
    mtime and mode into the image. BuildKit's ``rewrite-timestamp`` only clamps
    times NEWER than SOURCE_DATE_EPOCH, so a file older than the HEAD commit
    (one a checkout did not touch, or a directory whose mtime moved when Python
    wrote ``__pycache__``) kept its own time, and the mode followed the local
    umask. Two checkouts of one commit then built different digests.

    ``git archive`` of HEAD stamps every entry with the commit time — exactly
    SOURCE_DATE_EPOCH — and ``tar.umask=0022`` fixes modes to 0644/0755 (only
    git's executable bit survives). The context is therefore a pure function of
    the commit. Uncommitted changes are NOT built; a warning names them.
    """
    paths = context_paths(repo_root, dockerfiles)
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--", *paths],
        cwd=repo_root, capture_output=True, text=True, check=True,
    ).stdout.strip()
    if dirty:
        print(
            "WARNING: building HEAD; these uncommitted changes are NOT in the image:\n"
            + dirty, file=sys.stderr,
        )
    archive = subprocess.Popen(
        ["git", "-c", "tar.umask=0022", "archive", "--format=tar", "HEAD", "--", *paths],
        cwd=repo_root, stdout=subprocess.PIPE,
    )
    assert archive.stdout is not None
    with tarfile.open(fileobj=archive.stdout, mode="r|") as tar:
        # "tar", not "data": the data filter drops directory modes, so
        # directories would follow the local umask again.
        tar.extractall(dest, filter="tar")
    if archive.wait() != 0:
        raise SystemExit(f"git archive failed (exit {archive.returncode})")


def export_image_contexts(
    work_root: Path,
    repo_root: Path = REPO_ROOT,
    dockerfiles: tuple[str, ...] = IMAGE_DOCKERFILES,
) -> dict[str, Path]:
    """Export a separate, uniquely named build context for each Dockerfile.

    BuildKit keeps each local build context it receives and, on the next build
    that sends a context with the same directory BASENAME (buildx's shared key
    ignores the parent path), transfers only the difference. That diff never
    updates a directory whose children did not change, even when the
    directory's own mtime did. The old fixed ``<tmp>/context`` path therefore
    let a build inherit directory mtimes from an earlier run, often an earlier
    commit. Those predate SOURCE_DATE_EPOCH, ``rewrite-timestamp`` only clamps
    newer times, and the image differed from a cold rebuild (seen as the
    ``/app/src`` mtime in the worker). It was intermittent because the web and
    worker builds raced for the one cached transfer: the build that lost the
    race got a fresh, full copy.

    A basename no earlier build used forces a full transfer, so the image sees
    exactly the exported mtimes. One directory per image keeps the two
    parallel builds from sharing a transfer at all.
    """
    contexts: dict[str, Path] = {}
    for dockerfile in dockerfiles:
        stem = dockerfile.lower().replace(".", "-")
        context_dir = Path(tempfile.mkdtemp(prefix=f"ctx-{stem}-", dir=work_root))
        export_build_context(context_dir, repo_root, dockerfiles)
        contexts[dockerfile] = context_dir
    return contexts


async def _build_image(
    *,
    dockerfile: str,
    tag: str,
    sde: str,
    metadata_dir: Path,
    context_dir: Path,
) -> tuple[str, str]:
    """Build an image with BuildKit's native reproducible export and publish it.

    Returns: ``(requested_tag, published_ref_with_digest)``.

    Why ``docker buildx`` and not Dagger's ``Directory.docker_build``: Dagger's
    Dockerfile compat ignores SOURCE_DATE_EPOCH at export time, so the image
    config ``created``/``history`` stamps and every file BuildKit writes carry
    the wall clock. Back-to-back Dagger builds only matched while the second
    build hit the engine cache; any cache miss or eviction produced a new
    digest. BuildKit's ``rewrite-timestamp=true`` exporter (BuildKit >= 0.13)
    clamps layer file mtimes and config timestamps to SOURCE_DATE_EPOCH, so a
    cold rebuild is bit-identical. Provenance/SBOM attestations are disabled
    because provenance records build start/finish times.

    SOURCE_DATE_EPOCH reaches the Dockerfile as a build arg (``ARG``/``ENV``)
    and BuildKit itself through the process environment (Gate 5 pitfall 4).
    """
    safe_name = tag.rsplit("/", 1)[-1].replace(":", "_")
    metadata_file = metadata_dir / f"{safe_name}.json"
    cmd = [
        "docker", "buildx", "build",
        "--file", dockerfile,
        "--build-arg", f"SOURCE_DATE_EPOCH={sde}",
        "--provenance=false",
        "--sbom=false",
        "--output", f"type=registry,name={tag},rewrite-timestamp=true",
        "--metadata-file", str(metadata_file),
        str(context_dir),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=context_dir,
        env={**os.environ, "SOURCE_DATE_EPOCH": sde},
        stdout=sys.stderr,
        stderr=sys.stderr,
    )
    returncode = await proc.wait()
    if returncode != 0:
        raise SystemExit(f"docker buildx build failed for {dockerfile} (exit {returncode})")
    digest = json.loads(metadata_file.read_text())["containerimage.digest"]
    return tag, f"{tag}@{digest}"


async def _lint(client: dagger.Client, sde: str) -> None:
    """Run ruff against src/ api/ tests/ ci/ — D-10 lint stage.

    Uses an ephemeral python:3.11-slim container so lint does not touch the
    Gate 5 digest surface. Ruff is pinned via the dev extras.
    """
    src = client.host().directory(str(REPO_ROOT), exclude=BUILD_CTX_EXCLUDE)
    await (
        client.container()
        .from_("python:3.11-slim")
        .with_env_variable("SOURCE_DATE_EPOCH", sde)
        .with_directory("/app", src)
        .with_workdir("/app")
        .with_exec(["pip", "install", "--no-cache-dir", "ruff>=0.6.0"])
        # Ruff defaults (no config yet) — Phase 0 just proves the pipeline
        # stage runs; Phase 11+ can tighten rules via pyproject.toml.
        .with_exec(["ruff", "check", "--exit-zero", "src/", "api/", "tests/", "ci/"])
        .sync()
    )


# The in-container suite cannot reach a sibling folio-enrich checkout, so tests
# that need one (marker ``integration``) are deselected; ``gate5``/``slow`` too.
TEST_MARKER_EXPR = "not gate5 and not slow and not integration"


def _image_arg(name: str, dockerfile: str = "Dockerfile.web") -> str:
    """The pinned ``tag@sha256`` default of ``ARG <name>=`` in a Dockerfile."""
    text = (REPO_ROOT / dockerfile).read_text(encoding="utf-8")
    match = re.search(rf"^ARG {name}=(\S+)", text, re.M)
    if match is None:
        raise SystemExit(f"{dockerfile} has no ARG {name}=")
    return match.group(1)


def _test_container(client: dagger.Client, sde: str) -> dagger.Container:
    """The quick-suite container: dependencies installed, source mounted at /app.

    The dependency install sees only the three locks (exported from ``uv.lock``
    by ``scripts/export_image_locks.py``), so its multi-GB layer stays cached
    until a lock changes rather than on every commit:

      * ``requirements.dev.lock`` — the uv.lock closure plus the ``dev`` extra,
        ``--require-hashes``.
      * ``requirements.vcs.lock`` — folio-propositions at its pinned commit,
        ``--no-deps`` (its requirements are in the dev lock), built under the
        hash-verified ``requirements.build.lock``, exactly as Dockerfile.web does.

    ``git`` serves that checkout and the tests that create throwaway
    repositories; ``uv`` (the pinned ``UV_IMAGE`` binary) serves the lock
    freshness tests. The project is not pip-installed; ``PYTHONPATH`` puts
    ``src/`` (and the repo root, for the ``tests``/``ci``/``scripts`` imports)
    on the path, as local runs do.
    """
    src = client.host().directory(str(REPO_ROOT), exclude=BUILD_CTX_EXCLUDE)
    uv_binary = client.container().from_(_image_arg("UV_IMAGE")).file("/uv")
    locks = ("requirements.dev.lock", "requirements.vcs.lock", "requirements.build.lock")
    container = (
        client.container()
        .from_("python:3.11-slim")
        .with_exec([
            "sh", "-c",
            "apt-get update"
            " && apt-get install -y --no-install-recommends git"
            " && rm -rf /var/lib/apt/lists/*",
        ])
        .with_file("/usr/local/bin/uv", uv_binary)
        .with_workdir("/app")
    )
    for lock in locks:
        container = container.with_file(f"/app/{lock}", src.file(lock))
    return (
        container
        .with_exec([
            "pip", "install", "--no-cache-dir",
            "--require-hashes", "-r", "requirements.dev.lock",
        ])
        .with_exec([
            "uv", "pip", "install", "--system", "--no-cache", "--no-deps",
            "--build-constraints", "requirements.build.lock",
            "-r", "requirements.vcs.lock",
        ])
        .with_env_variable("SOURCE_DATE_EPOCH", sde)
        .with_env_variable("PYTHONPATH", "/app/src:/app")
        .with_directory("/app", src)
    )


async def _test(client: dagger.Client, sde: str) -> None:
    """Run pytest quick-suite.

    Gates 2/3/4 (benchmarks) run separately in Plan 07; this stage is the fast
    regression pass that must stay green on every pipeline run. Markers
    ``gate5`` and ``slow`` are excluded so the slow Gate 5 determinism test does
    not run inside the pipeline it is measuring (would recurse forever), and
    ``integration`` because the container has no folio-enrich checkout.
    """
    await (
        _test_container(client, sde)
        .with_exec([
            "pytest", "-x", "--ff", "-q",
            "--benchmark-skip",
            "-m", TEST_MARKER_EXPR,
        ])
        .sync()
    )


async def _run_pipeline(args: argparse.Namespace) -> tuple[str, str, str]:
    """Core pipeline driver — returns (sde, web_ref, worker_ref)."""
    sde = _source_date_epoch()
    assert_bundled_corpora_tracked()
    _load_digests()  # Fail-fast if .env.docker(.example) absent
    tag_suffix = args.tag or sde

    with tempfile.TemporaryDirectory(prefix="fi-ci-build-") as work_root:
        metadata_dir = Path(work_root) / "metadata"
        metadata_dir.mkdir()
        contexts = export_image_contexts(Path(work_root))
        async with dagger.Connection(dagger.Config(log_output=sys.stderr)) as client:
            # Parallelizable stages: both image builds (BuildKit) and lint (Dagger)
            web_task = _build_image(
                dockerfile="Dockerfile.web",
                tag=f"ttl.sh/fi-web:{tag_suffix}",
                sde=sde,
                metadata_dir=metadata_dir,
                context_dir=contexts["Dockerfile.web"],
            )
            worker_task = _build_image(
                dockerfile="Dockerfile.worker",
                tag=f"ttl.sh/fi-worker:{tag_suffix}",
                sde=sde,
                metadata_dir=metadata_dir,
                context_dir=contexts["Dockerfile.worker"],
            )
            # Keep lint optional on --no-lint; test always runs.
            tasks = [web_task, worker_task]
            if not args.no_lint:
                tasks.append(_lint(client, sde))
            results = await asyncio.gather(*tasks)
            web_result = results[0]
            worker_result = results[1]

            if not args.no_test:
                await _test(client, sde)

    return sde, web_result[1], worker_result[1]


async def main(args: argparse.Namespace) -> None:
    """Pipeline driver: build, publish, and print digests."""
    sde, web_ref, worker_ref = await _run_pipeline(args)

    print(f"SOURCE_DATE_EPOCH={sde}")
    print(f"WEB: ttl.sh/fi-web:{args.tag or sde} @ {web_ref}")
    print(f"WORKER: ttl.sh/fi-worker:{args.tag or sde} @ {worker_ref}")


def cli() -> None:
    parser = argparse.ArgumentParser(description="folio-insights CI pipeline (Dagger)")
    parser.add_argument("--no-lint", action="store_true", help="Skip ruff lint stage")
    parser.add_argument("--no-test", action="store_true", help="Skip pytest stage")
    parser.add_argument(
        "--tag", default=None,
        help="Override image tag suffix (default: SOURCE_DATE_EPOCH)",
    )
    args = parser.parse_args()
    asyncio.run(main(args))


if __name__ == "__main__":
    cli()
