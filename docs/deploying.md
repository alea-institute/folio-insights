# Deploying (Coolify on Hetzner)

The dev environment runs at **https://folio-insights.dev.openlegalstandard.org** as a Coolify
application on the Hetzner dev box. Coolify builds [`Dockerfile.web`](../Dockerfile.web) from this
repository: a single web service, a FastAPI backend that also serves the built SvelteKit viewer
(a static SPA) at `/`, on one port, with `/health` as its healthcheck. (Railway hosted it until
2026-07-27; that account is gone and its config was removed from this repo.)

> **Web-only by design.** The `worker` tier (OWL reasoning) is an idle stub and is **not**
> deployed — no worker service, no Redis, no Oxigraph. The full multi-service release cut is a
> gated candidate in `docs/plans/2026-09-27-1930-refactor-v2-gsd-to-ce-migration-plan.md`.

> **No shared LLM key is baked into the server.** LLM-backed features use Bring-Your-Own-Key
> (each user supplies their own key); the dev server intentionally has no `ANTHROPIC_API_KEY`.

## Verify

```bash
URL="https://folio-insights.dev.openlegalstandard.org"
curl -sf "$URL/health"                  # {"status":"ok"}
curl -sf "$URL/api/v1/corpora"          # JSON list of bundled corpora
```

## Notes

- **Data:** the baseline corpora `output/default/` and `output/demo/` are whitelisted in
  `.gitignore` **and** re-included in `.dockerignore`, so `Dockerfile.web`'s `COPY output/`
  bundles them into the image and the viewer renders real data. Other generated output stays
  git-ignored. Never whitelist a corpus built from copyrighted sources. (SQLite
  `*.db-wal`/`*.db-shm` sidecars are excluded for build determinism.)
- **Source viewer:** `/api/v1/source` reads only files inside the configured output directory.
- **SPA viewer:** the viewer is built with `@sveltejs/adapter-static` and served by FastAPI
  (`StaticFiles` with an `index.html` fallback for client-side routes, so deep links / refreshes
  work).

---
