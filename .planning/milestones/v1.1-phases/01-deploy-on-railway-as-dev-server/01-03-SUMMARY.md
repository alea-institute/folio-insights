---
plan: 01-03
name: live-deploy-and-docs
status: complete
completed: 2026-04-12
tasks_complete: 2/2
---

# Plan 01-03: Live deploy + README/STATE docs

## Outcome

Deployed folio-insights to Railway as a dev server. Live URL:
**https://folio-insights-production.up.railway.app**

End-to-end verification (post-deploy):
- `GET /health` → 200 `{"status":"ok"}`
- `GET /` → 200 HTML (viewer bundle)
- `GET /api/v1/corpora` → 200 JSON, returns `test1` corpus from bundled data

## What was done

### Task 1 — User-driven Railway deploy (human-action checkpoint)
- `railway init --name folio-insights` created project `4a02ae26-caa8-41b3-871e-ad937919023c`
- `railway up` uploaded build context, Railway built the multi-stage Dockerfile
- First deploy **failed** at `COPY output/ ./output/` because `output/` was fully gitignored
- Fix: whitelisted `output/default/` and `output/test1/` in `.gitignore`, committed the
  22 baseline corpus files, redeployed
- Second deploy reached `status: SUCCESS` (~10 min build — dominated by torch/CUDA layers)
- `railway domain` generated `https://folio-insights-production.up.railway.app`
- `railway.toml` `/health` healthcheck with 120s timeout passed

### Task 2 — Docs + STATE.md
- Added `## Deploying to Railway` section to `README.md` — live URL, one-time setup
  commands (`railway login`/`init`/`service`), deploy command (`railway up`), domain
  command, verify snippet, and notes on data bundling + image size
- Appended two `[Phase 1]` decision entries to `.planning/STATE.md` Decisions section
  (live URL + gitignore whitelist rationale)

## Commits

- `feat(01-03): ship baseline corpora for Railway dev deploy` — gitignore whitelist + output/ data
- `docs(01-03): document Railway deploy workflow + record live URL` — README section + STATE.md decisions + SUMMARY

## Verification notes

- Only `test1` corpus is listed by the API on Railway (the `default` corpus directory
  contains only `review.db` with no `corpus-meta.json`, so the catalog loader skips it).
  This matches local behavior — not a deploy defect.
- Image size ~8.7 GB due to transitive torch+CUDA. Railway accepted it but build time
  is long. CPU-only torch pin would cut it to ~1-2 GB. Filed as deferred follow-up.
- GitHub auto-redeploy is NOT yet configured — the user can wire it via Railway
  dashboard (Service → Settings → Source → connect repo, branch=master) at their
  convenience. The manual `railway up` workflow is documented in the README.

## Deferred issues

- **CPU-only torch pin** — would slash image size from 8.7 GB to ~1-2 GB. Not blocking.
- **GitHub source connection** — requires browser dashboard step, out of scope for
  autonomous execution. User to complete when ready.
- **`default` corpus metadata** — empty `output/default/` directory is noise. Safe to
  delete or backfill with `corpus-meta.json`.
