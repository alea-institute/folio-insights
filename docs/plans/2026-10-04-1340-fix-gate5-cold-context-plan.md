---
title: Gate 5 Cold Context, Web Stage Order and Dagger Test Stage - Plan
type: fix
date: 2026-10-04
artifact_contract: ce-unified-plan/v1
execution: code
---

# Gate 5 Cold Context, Web Stage Order and Dagger Test Stage - Plan

## Goal Capsule

- Objective: Close three build follow-ups left by the long-term pins work (`2026-10-04-1044-fix-gate5-long-term-pins-plan.md`): cold-rebuild drift, web runtime stage ordering, and a red Dagger `_test` stage.
- Authority: Orchestrator task (2026-10-04) on branch `fix/gate5-cold-context`, based on `origin/master` with PRs #18 and #19. There is no push in this lane.
- Stop conditions: Stop if Gate 5 fails, a cold `--no-cache` rebuild differs from Gate 5, a smoke check fails, or the fast suite regresses.

## Findings and Decisions

| # | Problem | Root cause | Decision |
|---|---|---|---|
| F1 | A cold worker rebuild could differ from Gate 5 by the `/app/src` directory mtime, intermittently, on unmodified master. | BuildKit keeps each local context it receives. For a later context with the same directory basename, it transfers only the difference. buildx's shared key ignores the parent path. That diff never updates a directory whose children are unchanged, even when the directory's own mtime changed. `ci.build` always exported to `<tmp>/context`, so a build inherited directory mtimes from an earlier run, usually an earlier commit. Those mtimes predate `SOURCE_DATE_EPOCH`, and `rewrite-timestamp` only clamps newer times. The web and worker builds raced for the one cached transfer, so whichever build lost the race got a full copy. That race made the drift intermittent. | `export_image_contexts` gives each Dockerfile its own `mkdtemp`-named context, so every build gets a full transfer. A tarball context was rejected: BuildKit does not apply `.dockerignore` to it, and it carries tar ownership, so it would need a reimplementation of the ignore semantics. |
| F2 | The web runtime stage opened with `WORKDIR /app`. | A WORKDIR or COPY cache key lacks `SOURCE_DATE_EPOCH`. | The user-creating RUN comes first and creates `/app`. The later COPYs use `--chown`. The strict xfail is gone. |
| F3 | The Dagger `_test` stage had 31 failed and 13 errors. | The container had no git, uv, folio-propositions, folio-enrich, or polysemy fixtures. One test also invoked `uv run`. | Install git and the pinned uv. Install folio-propositions from `requirements.vcs.lock` with `--no-deps`. Mark the 5 folio-enrich ingestion tests `integration` and deselect them in the container. Re-include the polysemy fixtures in the test context. Run the bench CLI under `sys.executable`. |

## Evidence of F1 Root Cause

A minimal Dockerfile ran `COPY src/ /x/src/` and then `stat` on the copied files:

- The first build of `p/ctx`, with the `src` mtime set to 1100000000, reported 1100000000.
- `q/ctx`, a different parent directory with the same basename, the same file content, and an `src` mtime of 1200000000, also reported **1100000000**.
- A different basename (`c2`) reported its own mtime.

## Verification

- Gate 5 required run.
- Two cold `--no-cache` rebuilds of both images, from fresh `export_image_contexts` directories with `ci/build.py`'s arguments, must equal Gate 5.
- `python -m ci.build` with lint and test enabled must pass.
- Web smoke: the imports work and `/health` returns 200. Worker smoke: owlready2, pyoxigraph and HermiT work.
- The fast suite, scoped ruff, `export_image_locks.py --check` and `check_exclusions.py --history origin/master` must pass.

## Residual Risk

- Each build leaves its own local-context record in BuildKit. The contexts are small, and builder GC reclaims them; moby's default policy prunes unused `source.local` records first. This box's GC configuration was not inspected.
