---
phase: 01
slug: polysemy-distinguo-spike
status: verified
threats_open: 0
threats_closed: 35
threats_accepted: 11
asvs_level: 1
created: 2026-04-24
scope: Single-maintainer CLI research spike; no network ingress; no multi-tenancy
---

# Phase 01 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> SECURED — all 35 threats have a documented disposition (24 mitigated, 11 accepted).

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| `$HOME/.folio-insights/` ↔ repo | Reviewer ed25519 private key (JWK) lives outside repo tree | Private key material (0600); DID string (public) |
| CLI stdin ↔ `dispositions.jsonl` | Human keystroke gate recording disposition records | Reviewer decision + rationale (text); pseudonymous DID |
| Disposition append path | POSIX O_APPEND atomic write (≤4KB records) | JSONL schema-v1 records |
| PyoxigraphStore query surface | SEC-01 wrapper around `pyoxigraph.Store.query_rdf12` | SPARQL ASK queries with constant strings + Literal-enum framework tokens |
| LLM audit egress (optional) | `instructor` → Anthropic/OpenAI/Gemini/Ollama for Rule-4 + audit disagreements | Public-domain axioms + framework labels (no PII, no credentials) |
| TTL fixture ingest (`bulk_load`) | Maintainer-curated Turtle corpus; parsed by pyoxigraph | Fixture axiom strings, escaped via `_escape_turtle_literal` |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation / Control | Status |
|-----------|----------|-----------|-------------|----------------------|--------|
| T-01-01 | Information disclosure | `.gitignore` / reviewer key | mitigate | `.gitignore:43` excludes `.folio-insights/` | closed |
| T-01-02 | Tampering (deps) | `cryptography`, `base58` | accept | PCA-maintained, pinned in lockfile | closed |
| T-01-03 | Information disclosure (JWK) | `reviewer.py` | mitigate | `reviewer.py:64` dir 0o700; `:75` KEY_PATH 0o600; `:77` DID_PATH 0o600 | closed |
| T-01-04 | Tampering (JSONL append) | `dispositions.py` | mitigate | `dispositions.py:52` — `path.open("a")` O_APPEND atomicity | closed |
| T-01-05 | Repudiation (unsigned dispositions) | `dispositions.py` | accept | `signature: None` reserved (`dispositions.py:46`); Phase 6 backfill | closed |
| T-01-06 | Spoofing (local did:key) | `reviewer.py` | accept | Single-maintainer spike; Phase 19 trust model audit | closed |
| T-01-06a | Tampering (float confidence) | `dispositions.py` | mitigate | `dispositions.py:43` `detector_verdict: dict`; `detector_confidence` absent (grep exit 1) | closed |
| T-01-07 | Tampering (SPARQL injection) | `similarity_query.py` | mitigate | `similarity_query.py:28-33` — constant strings; framework from Literal enum; term from hand-curated fixtures | closed |
| T-01-08 | Information disclosure (LLM prompt) | `detector.py` | accept | Public-domain legal axioms, no PII | closed |
| T-01-09 | DoS (LLM calls) | `detector.py` | mitigate | `detector.py:175` `except Exception` → `decision="uncertain"`; LLM only for Rule 4 HOMONYMS | closed |
| T-01-10 | Spoofing (raw store query) | `similarity_query.py` | mitigate | `similarity_query.py:80` — `store.query_rdf12()` exclusively; raw `.store.query()` never called | closed |
| T-01-04-01 | Tampering (invalid fork) | `distinguo.py` | mitigate | `distinguo.py:160` — `validate_fork_proposal_shape(fork)` preflight inside `emit_fork_ttl` | closed |
| T-01-04-02 | Tampering (Turtle injection) | `distinguo.py` | mitigate | `distinguo.py:130-146` — `_escape_turtle_literal` escapes `\`, `"`, `\n`, `\r` | closed |
| T-01-04-03 | Information disclosure (DID in fork IRI) | `distinguo.py` | accept | Intentional provenance; pseudonymous ed25519 | closed |
| T-01-04-04 | DoS (large proportional_relation) | `distinguo.py` | accept | Terminal-buffer-bounded; single-maintainer | closed |
| T-01-04-05 | Elevation of privilege (SERVICE via fork graph) | `distinguo.py` | mitigate | All writes routed through `PyoxigraphStore`; `bulk_load` is data-ingest, not query surface | closed |
| T-01-04-06 | Repudiation (fork provenance) | `distinguo.py` | mitigate | `distinguo.py:190-191` — `fi:proposedBy` + `fi:proposedAt` on every emitted fork | closed |
| T-01-04-07 | Spoofing (DID forgery) | `distinguo.py` | accept | Phase 15 JCS-canonical signatures | closed |
| T-01-05-01 | Tampering (auto-apply flag) | `cli.py` | mitigate | No `--auto`/`--yes`/`--batch`/`--accept-all`/`--no-prompt`/`--force` params on review command; `tests/polysemy/test_cli_review.py:107` `test_no_auto_apply_path` | closed |
| T-01-05-02 | Tampering (silent default-accept) | `cli.py` | mitigate | `cli.py:191-195` — `Prompt.ask(choices=[...])` with no `default=` argument | closed |
| T-01-05-03 | Information disclosure (DID in JSONL) | `dispositions.py` | accept | D-3 schema intentional provenance; pseudonymous | closed |
| T-01-05-04 | Tampering (path traversal via `--dispositions-path`) | `cli.py` | accept | Single-maintainer spike; Phase 15 root-confinement check | closed |
| T-01-05-05 | DoS (oversized rationale) | `cli.py` | accept | Terminal-buffer-bounded (rich.prompt reads one line) | closed |
| T-01-05-06 | Repudiation (disposition records) | `dispositions.py` | mitigate | `dispositions.py:41-43` — `reviewer_did`, `reviewed_at_iso`, `detector_verdict` all required fields | closed |
| T-01-05-07 | Elevation of privilege (SERVICE via bulk_load) | `distinguo.py` | mitigate | SERVICE preflight covers `query_rdf12` only; `bulk_load` is maintainer-curated data-ingest, no query execution during TTL parse | closed |
| T-01-05-08 | Tampering (ForkProposal bypass) | `cli.py` | mitigate | `cli.py:221` — pydantic constructor fires; `cli.py:235` — `validate_fork_proposal_shape(fork)` defense-in-depth | closed |
| T-01-06-01 | Tampering (point-estimate FP reporting) | `fp_audit.py` | mitigate | `fp_audit.py:74,83-84` — `ci_lower`/`ci_upper` always returned | closed |
| T-01-06-02 | Information disclosure (rationale → LLM) | `fp_audit.py` | accept | Caselaw-derived, not PII; Phase 9 data-egress review | closed |
| T-01-06-03 | DoS (LLM audit hang) | `fp_audit.py` | mitigate | `fp_audit.py:146-149` — try/except + `logger.warning` per `_invoke_audit` call | closed |
| T-01-06-04 | Tampering (Markdown injection) | `fp_audit.py` | mitigate | `fp_audit.py:243` — `.replace("\|", "\\\|")` + `[:80]` truncation | closed |
| T-01-06-05 | Repudiation (LLM flip-flop) | `fp_audit.py` / `detector.py` | mitigate | `fp_audit.py:198` `response_model=PolysemyVerdict`; `:166` verbatim `llm_reason` recording | closed |
| T-01-06-06 | Elevation of privilege (scipy dep bloat) | `fp_audit.py` | mitigate | No `import scipy` in module (grep exit 1); `tests/polysemy/test_fp_rate.py:104` `test_wilson_score_interval_no_scipy_import` | closed |
| T-01-06-07 | Tampering (kappa misread as gate) | `fp_audit.py` | mitigate | `fp_audit.py:33-37` `KAPPA_CAVEAT` defined; `:86` returned in `compute_fp_rate` dict | closed |
| T-01-06-08 | Tampering (detector_confidence regression) | `fp_audit.py` | mitigate | `detector_confidence` absent from module (grep exit 1); `tests/polysemy/test_fp_rate.py:333` `test_no_detector_confidence_float_regression` | closed |
| T-01-06-09 | Tampering (--llm-model regression) | `cli.py` | mitigate | `"--llm-model"` absent from module (grep exit 1); `tests/polysemy/test_fp_rate.py:363` + `tests/polysemy/test_cli_review.py:118` | closed |
| T-01-06-10 | Tampering (stale `.reason` attribute) | `fp_audit.py` | mitigate | `.reason\b` absent (grep exit 1); `tests/polysemy/test_fp_rate.py:345` `test_no_stale_reason_attribute_regression` | closed |

