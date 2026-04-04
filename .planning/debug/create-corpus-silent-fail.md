---
status: awaiting_human_verify
trigger: "Create Corpus button in the UI dialog does nothing. User enters a name, clicks Create Corpus, dialog closes but no corpus appears in the sidebar."
created: 2026-03-22T00:00:00Z
updated: 2026-03-23T00:15:00Z
---

## Current Focus

hypothesis: CONFIRMED - handleCreate did not await createCorpus and closed dialog unconditionally, silencing all errors
test: automated browser test via CDP + full test suite
expecting: corpus creation works and errors are visible
next_action: await human verification of the fix

## Symptoms

expected: Clicking "Create Corpus" with a name should create a corpus directory, save metadata, and show it in the sidebar
actual: Dialog closes silently, no corpus appears, sidebar still shows "No corpora yet", main area still shows "No corpus selected"
errors: No visible errors — silent failure
reproduction: Open the app, click "+ New Corpus" in sidebar, enter a name like "Testing", click "Create Corpus"
started: Unknown — may have never worked or recently broken

## Eliminated

- hypothesis: Backend API endpoint is broken or returns errors
  evidence: Direct curl testing shows POST /api/v1/corpora returns 201 with correct JSON. GET /api/v1/corpora returns the created corpus. CORS preflight returns correct headers.
  timestamp: 2026-03-23T00:02:00Z

- hypothesis: CORS configuration blocks cross-origin requests from Vite dev server
  evidence: OPTIONS preflight request with Origin: http://localhost:5173 returns 200 with correct Access-Control-Allow-Origin header. POST with same origin also succeeds.
  timestamp: 2026-03-23T00:02:30Z

- hypothesis: Frontend code has TypeScript/compilation errors preventing execution
  evidence: svelte-check reports 0 errors, 16 warnings (all a11y-related). Code compiles cleanly.
  timestamp: 2026-03-23T00:04:00Z

- hypothesis: ConfirmDialog fails to pass input value to onconfirm callback
  evidence: Automated browser test via CDP confirmed full flow: ConfirmDialog handleConfirm correctly calls onconfirm("TestFromScript"), handleCreate receives value, createCorpus is called, API succeeds, store updates, sidebar shows corpus.
  timestamp: 2026-03-23T00:05:00Z

- hypothesis: Svelte 5 reactivity issue prevents store updates from rendering in sidebar
  evidence: Automated browser test confirmed corpora store update triggers sidebar re-render: corpusItems went from 0 to 1, selectedItem showed "TestFromScript".
  timestamp: 2026-03-23T00:05:00Z

## Evidence

- timestamp: 2026-03-23T00:01:00Z
  checked: Backend API endpoints via curl
  found: POST /api/v1/corpora creates corpus correctly (201). GET /api/v1/corpora lists it. DELETE works. CORS headers correct.
  implication: Backend is fully functional. Problem is not server-side.

- timestamp: 2026-03-23T00:03:00Z
  checked: Port availability and server status
  found: Vite dev server on port 5173, FastAPI on port 8700. Both running and responding.
  implication: Both servers are up. API_BASE in dev mode correctly points to port 8700.

- timestamp: 2026-03-23T00:04:00Z
  checked: Full code flow: ConfirmDialog -> CorpusSidebar.handleCreate -> corpus store createCorpus -> API client createCorpusApi
  found: handleCreate does NOT await createCorpus(). It sets showCreateDialog = false UNCONDITIONALLY, closing the dialog immediately regardless of async result. createCorpus silently returns null on error.
  implication: Any error in the async chain is completely invisible to the user. The dialog closes, giving the impression the action completed, but nothing happens.

- timestamp: 2026-03-23T00:05:00Z
  checked: Automated browser test via Chrome DevTools Protocol
  found: When API is healthy, the entire flow works correctly. Corpus appears in sidebar, gets selected, upload zone shows.
  implication: The code path is correct when there are no errors. The bug manifests when the API call fails for any reason (server not running, network issue, port conflict, etc.).

- timestamp: 2026-03-23T00:06:00Z
  checked: Error handling in createCorpus store function and handleCreate
  found: createCorpus catches API errors via createCorpusApi (which catches all fetch errors) and returns null. handleCreate doesn't check the return value. No error state is surfaced to the UI.
  implication: This is a fire-and-forget pattern. The root cause is insufficient error handling that silences all failure modes.

- timestamp: 2026-03-23T00:12:00Z
  checked: svelte-check after fix (0 errors, 16 warnings same as before)
  found: Fix compiles cleanly with no new issues
  implication: Fix is type-safe

- timestamp: 2026-03-23T00:13:00Z
  checked: Full test suite (179 passed, 15 skipped)
  found: All tests pass with no regressions
  implication: Backend behavior unchanged, fix is safe

- timestamp: 2026-03-23T00:14:00Z
  checked: Automated browser test of fixed code
  found: Corpus creation works correctly: "TestFixed" appears in sidebar, gets selected, header dropdown updates
  implication: Fix is functionally correct

## Resolution

root_cause: CorpusSidebar.handleCreate does not await the async createCorpus() call and closes the dialog unconditionally. The createCorpus store function silently returns null on API errors without surfacing any feedback. When the API call fails for any reason (server unreachable, network error, conflict, etc.), the user sees the dialog close but no corpus appears — a completely silent failure with no error indication.
fix: (1) Made handleCreate async and await createCorpus result. (2) Dialog only closes on success; stays open with error message on failure. (3) Added corpusError store for error state. (4) Added loading state with "Creating..." button text and disabled inputs during API call. (5) Added errorMessage and loading props to ConfirmDialog for reusable async dialog pattern.
verification: svelte-check 0 errors, full test suite 179/179 passed, automated browser test confirms corpus creation works end-to-end
files_changed:
  - viewer/src/lib/stores/corpus.ts
  - viewer/src/lib/components/CorpusSidebar.svelte
  - viewer/src/lib/components/ConfirmDialog.svelte
