---
phase: 00
slug: foundations-hard-gate
status: verified
threats_open: 0
threats_total: 40
threats_closed: 40
asvs_level: 1
created: 2026-04-23
verified: 2026-04-23
---

# Phase 00 — Security

> Phase 0 foundations hard-gate security contract. 40 STRIDE-classified threats across 8 plans; all dispositions closed by mitigation or accepted risk. No implementation gaps.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| PyPI → uv install | Third-party Python packages enter developer venv | Python wheels + sdists |
| Dockerfile build context → image layer | Local repo → shipped container | source code, `.env`, caches |
| SPARQL query text → pyoxigraph engine | User/dev-supplied SPARQL strings | RDF-12 query AST |
| SPARQL `SERVICE` clause → network | SPARQL federation endpoint | HTTP(S) outbound (169.254/RFC 1918 risk) |
| `RAILWAY_TOKEN` → Dagger subprocess env | CI secret into pipeline | deploy credential |
| SOURCE_DATE_EPOCH → image digest | Build-time timestamp | reproducibility anchor |
| `params.id` → SSR JSON response | URL path → server render | user-controlled IRI |
| DECISION.md → downstream PLAN.md | Policy artifact → phase planning | gate verdicts + branch guidance |

---

## Threat Register

### Plan 00-01 (prep-deps)

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-00-01 | Tampering (supply-chain) | pyoxigraph==0.5.7 wheel | mitigate | Exact version pin; `requirements.lock` with `--hash=sha256` (1907 entries, Plan 05); `--require-hashes` enforced at Docker install | closed |
| T-00-02 | Tampering | owlready2==0.50 wheel | mitigate | Version pin; HermiT.jar verified in 00-04 image build; 42-entry `requirements.worker.lock` | closed |
| T-00-03 | Information Disclosure | `.env` leak into image | mitigate | `.dockerignore` (30+ entries) includes `.env`; explicit `COPY` paths — no `COPY . .` | closed |
| T-00-04 | Information Disclosure | `.planning/` leaked into image | accept | No PII; design docs only. `.dockerignore` excludes. | closed |
| T-00-05 | DoS | Python 3.13 regression | mitigate | `requires-python = ">=3.11,<3.13"` — fails at install, not runtime | closed |

### Plan 00-02 (bench-generator)

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-00-06 | Tampering | Non-deterministic generator | mitigate | `random.Random(seed)` threaded; sorted iteration; `test_same_seed_produces_bit_identical_output` green; cross-process 1M SHA256 verified (`ffb2c130…`) | closed |
| T-00-07 | Tampering | Banned `<<>>` subject terms | mitigate | `test_output_contains_no_sparql_star_subject_terms` green; fixture grep → zero `<<` bytes | closed |
| T-00-08 | DoS | Unbounded `--target` | accept | Caller-discipline; OOM user-induced; not a security threat | closed |
| T-00-09 | Information Disclosure | Real v1 PII in output | accept | Phase 0 is synthetic-structural; no real corpus extraction | closed |
| T-00-10 | DoS | Adversarial-profile deep-graph explosion | mitigate | `adversarial_density=0.10` dataclass-frozen; `PhaseProfile` immutable | closed |

### Plan 00-03 (gate-1 RDF-12) — *threat IDs re-use 06–11 for STRIDE remapping in this plan's scope*

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-00-06′ | Information Disclosure | `SERVICE <169.254.169.254/...>` | mitigate | `ServiceClauseBlocked` regex preflight in `PyoxigraphStore.query_rdf12` — synchronous reject in ms; `adversarial/service_ssrf.sparql` asserts | closed |
| T-00-07′ | DoS | Unbounded CONSTRUCT | mitigate | `@pytest.mark.timeout(30)` on adversarial query; Phase 16 adds `arq:queryTimeout` | closed |
| T-00-08′ | Tampering | rdflib Turtle drops RDF-12 annotations | mitigate | Pitfall-2 guard test; `validate_shard_via_rdflib_bridge` docstring routes to SPARQL ASK | closed |
| T-00-09′ | Spoofing | Gold queries containing `<<` | mitigate | File-discipline check (13 gold + 5 adversarial all grep-clean); pyoxigraph 0.5.7 regression pin | closed |
| T-00-10′ | Repudiation | Silent annotation drop on bridge | accept | Docstring WARNING; Phase 11 adds metrics | closed |
| T-00-11 | Elevation | SPARQL `INSERT DATA` on read-only surface | transfer | Phase 16 wraps public endpoint query-only; out of Phase 0 scope per SEC-01 | closed |