*Status: open · closed*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Deferred To | Accepted By | Date |
|---------|------------|-----------|-------------|-------------|------|
| AR-01 | T-01-02 | `cryptography`/`base58` are PCA-maintained; pinned in `requirements.dev.lock` | Ongoing | Phase 01 maintainer | 2026-04-24 |
| AR-02 | T-01-05 | Unsigned dispositions; `signature: None` field reserved at schema v1 | Phase 6 — cryptographic signature backfill | Phase 01 maintainer | 2026-04-24 |
| AR-03 | T-01-06 | Local `did:key` unverified by server; single-maintainer trust scope | Phase 19 — trust model audit | Phase 01 maintainer | 2026-04-24 |
| AR-04 | T-01-08 | LLM prompt content is public-domain legal axioms; no PII/credentials | Informational — no deferred work | Phase 01 maintainer | 2026-04-24 |
| AR-05 | T-01-04-03 | DID IRI in fork proposals is intentional provenance (pseudonymous ed25519 pubkey) | No deferred work — design intent | Phase 01 maintainer | 2026-04-24 |
| AR-06 | T-01-04-04 | Large `proportional_relation` strings bounded by rich.prompt one-line read | No deferred work — environmental bound | Phase 01 maintainer | 2026-04-24 |
| AR-07 | T-01-04-07 | DID forgery under another's key out of Phase 1 scope | Phase 15 — JCS-canonical signatures | Phase 01 maintainer | 2026-04-24 |
| AR-08 | T-01-05-03 | Reviewer DID in `dispositions.jsonl` is D-3 schema intentional provenance | No deferred work — design intent | Phase 01 maintainer | 2026-04-24 |
| AR-09 | T-01-05-04 | `--dispositions-path` not root-confined; single-maintainer scope | Phase 15 — root-confinement check | Phase 01 maintainer | 2026-04-24 |
| AR-10 | T-01-05-05 | Oversized rationale input bounded by terminal buffer | No deferred work — environmental bound | Phase 01 maintainer | 2026-04-24 |
| AR-11 | T-01-06-02 | Rationale text to external LLM is caselaw-derived, not PII | Phase 9 — data-egress review | Phase 01 maintainer | 2026-04-24 |

*Accepted risks do not resurface in future audit runs.*

---

## Unregistered Threat Flags from SUMMARY.md

`01-SUMMARY.md` has no `## Threat Flags` section. §5 "Pitfalls Encountered" table entries all map to registered threats (primarily the T-01-06-0{6,7,8,9,10} regression-guard cluster).

One informational note from §6 deltas: `PyoxigraphStore.query_rdf12` required an ASK-query branch fix (commit `ee0cfeb`). This is an in-scope correction inside the T-01-10 mitigation boundary, not a new attack surface.

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-04-24 | 35 | 35 (24 mitigated + 11 accepted) | 0 | gsd-security-auditor (sonnet) via /gsd-secure-phase 01 |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log (AR-01 through AR-11)
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter
