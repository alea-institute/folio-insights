# Railway Dev Server — Diagnose & Restore Plan

_Created 2026-05-22. Goal: get a working Railway dev/testing deployment of the
current v2.0 `master`, with auto-deploy on push, reusing the existing service/URL._

## Current state (verified 2026-05-22)

- A Railway dev deploy shipped in **v1.1** (`deploy-on-railway-as-dev-server`,
  3/3 plans) at **https://folio-insights-production.up.railway.app**. It served
  200s at v1.1 ship time.
- That URL now returns **HTTP 502** on `/health` and `/` (edge responds, no
  healthy container behind it → crashed / suspended / failed redeploy).
- v1.1 deployed a **single-service** app (one `Dockerfile`). v2.0 `master` changed
  `railway.toml` to a **two-service split** (`web`→`Dockerfile.web`,
  `worker`→`Dockerfile.worker`). The formal v2.0 deploy is **Phase 20**; master is
  at **Phase 3**.
- **Leading 502 hypothesis:** GitHub auto-deploy on `master` redeployed using the
  new two-service `railway.toml`, which no longer matches the single service the
  v1.1 deploy created → boot/healthcheck failure.
- Local `railway` CLI (v4.31.0) is **logged out**; no `.railway` link in repo.

## Decisions locked

| Decision | Choice |
|---|---|
| Scope (web-only vs web+worker) | **Diagnose first, then decide** |
| Deploy trigger | **Auto-deploy on push to `master`** |
| Environment | **Reuse existing service/domain** (Phase 20 can promote later) |

---

## Stage 0 — Authenticate & link _(blocks everything; user action)_

```bash
! railway login              # interactive device/browser auth — run in-session
```

Then I run:
```bash
railway link                 # link this repo to the existing folio-insights project
railway status               # confirm project / environment / linked service
railway environment          # confirm which env the domain lives in
railway service              # confirm service name(s)
```

**Exit:** CLI authenticated, repo linked to the existing project, service +
environment names known.

## Stage 1 — Diagnose the 502 _(I do this)_

```bash
railway logs --deployment    # latest deploy/build + runtime logs for the 502
railway variables            # what env vars the service expects (vs .env.docker.example)
```

Determine:
1. How many services exist in the env, and their names (does `railway.toml`'s
   `web`/`worker` match, or is there a single legacy service?).
2. Is GitHub source auto-deploy already connected, and to which branch/Dockerfile?
3. Root cause of the 502: config mismatch (two-service toml vs single service),
   crash on boot, missing env var, OOM/image-size, or suspended/usage-capped.
4. Required runtime env vars for the `web` tier (cross-check `.env.docker.example`,
   `.env.example`) — e.g. LLM keys, DB path. Corpora are bundled into the image,
   so no external data store is needed for dev.

**Decision gate — scope:** based on findings, pick:
- **Web-only** (likely): point the dev service at `Dockerfile.web` (or a single
  dev Dockerfile); skip the idle-stub worker to save cost/build time at Phase 3.
- **Web + worker**: only if the existing project already has both services wired
  and it's cheaper to keep them than to prune.

## Stage 2 — Make config match the chosen dev scope

- If **web-only**: ensure the linked service builds `Dockerfile.web` with
  healthcheck `/health` (already in `railway.toml`). Confirm the `worker` service
  isn't blocking the env (delete/pause it in dev, or leave `railway.toml` as-is and
  simply don't create the worker service in the dev environment).
- Set any missing runtime variables found in Stage 1 via `railway variables --set`
  (secrets stay in Railway, never committed).
- Commit any `railway.toml` / Dockerfile adjustments needed for a clean dev boot.

## Stage 3 — Deploy + wire auto-deploy on `master`

- Connect the service to GitHub source on branch `master` (Railway dashboard:
  Service → Settings → Source → `master`) so every push auto-redeploys.
- Trigger the first clean deploy: `railway up` (or push a commit to fire the hook).
- Watch `railway logs` until the container is healthy.

## Stage 4 — Verify (smoke test)

```bash
URL="https://folio-insights-production.up.railway.app"
curl -sf "$URL/health"                 # expect {"status":"ok"}
curl -sI "$URL/" | head -1             # expect HTTP/2 200
curl -sf "$URL/api/v1/corpora"         # expect JSON list of bundled corpora
```
Plus a Chrome DevTools MCP screenshot of the live viewer to confirm SSR renders.

## Stage 5 — Update docs

- `README.md` "Deploying to Railway" still describes the **old single-Dockerfile**
  flow — update it to reflect the dev-server reality (web-only or two-service,
  auto-deploy on master).
- Add a one-line dev-server note to `.continue-here.md` / `STATE.md` so the next
  session knows the dev URL is live and how it redeploys.

---

## Risks / open items

- **Image size ~8.7 GB** (torch+CUDA via `sentence-transformers`) → slow builds,
  possible Railway build/storage limits. Mitigation noted in README: pin CPU-only
  torch. Decide in Stage 1 if builds are timing out.
- **Account/plan limits:** a 502 can also mean a suspended service (trial expired /
  usage cap). Surfaces immediately in Stage 0–1.
- **"production" naming:** the dev URL is literally `...-production`. We reuse it
  per the locked decision; Phase 20 renames/promotes for the real GA cut.
- **Secrets:** never commit `RAILWAY_TOKEN` or LLM keys; set them as masked Railway
  variables (matches existing `ci/railway.py` T-00-19 handling).

## Immediate next action

Run **`! railway login`** in this session, then tell me to continue — I'll link,
diagnose the 502, and report findings before changing any config.
