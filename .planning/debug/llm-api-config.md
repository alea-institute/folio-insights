---
status: awaiting_human_verify
trigger: "LLM-dependent pipeline stages (distiller, classifier, folio_tagger) fail silently during corpus processing"
created: 2026-03-22T00:00:00Z
updated: 2026-03-22T00:00:00Z
---

## Current Focus

hypothesis: CONFIRMED AND FIXED - Changed default LLM provider from anthropic to google (gemini-2.5-flash)
test: Verified all three LLM tasks (distiller, classifier, concept) return correct structured output
expecting: User re-processes a corpus and sees non-empty folio_tags, non-zero confidence, successful lineage
next_action: Await user verification that pipeline processing produces enriched units

## Symptoms

expected: The distiller, classifier, and folio_tagger pipeline stages should use an LLM to enrich extracted knowledge units with distilled text, classifications, and FOLIO taxonomy tags.
actual: All 535 units in test2 corpus have empty folio_tags, confidence 0.0. Lineage shows "distill_failed: LLM call failed". Pipeline reports success despite failures.
errors: No visible errors to user. Lineage metadata shows "LLM call failed" but not surfaced. No crash or exception visible.
reproduction: Process any corpus -- LLM stages always fail.
started: Has never worked -- missing configuration since initial build.

## Eliminated

## Evidence

- timestamp: 2026-03-22T00:01:00Z
  checked: Environment variables for API keys
  found: OPENAI_API_KEY is set (but quota exhausted), GOOGLE_API_KEY is set and working, ANTHROPIC_API_KEY is NOT set
  implication: Default provider "anthropic" has no API key available

- timestamp: 2026-03-22T00:02:00Z
  checked: Python packages in folio-insights venv
  found: openai (v2.29.0) and instructor (v1.14.5) installed; anthropic NOT installed; httpx IS installed
  implication: Even if ANTHROPIC_API_KEY were set, anthropic SDK import would fail. Google provider uses httpx (available).

- timestamp: 2026-03-22T00:03:00Z
  checked: LLMBridge.get_llm_for_task() code path (llm_bridge.py lines 63-73)
  found: Constructs API key env var as f"{provider_name.upper()}_API_KEY", gets empty string, passes None to provider
  implication: AnthropicProvider created with api_key=None, fails on every LLM call

- timestamp: 2026-03-22T00:04:00Z
  checked: extraction.json lineage for test2 corpus (535 units)
  found: 535/535 units have "distill_failed", 535/535 have 0 folio_tags, knowledge_classifier absent from lineage
  implication: Every LLM-dependent stage fails silently; exception is caught and pipeline continues

- timestamp: 2026-03-22T00:05:00Z
  checked: Google provider end-to-end test from folio-insights venv
  found: GoogleProvider imports OK (uses httpx only), GOOGLE_API_KEY is set, test call with gemini-2.5-flash returned correct JSON
  implication: Google provider is a working drop-in replacement

- timestamp: 2026-03-22T00:06:00Z
  checked: After fix - full LLMBridge chain test for distiller, classifier, concept tasks
  found: All three tasks return correct structured JSON with real LLM enrichment
  implication: Fix is working end-to-end for all LLM-dependent pipeline stages

- timestamp: 2026-03-22T00:07:00Z
  checked: Test suite after fix
  found: 182 passed, 15 skipped (same as before fix)
  implication: No regressions introduced

## Resolution

root_cause: Two compounding issues: (1) The anthropic Python SDK is not installed in the folio-insights virtual environment -- it only exists in folio-enrich's venv, and the sys.path bridge only imports folio-enrich's app.* modules, not its pip packages. (2) The ANTHROPIC_API_KEY environment variable is not set. Both issues cause every LLM call to throw an exception, which is silently caught by each pipeline stage (distiller, classifier, folio_tagger), resulting in empty folio_tags and 0.0 confidence on all units.
fix: Changed default llm_provider from "anthropic" to "google" and llm_model from "claude-sonnet-4-6" to "gemini-2.5-flash" in config.py. The Google provider only needs httpx (already installed as a dependency) and GOOGLE_API_KEY (already set in the environment).
verification: Self-verified: (1) LLMBridge resolves to GoogleProvider correctly, (2) all three LLM task types return valid structured JSON, (3) 182 tests pass with no regressions. Awaiting human verification of full pipeline re-run.
files_changed: [src/folio_insights/config.py]
