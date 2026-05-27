---
phase: 6
slug: did-substrate-6-5
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-27
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `06-RESEARCH.md` § Validation Architecture. Per-task rows are
> filled by the planner/executor once `*-PLAN.md` task IDs exist.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x (`pytest>=9.0`, `pytest-asyncio>=0.25`, `hypothesis>=6.100` — all existing dev deps) |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`, `asyncio_mode=auto`, `timeout=30`) |
| **Quick run command** | `pytest tests/identity/ -x -q` |
| **Full suite command** | `pytest tests/identity/ tests/shards/ tests/revision/ -q` |
| **Estimated runtime** | ~30–90 seconds (the 1000-shard JCS property test dominates; cap hypothesis examples if it exceeds the 30s per-test timeout) |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/identity/ -x -q`
- **After every plan wave:** Run the full suite command above
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 90 seconds

---

## Per-Task Verification Map

> Task IDs map to the test-authoring task of each plan (06-01 Task 4, 06-02 Task 4,
> 06-03 Task 4). `nyquist_compliant` flips to true at execution sign-off once these run green.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 06-01-04 | 01 | 1 | DID-03 | T-06-02/F4 | JCS canonical hash is order-independent + NFC-stable | property | `uv run pytest tests/identity/test_canonical_jcs_properties.py -q` | ❌ W0 | ⬜ pending |
| 06-01-04 | 01 | 1 | DID-03 | T-06-02/F4 | canonical bytes match cyberphone reference vectors | golden | `uv run pytest tests/identity/test_jcs_golden.py -q` | ❌ W0 | ⬜ pending |
| 06-02-04 | 02 | 2 | DID-04/SEC-05 | T-06-06/F2 | historical signature verifies after key rotation | unit | `uv run pytest tests/identity/test_signature_survives_key_rotation.py -q` | ❌ W0 | ⬜ pending |
| 06-02-04 | 02 | 2 | DID-06 | T-06-05 | no code path persists a private key server-side | contract | `uv run pytest tests/identity/test_no_server_keys_contract.py -q` | ❌ W0 | ⬜ pending |
| 06-02-04 | 02 | 2 | DID-01 | T-06-08 | sign/verify did:key + did:web; did:plc resolve/verify | unit | `uv run pytest tests/identity/test_sign_verify_methods.py -q` | ❌ W0 | ⬜ pending |
| 06-03-04 | 03 | 3 | DID-07 | — | preview renders hash + diff for all 8 action types | param | `uv run pytest tests/identity/test_signing_preview.py -q` | ❌ W0 | ⬜ pending |
| 06-03-04 | 03 | 3 | DID-05/SEC-06 | T-06-10/T-06-11/F3/F7 | replayed/stale binding proof rejected; bind to `sub` | unit | `uv run pytest tests/identity/test_binding_proof.py -q` | ❌ W0 | ⬜ pending |
| 06-03-04 | 03 | 3 | DID-02 | — | each of 8 write actions yields a populated AttestedSignature | param | `uv run pytest tests/identity/test_attested_signature_shape.py -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/identity/__init__.py` + `tests/identity/conftest.py` — shared fixtures (sample keypairs, recorded did:web/did:plc resolver responses, shard builders mirroring `tests/shards/conftest.py` + `tests/revision/conftest.py`)
- [ ] `tests/identity/fixtures/jcs_golden/` — ~50 cyberphone/json-canonicalization reference vectors
- [ ] New deps installed: `PyNaCl`, `jcs`, `atproto`, `dag-cbor`, `joserfc`, `authlib` (operator-approved dependency-add task)

*Existing pytest/hypothesis/pytest-asyncio infrastructure covers the runner; only the `tests/identity/` tree and fixtures are new.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `folio-insights did generate/bind/sign/verify` CLI ergonomics | DID-05/DID-07 (CLI form) | Human-judgment on prompt clarity + preview readability | Run each subcommand against a scratch `~/.folio-insights` keystore; confirm the DID-07 preview is human-readable for a representative action |

*All cryptographic/contract behaviors have automated verification; only CLI ergonomics are manual.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
