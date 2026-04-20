# Phase 1: Deploy on Railway as Dev Server - Context

**Gathered:** 2026-04-12
**Status:** Ready for planning
**Source:** Direct user directive + sibling project pattern discovery

<domain>
## Phase Boundary

Ship the FOLIO Insights app as a single Railway service (dev environment), mirroring the
deployment pattern already used for sibling projects `folio-enrich` and `folio-mapper`.
Scope is a working dev URL that loads data end-to-end. Not prod-hardened (no custom domain,
no auth, no horizontal scaling, no staging/prod separation).

**In scope:**
- Single-service Railway deployment (FastAPI + built SvelteKit bundled in one container)
- Multi-stage Dockerfile (Node build → Python runtime)
- `$PORT` binding, health check, non-root user
- CORS/static-serving configuration so viewer talks to API without cross-origin issues
- Seeded/bundled `output/` data (or volume if required) so viewer has something to render
- Redeploy-from-git workflow (Railway watches master)

**Out of scope:**
- Production hardening (auth, custom domain, backups, CDN)
- DB migration to Postgres (keep SQLite for dev)
- CI/CD beyond Railway's built-in git trigger
- Separate staging/prod environments

</domain>

<decisions>
## Implementation Decisions

### Deployment shape
- **Single Railway service, single Dockerfile.** Mirror `folio-enrich` and `folio-mapper`.
  FastAPI serves the built SvelteKit bundle via StaticFiles. No separate viewer service.
- **Multi-stage Dockerfile.** Stage 1: Node 20 + pnpm/npm builds SvelteKit to static. Stage 2:
  Python 3.11/3.13 slim, installs backend deps, copies built frontend into image.
- **`uv` for Python deps in the image** (matches `folio-mapper`; faster, deterministic).
- **Port:** Bind to `$PORT` with `8000` fallback. Same pattern as siblings.
- **Non-root user** with a writable home dir for any runtime state (jobs, temp files).
- **HEALTHCHECK:** `python -c "import urllib.request; urllib.request.urlopen(...)"` against
  `/health` or `/api/health`. Add endpoint if missing.

### SvelteKit build
- Use `@sveltejs/adapter-static` (already chosen in Phase 01-04 per STATE.md). Static output
  copied into image and served by FastAPI at `/` plus `/static/*` (or equivalent).
- Build command: whatever the viewer's existing `package.json` defines (`npm run build` or
  `pnpm build`). Planner must inspect `viewer/package.json` to choose.
- `VITE_API_BASE` or equivalent must be empty/relative so frontend calls hit same origin —
  avoids CORS and localhost hardcoding (honors auto-memory rule
  `feedback_api-client-proxy.md`).

### Data strategy
- **Bundle `output/` data into the image** as the simplest dev path — deterministic, no
  volume setup, redeploy replaces data. Acceptable for dev server only.
- If `output/` is too large (>500MB), fall back to Railway volume mounted at
  `/app/output`. Planner must measure `output/` size and choose.
- Do NOT commit regenerated data to the image during build.

### Env vars
- `PORT` — injected by Railway
- `PYTHONUNBUFFERED=1` — standard
- Any API keys (LLM providers) set via Railway dashboard, not in repo
- No custom domain; use the generated `*.up.railway.app` URL

### CORS
- Single origin (FastAPI serves frontend), so CORS is a non-issue in the deployed environment.
- Local dev continues to use Vite proxy (already enforced by auto-memory).

### Redeploy
- Connect Railway service to the git repo, watch `master` branch. Push → auto-deploy.
- Document the manual "Deploy" button fallback in README.

### Claude's Discretion
- Exact Dockerfile layer ordering for cache efficiency
- Whether to use `adapter-static` or `adapter-node` (default: static — matches prior decision)
- Package manager choice for the viewer build (`npm` vs `pnpm`) — inspect existing lockfile
- Whether to add a `railway.json`/`railway.toml` or rely purely on Dockerfile defaults
  (preference: Dockerfile only, matching siblings; add `railway.toml` only if needed for
  healthcheck path or watch paths)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Sibling deployments (pattern source)
- `../folio-enrich/Dockerfile` — Single-service pattern: FastAPI + static frontend, non-root user, `$PORT` binding, health check
- `../folio-mapper/Dockerfile` — Multi-stage with pnpm frontend build + `uv` Python install; most relevant template since folio-mapper also has a SPA frontend

### This project
- `README.md` — Current run instructions (API on 9925, viewer on 9926 via `.claude/bootup.json`)
- `.claude/bootup.json` — Dev server definitions (mirror commands in production entrypoint)
- `api/main.py` — FastAPI entry (has `serve(port=...)` helper)
- `viewer/package.json` + `viewer/svelte.config.js` — Frontend build config
- `pyproject.toml` — Python deps + integration test markers

### Project decisions (from STATE.md)
- Phase 01-04 chose `adapter-static` for SPA mode served by FastAPI StaticFiles
- FastAPI uses `aiosqlite` (async SQLite) — SQLite file lives under data dir

</canonical_refs>

<specifics>
## Specific Ideas

- Bundle `output/` into image during Dockerfile build (`COPY output/ /app/output/`)
- Add `/health` endpoint to FastAPI if not present
- Set `FOLIO_INSIGHTS_OUTPUT_DIR` (or equivalent) env var to `/app/output`
- Mirror non-root-user block from `folio-enrich/Dockerfile` lines 24-29
- Mirror `CMD ["sh", "-c", "uvicorn ... --port ${PORT:-8000}"]` pattern

</specifics>

<deferred>
## Deferred Ideas

- Custom domain + HTTPS termination (prod milestone)
- Separate staging environment
- Auth / access control (dev server is assumed trusted)
- Postgres migration from SQLite
- CI checks (lint/test) before Railway deploy
- Observability (logs aggregation, error tracking)

</deferred>

---

*Phase: 01-deploy-on-railway-as-dev-server*
*Context gathered: 2026-04-12 via direct directive ("like folio-enrich and folio-mapper")*