### Plan 00-04 (dockerfiles + adapter-node)

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-00-12 | Tampering | Base image tag drift | mitigate | `@sha256:` manifest-list digests pinned on all 4 bases; captured 2026-04-22 | closed |
| T-00-13 | Information Disclosure | `COPY . .` host-state leak | mitigate | `.dockerignore` 30+ exclusions; explicit `COPY src/` `COPY api/` | closed |
| T-00-14 | Elevation | Root escape from container | mitigate | `USER 1001` numeric on both images; healthcheck runs non-root | closed |
| T-00-15 | DoS | apt/apk cache bloat | mitigate | `--no-install-recommends` + `rm -rf /var/lib/apt/lists/*`; `--no-cache` on alpine | closed |
| T-00-16 | Repudiation | Non-reproducible builds | mitigate | `SOURCE_DATE_EPOCH` ARG+ENV on all stages; Plan 05 asserts bit-identical digest (PASS) | closed |
| T-00-17 | Information Disclosure | adapter-node env leak | accept | `envPrefix: 'FOLIO_'` — only FOLIO_* env reaches client | closed |

### Plan 00-05 (Dagger CI + Gate 5)

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-00-18 | Tampering | PyPI typosquat / dep swap | mitigate | `uv pip compile --generate-hashes` → `--require-hashes` (4085 sha256 entries across 3 lockfiles) | closed |
| T-00-19 | Information Disclosure | `RAILWAY_TOKEN` pipeline log leak | mitigate | Token passed via `env=` only, never argv; `ci/railway.py` does not log token; stderr-only deploy failures | closed |
| T-00-20 | DoS | Runaway Dagger builds | mitigate | `timeout=1200` on `_dagger_build`; `pytest.mark.slow` excludes from quick suite | closed |
| T-00-21 | Elevation | Dagger engine Unix socket | accept | CI runner ephemeral; project-scoped; no multi-tenant exposure | closed |
| T-00-22 | Repudiation | Dagger SDK non-determinism | mitigate | `dagger-io==0.20.6` hash-pinned in `requirements.dev.lock`; version recorded in 00-05-SUMMARY | closed |
| T-00-23 | Spoofing | `ttl.sh` tag poisoning | mitigate | Gate 5 test compares `@sha256:` content digests, not tags | closed |

### Plan 00-06 (Gate 2 P95 harness)

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-00-24 | Tampering | Tuning-to-test | mitigate | Baseline committed at `705f586` before any tuning; TUNING-LOG.md Tuning-to-Test Guard section pins commit | closed |
| T-00-25 | DoS | Runaway cold-cache test | mitigate | Cold-cache parametrized to 3 queries (`GOLD_QUERIES[:3]`); not auto-run | closed |
| T-00-26 | Information Disclosure | `bench-results.json` path leak | accept | Repo-internal paths only; no secrets | closed |
| T-00-27 | Repudiation | Gate 2 machine-dispute | mitigate | pytest-benchmark `machine_info` block (hostname, CPU, Hz) in `bench-results.json`; TUNING-LOG.md header reproduces | closed |

### Plan 00-07 (SSR + Gate 3/4 + HermiT)

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-00-28 | Information Disclosure | Unvalidated `params.id` (XSS vector) | mitigate | SvelteKit `{expr}` auto-escape; Phase 0 stubs return JSON only; Phase 15 adds IRI regex | closed |
| T-00-29 | DoS | hyperfine 450-request burst | accept | Canned-JSON fast path; local loopback | closed |
| T-00-30 | Tampering | Tuning Gate 4 via removing streaming | mitigate | `+page.server.ts` requires 2 unawaited + 1 awaited fetches per D-09; acceptance check | closed |
| T-00-31 | Elevation | HermiT subprocess privilege | mitigate | UID 1001 in worker container (Plan 04); dev env = developer UID | closed |
| T-00-32 | Repudiation | Gate 4 machine-dispute | mitigate | hyperfine `--export-json` captures hostname + system info; MEASUREMENTS.md records | closed |
| T-00-33 | Spoofing | `FOLIO_WORKER_IMAGE` mis-pointed | accept | Dev-machine risk only; CI sets explicitly from Dagger publish | closed |

