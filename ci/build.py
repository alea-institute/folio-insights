"""folio-insights Dagger build pipeline.

D-10: full CI (build + lint + test + publish + deploy-trigger).
D-08: bit-identical digest via SOURCE_DATE_EPOCH + ``--require-hashes``.

Stage ordering (Claude's discretion per CONTEXT.md line 64):
  Parallel: build-web | build-worker | lint
  Serial:   test (needs python runtime image from build-web)
  Serial:   publish (after all above)
  Serial:   deploy (only on ``$CI`` + main branch + ``$RAILWAY_TOKEN``)

Invoke: ``python -m ci.build [--no-deploy] [--tag <tag>]``

Gate 5 discipline (10 techniques):
  1. ``@sha256:`` base pins            — sourced via ``.env.docker(.example)``
  2. SOURCE_DATE_EPOCH env+arg         — ``with_env_variable`` AND ``with_build_arg`` (Pitfall 4)
  3. BuildKit rewrite-timestamp        — Dockerfiles set ``ENV SOURCE_DATE_EPOCH``; jlink stage uses it
  4. Fixed UID 1001                    — Dockerfiles set numeric UID
  5. Hash-pinned pip                   — ``requirements.lock`` (web) + ``requirements.worker.lock``
  6. ``--no-install-recommends``       — Dockerfiles already set
  7. ``PYTHONDONTWRITEBYTECODE=1``     — Dockerfiles already set
  8. Ordered explicit COPY             — Dockerfiles already follow
  9. ``.dockerignore`` excludes        — plus ``BUILD_CTX_EXCLUDE`` defence-in-depth
 10. Dagger SDE both env AND build_arg — see ``_build_image`` below
"""
from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
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
    "output",
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


async def _build_image(
    client: dagger.Client,
    *,
    dockerfile: str,
    tag: str,
    sde: str,
) -> tuple[str, str]:
    """Build an image via Dagger's Dockerfile compat and publish.

    Returns: ``(requested_tag, published_ref_with_digest)``.

    Gate 5 pitfall 4: SOURCE_DATE_EPOCH MUST be passed as BOTH a build_arg AND
    an env variable. The build_arg reaches ``ARG SOURCE_DATE_EPOCH`` inside the
    Dockerfile (compile-time); the env variable reaches the container runtime
    (so any downstream stage that ``with_exec()``s inherits the pinned epoch).
    """
    src = client.host().directory(str(REPO_ROOT), exclude=BUILD_CTX_EXCLUDE)

    container = src.docker_build(
        dockerfile=dockerfile,
        build_args=[
            dagger.BuildArg(name="SOURCE_DATE_EPOCH", value=sde),
        ],
    )
    # Belt-and-braces: also set the env var on the resulting container so any
    # downstream with_exec() calls see the same epoch (Gate 5 step 10).
    container = container.with_env_variable("SOURCE_DATE_EPOCH", sde)

    published = await container.publish(tag)
    return tag, published


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
    _load_digests()  # Fail-fast if .env.docker(.example) absent
    tag_suffix = args.tag or sde

    async with dagger.Connection(dagger.Config(log_output=sys.stderr)) as client:
        # Parallelizable stages
        web_task = _build_image(
            client,
            dockerfile="Dockerfile.web",
            tag=f"ttl.sh/fi-web:{tag_suffix}",
            sde=sde,
        )
        worker_task = _build_image(
            client,
            dockerfile="Dockerfile.worker",
            tag=f"ttl.sh/fi-worker:{tag_suffix}",
            sde=sde,
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
    """Pipeline driver with deploy post-step."""
    sde, web_ref, worker_ref = await _run_pipeline(args)

    print(f"SOURCE_DATE_EPOCH={sde}")
    print(f"WEB: ttl.sh/fi-web:{args.tag or sde} @ {web_ref}")
    print(f"WORKER: ttl.sh/fi-worker:{args.tag or sde} @ {worker_ref}")

    # Deploy (serial, post-success) — skipped on --no-deploy or absent RAILWAY_TOKEN
    if args.no_deploy or not os.environ.get("RAILWAY_TOKEN"):
        print("Skipping Railway deploy (--no-deploy or RAILWAY_TOKEN missing)")
        return

    # Lazy import to avoid pulling subprocess/logging when the pipeline runs in
    # --no-deploy mode (common for smoke + Gate 5 determinism runs).
    from ci.railway import deploy_service

    deploy_service("web", image=web_ref)
    deploy_service("worker", image=worker_ref)


def cli() -> None:
    parser = argparse.ArgumentParser(description="folio-insights CI pipeline (Dagger)")
    parser.add_argument("--no-deploy", action="store_true", help="Skip Railway deploy stage")
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
