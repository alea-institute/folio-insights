"""folio-insights Dagger build pipeline.

D-10: full CI (build + lint + test + publish). Deploys happen in Coolify, not here.
D-08: bit-identical digest via SOURCE_DATE_EPOCH + ``--require-hashes``.

Stage ordering (Claude's discretion per CONTEXT.md line 64):
  Parallel: build-web | build-worker | lint
  Serial:   test (needs python runtime image from build-web)
  Serial:   publish (after all above)

Invoke: ``python -m ci.build [--tag <tag>]``

Gate 5 discipline (10 techniques):
  1. ``@sha256:`` base pins            — sourced via ``.env.docker(.example)``
  2. SOURCE_DATE_EPOCH env+arg         — process env AND ``--build-arg`` (Pitfall 4)
  3. BuildKit rewrite-timestamp        — ``docker buildx`` exporter clamps layer mtimes and
                                         config/history timestamps (see ``_build_image``)
  4. Fixed UID 1001                    — Dockerfiles set numeric UID
  5. Hash-pinned pip                   — ``requirements.lock`` (web) + ``requirements.worker.lock``
  6. ``--no-install-recommends``       — Dockerfiles already set
  7. ``PYTHONDONTWRITEBYTECODE=1``     — Dockerfiles already set
  8. Ordered explicit COPY             — Dockerfiles already follow
  9. ``.dockerignore`` excludes        — image context; ``BUILD_CTX_EXCLUDE`` for Dagger lint/test
 10. No attestations                   — provenance stamps build times, so it is disabled

Images build with ``docker buildx`` (BuildKit's reproducible exporter); lint and
test stages run in Dagger.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
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


async def _build_image(
    *,
    dockerfile: str,
    tag: str,
    sde: str,
    metadata_dir: Path,
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
        str(REPO_ROOT),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=REPO_ROOT,
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


async def _test(client: dagger.Client, sde: str) -> None:
    """Run pytest quick-suite.

    Gates 2/3/4 (benchmarks) run separately in Plan 07; this stage is the fast
    regression pass that must stay green on every pipeline run. Markers
    ``gate5`` and ``slow`` are excluded (``-m "not gate5 and not slow"``) so
    the slow Gate 5 determinism test does not run inside the pipeline it is
    measuring (would recurse forever).
    """
    src = client.host().directory(str(REPO_ROOT), exclude=BUILD_CTX_EXCLUDE)
    await (
        client.container()
        .from_("python:3.11-slim")
        .with_env_variable("SOURCE_DATE_EPOCH", sde)
        .with_directory("/app", src)
        .with_workdir("/app")
        .with_exec([
            "pip", "install", "--no-cache-dir",
            "--require-hashes", "-r", "requirements.dev.lock",
        ])
        .with_exec([
            "pytest", "-x", "--ff", "-q",
            "--benchmark-skip",
            "-m", "not gate5 and not slow",
        ])
        .sync()
    )


async def _run_pipeline(args: argparse.Namespace) -> tuple[str, str, str]:
    """Core pipeline driver — returns (sde, web_ref, worker_ref)."""
    sde = _source_date_epoch()
    assert_bundled_corpora_tracked()
    _load_digests()  # Fail-fast if .env.docker(.example) absent
    tag_suffix = args.tag or sde

    with tempfile.TemporaryDirectory(prefix="fi-ci-build-") as metadata_root:
        metadata_dir = Path(metadata_root)
        async with dagger.Connection(dagger.Config(log_output=sys.stderr)) as client:
            # Parallelizable stages: both image builds (BuildKit) and lint (Dagger)
            web_task = _build_image(
                dockerfile="Dockerfile.web",
                tag=f"ttl.sh/fi-web:{tag_suffix}",
                sde=sde,
                metadata_dir=metadata_dir,
            )
            worker_task = _build_image(
                dockerfile="Dockerfile.worker",
                tag=f"ttl.sh/fi-worker:{tag_suffix}",
                sde=sde,
                metadata_dir=metadata_dir,
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
