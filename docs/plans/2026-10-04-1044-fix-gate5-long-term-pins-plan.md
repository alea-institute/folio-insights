---
title: Gate 5 Long-Term Pins - Plan
type: fix
date: 2026-10-04
artifact_contract: ce-unified-plan/v1
execution: code
---

# Gate 5 Long-Term Pins - Plan

## Goal Capsule

- Objective: Make the web and worker image builds reproducible over time, not just back to back. A rebuild months from now, at the same commit, must fetch the same bytes or fail loudly.
- Authority: Orchestrator task (2026-10-04) on branch `fix/gate5-long-term-pins`. It follows PR #7, which made Gate 5 pass back to back. There is no push or deploy in this lane.
- Inputs: `ci/build.py`, `Dockerfile.web`, `Dockerfile.worker`, `Dockerfile`, `uv.lock`, the requirements locks, and `tests/bench/test_gate5_digest.py`.
- Stop conditions: Stop if Gate 5 fails, a cold `--no-cache` rebuild digest differs from Gate 5, a smoke import fails, or the fast suite regresses.

## Drift Sources and Decisions

| # | Source | Reaches image bytes? | Decision |
|---|---|---|---|
| D1 | `COPY --from=ghcr.io/astral-sh/uv:latest` | Yes. uv writes venv metadata and installs the packages. | Use `UV_IMAGE=ghcr.io/astral-sh/uv:0.12.23@sha256:61d3…5b21` in a named stage, so `COPY --from` resolves to a pinned stage. The legacy `Dockerfile` pins the same ref. |
| D2 | Web deps from `uv pip install .`, which resolves at build time | Yes. The image carried torch 2.14.1 while `uv.lock` said 2.11.0. | Run `scripts/export_image_locks.py` to export `requirements.lock` from `uv.lock` with every hash, and install it with `--require-hashes --only-binary :all:`. |
| D3 | `folio-propositions` git dependency, which cannot carry a hash | Yes | Pin it to the full commit SHA in `requirements.vcs.lock`, taken from `uv.lock`, and install it with `--no-deps`. |
| D4 | Build backends fetched unpinned by build isolation: hatchling, setuptools, wheel, Cython | Yes. Their versions reach the WHEEL metadata and Cython-generated C. | Pass `--build-constraints requirements.build.lock`. uv hash-verifies it, as checked with a bad-hash probe. |
| D5 | Worker builder runs `apk add gcc g++ musl-dev python3-dev libffi-dev` unpinned | Yes. The compiler builds owlready2's optimizer `.so`, which ships. | Reduce the set to `gcc musl-dev`. Pin the full apk closure (13 packages) in `apk.worker-build.lock` with `scripts/resolve_apk_pins.sh`. |
| D6 | Worker runtime runs `apk add libgcc libstdc++ sqlite-libs` unpinned | Yes | Remove the step. pyoxigraph vendors libgcc_s and libstdc++. The JRE links neither. sqlite-libs ships in the base image. |
| D7 | Web builder `build-essential` | No compile happens under `--only-binary :all:` | Remove it. |
| D8 | Web builder apt `git` | No. It only checks out a commit-pinned tree. | Leave it unpinned and document why. |
| D9 | Build context taken from the working tree | Yes. COPY carries mtimes and modes, and rewrite-timestamp only clamps times newer than the epoch. The cold rebuild exposed this: directory mtimes moved when Python wrote `__pycache__`. | `ci/build.py` exports `git archive HEAD` of the COPY'd paths, so every mtime is the commit time and modes are 0644/0755. |
| D10 | The `jre-builder` stage has no `SOURCE_DATE_EPOCH` ARG | Yes. A jlink layer cached under an earlier commit kept its older mtimes, so the warm worker digest differed from the cold one. | Add `ARG`/`ENV SOURCE_DATE_EPOCH` to the stage. A test requires the ARG in every stage that has a RUN. |

## Implementation Units

- U1: Implement D1–D4 and D7 in `Dockerfile.web`, add the export script and the new locks, and record the uv digest in `.env.docker.example`.
- U2: Implement D1, D4, D5 and D6 in `Dockerfile.worker`, and add the apk resolve script and its lock.
- U3: Add a `docker buildx` check to `_missing_build_tooling`, with unit tests. Add `tests/test_image_pins.py` to check the digest pins, hash coverage, VCS commit pins, apk exact pins, `uv.lock` export freshness, and the `.env.docker.example` mirror.
- U4: Update the `ci/build.py` docstring and add the build tooling to `THIRD-PARTY.md`.

## Verification

- Gate 5 required run: `GATE5_REQUIRED=1 … -m gate5 tests/bench/test_gate5_digest.py`.
- A cold `docker buildx build --no-cache` of both images, with ci/build.py's arguments, must give the Gate 5 digests.
- Web smoke test: import folio_insights, folio_propositions, fastapi and api.main, and confirm there is no gcc or git.
- Worker smoke test: import owlready2 and pyoxigraph.
- The fast suite and ruff on `ci` must pass.

## Residual Risk

- Alpine keeps only the newest build per branch. When v3.23 ships an update to a pinned toolchain package, the worker build fails with "unable to select packages". To recover, re-run `scripts/resolve_apk_pins.sh`, rebuild, and re-run Gate 5. This is a loud failure, not silent drift.
- Upstream registries must keep serving the pinned artifacts: PyPI files, GitHub commits, and the ghcr and Docker Hub digests.
