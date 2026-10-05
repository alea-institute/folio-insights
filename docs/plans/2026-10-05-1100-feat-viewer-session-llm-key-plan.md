---
title: "feat: per-session LLM key field in the viewer (memory only)"
type: feat
status: completed
date: 2026-10-05
origin: cockpit ask folio-insights-2026-10-05-1018-p10-p11-product-calls (q2-viewer-key-entry)
---

# feat: per-session LLM key field in the viewer (memory only)

## Decision

- **q2-viewer-key-entry:** "Per-session key field, memory only" (Chief auto-answer, 2026-10-05;
  Damien may overrule). The key goes in a masked field. The browser holds it in JS memory for the
  tab only: no `localStorage`, `sessionStorage`, IndexedDB or cookies. It travels as
  `X-LLM-API-Key` on the submit, re-key and resume calls. The server already never stores it.
- **q1-shacl-warnings:** "Keep all as Warnings for now". No code change. The revisit point (tighten
  each warning when the Phase 10 minter lands) already rides with the minter's constraints.

## Problem

Phase 10 (PR #26) made LLM keys bring-your-own: a job submitted without `X-LLM-API-Key` waits as
`needs_credentials`. The viewer's Process and Discover buttons send no key. A job started from
the UI therefore always stalls, and the viewer shows that pause as a plain failure.

## Scope

1. **Session key holder.** `viewer/src/lib/stores/llmKey.ts`: a module-level in-memory value
   (a Svelte `writable<string>`) with `setLlmKey`, `clearLlmKey` and `llmKeyHeaders()`. It is never
   persisted. A page reload or tab close clears it.
2. **Key field.** `viewer/src/lib/components/LlmKeyField.svelte` on the upload page above the
   Process button: a labelled `type="password"` input with `autocomplete="off"`,
   `spellcheck="false"` and `data-1p-ignore`, a show/hide toggle, a Clear button and help text
   ("Kept in this tab's memory only. Never saved."). Restyling the page is out of scope.
3. **Client calls.** `triggerProcessing` / `triggerDiscovery` send `X-LLM-API-Key` when a key is
   set, and return `control_token`. New `resupplyCredentials(corpusId, kind)` and
   `resumeJob(corpusId, kind, maxSpendUsd?)` call `/job/credentials` and `/job/resume`, or the
   `/discover/job/...` routes, with the key and `X-Job-Control-Token`.
4. **Control token.** Hold the submit response's `control_token` in memory per corpus and kind
   (same module, also never persisted). It is needed to re-key or resume.
5. **Paused states.** The processing and discovery stores map stream-end `needs_credentials` and
   `budget_exhausted` to distinct `'needs_credentials' | 'budget_exhausted'` states, not `'error'`.
   The upload page shows a clear message for each. It offers "Supply key and continue" (calls
   credentials, then reopens the stream) or "Resume" (calls resume with the key, then reopens the
   stream). These actions are disabled when there is no key or no control token, and the page
   says why.
6. **Errors inline.** Failed submit, re-key and resume calls show the server's message inline
   (await before changing state).

## Out of scope

- A "remember key" option (rejected alternative; can be added later if users ask).
- Provider and model pickers, and a spend-cap input beyond the resume call's optional parameter.
- Backend changes. The API contract already exists.

## Acceptance

- **A1.** No call in `viewer/src` writes the key to `localStorage`, `sessionStorage`, IndexedDB,
  cookies or the URL. A grep proves it.
- **A2.** Process and Discover send `X-LLM-API-Key` only when a key is set, verified in a real
  browser against the API (network request header present; job does not stall as
  `needs_credentials`).
- **A3.** Without a key, a started job shows the needs-key message, not a failure. Entering a key
  and pressing "Supply key and continue" moves it past `needs_credentials`.
- **A4.** After a reload, the key field is empty.
- **A5.** `npm run check` and `npm run build` pass. The Python test suite is unchanged and green.

## Verification

Run the API and viewer locally, drive the upload page with chrome-devtools, inspect the request
headers and storage, and take a screenshot.

## Outcome (2026-10-05)

- **Built as scoped.** Session key holder, key field, client calls, in-memory control tokens,
  paused-state controls and inline errors are all on the upload page.
- **Browser found two defects, now fixed.**
  - The re-key and resume responses are full job records with `"error": null`. The client's
    `'error' in result` check read every success as a failure. `controlJob` now returns only
    `{status}`.
  - The paused panel did not say why it paused. It now shows the server's reason, for example
    "google rejected the API key (HTTP 400)".
- **Evidence.** In a real browser against a local API with synthetic data, the submit carried
  `X-LLM-API-Key`, the re-key carried the key plus `X-Job-Control-Token`, and the stream reopened.
  The job ran ingestion to distillation and paused again on the provider's rejection of the
  synthetic key. After a reload the field was empty. localStorage and cookies were empty, and
  sessionStorage held only SvelteKit's scroll and snapshot entries, with no key.

## Follow-up (not in this scope)

- **Cancel a paused job after a reload.** The control token is memory-only (per the decision), so a
  reload loses it. A paused job then blocks a forced re-run ("force cannot apply while job ... is
  needs_credentials; cancel it first"), and the UI has no cancel control. Options: a cancel button
  while the token is held, or a server-side expiry for abandoned paused jobs. This needs a
  product call, so it goes on the Next list.