### Plan 00-08 (DECISION.md synthesis)

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-00-34 | Tampering | DECISION.md pre-DID authenticity | accept | Git-sha authenticity (commit 3f9e7a3); backfill via Phase 6 DID signing per §Signature Deferral | closed |
| T-00-35 | Repudiation | DECISION.md authorship dispute | mitigate | Git author on DECISION.md commit = signatory until Phase 6; no squash-merge | closed |
| T-00-36 | Information Disclosure | Perf numbers aid SPARQL injection | accept | Open-source project; numbers already public; Phase 16 must not rely on obscurity | closed |
| T-00-37 | Information Disclosure | Branch-guidance leaks architecture | accept | ROADMAP.md already lists dependencies; no new disclosure | closed |
| T-00-38 | DoS | fuseki queryTimeout too high | mitigate | `arq:queryTimeout=30000ms` (30s) in fuseki/config.ttl per RESEARCH.md | closed |
| T-00-39 | Elevation | Substitute-then-sign on DID backfill | mitigate | §Signature Deferral point 4: SUPERSEDED-BY pattern; Phase 6 MUST verify body matches git-sha before signing | closed |
| T-00-40 | Tampering (pivot scaffold) | fuseki/config.ttl weakened post-Phase-0 | mitigate | Phase 16 config-as-code diff review; noted in BRANCH-GUIDANCE.md Phase 16 row | closed |

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-00-01 | T-00-04 | `.planning/` is design docs only — no PII; `.dockerignore` excludes | Damien Riehl | 2026-04-22 |
| AR-00-02 | T-00-08 | Caller-discipline bounded; OOM is user-induced, not a security surface | Damien Riehl | 2026-04-22 |
| AR-00-03 | T-00-09 | Phase 0 generator is synthetic-structural; real corpora + redaction arrive in Phase 10 + 13.5 | Damien Riehl | 2026-04-22 |
| AR-00-04 | T-00-17 | `envPrefix: 'FOLIO_'` is standard SvelteKit boundary control | Damien Riehl | 2026-04-22 |
| AR-00-05 | T-00-10′ | Plan 11 observability adds dropped-triple metrics; Phase 0 does not need them | Damien Riehl | 2026-04-22 |
| AR-00-06 | T-00-21 | Dagger engine CI-runner-ephemeral; no multi-tenant exposure | Damien Riehl | 2026-04-23 |
| AR-00-07 | T-00-26 | `bench-results.json` contains repo-internal paths only | Damien Riehl | 2026-04-23 |
| AR-00-08 | T-00-29 | Loopback-only 450-req burst against canned JSON — not a realistic DoS | Damien Riehl | 2026-04-23 |
| AR-00-09 | T-00-33 | `FOLIO_WORKER_IMAGE` is dev-machine surface; CI pins explicitly | Damien Riehl | 2026-04-23 |
| AR-00-10 | T-00-34 | Git-sha authenticity accepted until Phase 6 DID substrate ships (D-17 chicken-and-egg) | Damien Riehl | 2026-04-23 |
| AR-00-11 | T-00-36 | Open-source project; perf numbers already public | Damien Riehl | 2026-04-23 |
| AR-00-12 | T-00-37 | ROADMAP.md already public; no new disclosure | Damien Riehl | 2026-04-23 |

---

## Cross-Cutting Requirements Addressed

| Req ID | Description | Coverage |
|--------|-------------|----------|
| SEC-01 | SPARQL federation / SSRF hardening | `ServiceClauseBlocked` preflight in `PyoxigraphStore.query_rdf12`; 5 adversarial tests; Phase 16 replaces regex with parser-based allowlist |
| SEC-02 | Supply-chain hardening | Exact version pins + `requirements{,.worker,.dev}.lock` (4085 hash entries); `--require-hashes` enforced in both Dockerfiles |
| QUALITY-01 | Gate 2 P95 SPARQL latency | Worst-case 118.78 ms vs 500 ms target (>4× headroom) |
| QUALITY-03 | Two-tier worker split + reproducibility | 156 MB worker image; bit-identical Gate 5 digest; `SOURCE_DATE_EPOCH` plumbed |
| QUALITY-04 | SSR prototype for Gate 4 | 3 surfaces via adapter-node; hooks.server.ts cache-control |
| OBS-04 | Dagger CI + digest determinism | Gate 5 Mode 1 PASS — web `b36de1fe…6edd`, worker `b2abdffc…b309f` |
| STORAGE-04 | pyoxigraph 0.5.7 as canonical RDF-12 surface | `PyoxigraphStore` wrapper with bulk_load + optimize + query_rdf12 + rdflib bridge |

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-04-23 | 40 | 40 | 0 | claude-code (gsd-secure-phase, programmatic) |

### Audit Notes (2026-04-23)

- State B entry (no prior SECURITY.md). Register built from 8 `<threat_model>` blocks in PLAN.md files + `## Threat Flags` sections in all 8 SUMMARY.md files.
- Plan 00-03 re-used threat IDs T-00-06 through T-00-10 for STRIDE-remapped scope; disambiguated with `′` suffix in this register.
- No implementation scan performed for this audit — this is a paper verification against documented mitigations in SUMMARY files (each marked FOUND / VERIFIED in self-checks). Runtime verification was performed separately in 00-UAT.md (10/10 tests pass, commit 7bf4196).
- No threats escalated; no gaps found.

---

## Sign-Off

- [x] All 40 threats have a disposition (mitigate / accept / transfer)
- [x] 12 accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-04-23

---

*Phase: 00-foundations-hard-gate*
*Next audit trigger: any change to Phase 0 implementation files, Phase 6 DID backfill of DECISION.md, or Phase 16 SPARQL endpoint hardening (replaces T-00-06′ regex preflight with parser allowlist).*
