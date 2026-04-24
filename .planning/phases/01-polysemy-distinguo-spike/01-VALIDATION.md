---
phase: 01
slug: polysemy-distinguo-spike
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-23
---

# Phase 01 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9+ with pytest-asyncio (asyncio_mode = "auto") and pytest-timeout (30s default) |
| **Config file** | `pyproject.toml [tool.pytest.ini_options]` |
| **Quick run command** | `pytest tests/polysemy/ -x --timeout=30` |
| **Full suite command** | `pytest tests/polysemy/ tests/bench/ -v --timeout=30` (excluding `-m "slow or gate3 or gate4 or gate5"` unless explicitly requested) |
| **Estimated runtime** | ~45 seconds (unit suite); ~120 seconds (full suite w/ LLM audit mocked) |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/polysemy/ -x --timeout=30`
- **After every plan wave:** Run `pytest tests/polysemy/ -v --timeout=60`
- **Before `/gsd-verify-work`:** Full suite must be green; `dispositions.jsonl` contains ≥20 accept/reject/modify entries; `fp-labeling-audit.md` + `SUMMARY.md` committed
- **Max feedback latency:** 45 seconds (unit), 120 seconds (full)

---

## Per-Task Verification Map

*Populated by planner from 01-RESEARCH.md §Validation Architecture. Each plan task MUST map to a row here.*

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | TBD | 0 | Wave-0 test scaffolding | — | N/A | infrastructure | `pytest tests/polysemy/ --collect-only` | ❌ W0 | ⬜ pending |
| TBD | TBD | 2 | PRINCIPLE-06 | — | FP rate ≤ 10% on curated ≥20-shard fixture | integration | `pytest tests/polysemy/test_fp_rate.py::test_fp_rate_within_target -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 2 | PRINCIPLE-06 | — | Auto-apply impossible by design (CLI-only) | unit | `pytest tests/polysemy/test_cli_review.py::test_no_auto_apply_path -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 2 | PRINCIPLE-06 | — | Rule 1: framework-conflicting axioms (not contexts) | unit | `pytest tests/polysemy/test_detector_rules.py::test_rule1_axioms_not_contexts -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 2 | PRINCIPLE-06 | — | Rule 2: N ≥ 3 per framework gate | unit | `pytest tests/polysemy/test_detector_rules.py::test_rule2_n_ge_3 -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 2 | PRINCIPLE-06 | — | Rule 3: terms-of-art whitelist raises threshold to 0.8 | unit | `pytest tests/polysemy/test_detector_rules.py::test_rule3_whitelist_threshold -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 2 | PRINCIPLE-06 | — | Rule 4: homonym whitelist triggers LLM fallback | unit | `pytest tests/polysemy/test_detector_rules.py::test_rule4_homonym_flag -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 2 | PRINCIPLE-06 | — | Instructor LLM fallback returns discriminated-union verdict | unit (mocked) | `pytest tests/polysemy/test_detector_llm_fallback.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 2 | VOCAB-02 | — | `fi:analogousTo` requires `fi:primeAnalogate` + `fi:proportionalRelation` | unit | `pytest tests/polysemy/test_distinguo_emission.py::test_analogousTo_requires_sub_properties -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 2 | VOCAB-02 | — | `fi:distinctionKind` in 4-enum set | unit | `pytest tests/polysemy/test_distinguo_emission.py::test_distinctionKind_enum -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 2 | VOCAB-02 | — | Emitted TTL parses via pyoxigraph + round-trips | integration | `pytest tests/polysemy/test_distinguo_emission.py::test_ttl_roundtrip_pyoxigraph -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 3 | D-3 lock | — | JSONL disposition matches Phase 15 consumer schema | unit | `pytest tests/polysemy/test_dispositions_jsonl.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 3 | D-3 lock | — | Append-only semantics (no rewrite, no truncation) | unit | `pytest tests/polysemy/test_dispositions_jsonl.py::test_append_only -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 4 | D-4 lock | — | FP-rate report includes Wilson 95% CI | unit | `pytest tests/polysemy/test_fp_rate.py::test_reports_wilson_ci -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 4 | D-4 lock | — | LLM audit pass reports disagreements only | integration (mocked) | `pytest tests/polysemy/test_fp_rate.py::test_audit_disagreements_only -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 3 | CLI ergonomics | — | `folio-insights polysemy review` accept/reject/modify paths | integration | `pytest tests/polysemy/test_cli_review.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 3 | Reviewer DID | — | First-invocation generates real did:key; persisted | unit | `pytest tests/polysemy/test_reviewer_did.py -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Planner will replace `TBD` with `{N}-PP-TT` task IDs during plan generation.*

---

## Wave 0 Requirements

- [ ] `tests/polysemy/__init__.py` — package marker
- [ ] `tests/polysemy/conftest.py` — session-scoped `consideration_fixture_store` (mirrors `tests/bench/conftest.py::bench_store` pattern)
- [ ] `tests/polysemy/test_detector_rules.py` — unit tests for 4 rule gates
- [ ] `tests/polysemy/test_detector_llm_fallback.py` — mocked instructor; unit
- [ ] `tests/polysemy/test_prototype_cluster.py` — centroid math; unit
- [ ] `tests/polysemy/test_distinguo_emission.py` — VOCAB-02 TTL round-trip via pyoxigraph; integration
- [ ] `tests/polysemy/test_cli_review.py` — CliRunner + scripted stdin; integration
- [ ] `tests/polysemy/test_dispositions_jsonl.py` — schema + append semantics; unit
- [ ] `tests/polysemy/test_fp_rate.py` — FP-rate harness + Wilson CI; integration (network for audit pass)
- [ ] `tests/polysemy/test_reviewer_did.py` — did:key generation; unit
- [ ] New pytest marker in pyproject.toml: `polysemy_spike: Phase 1 polysemy-distinguo spike tests`

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Self-labeled gold set FP reconciliation | D-4 lock | Requires human judgement on borderline polysemy vs homonymy cases | 1. Run `folio-insights polysemy audit --emit-disagreements`. 2. For each disagreement row in `fp-labeling-audit.md`, record final label. 3. Commit authoritative labels. |
| Per-framework threshold recommendation | PRINCIPLE-06 | Output is a policy recommendation for Phase 9.P6, not a test assertion | Author `SUMMARY.md` §Thresholds with proposed default band + per-framework overrides + rationale. |
| Human-gate UX acceptance | §16 R2 "no auto-apply" | CLI-only ergonomics evaluated on live review session | Run ≥20-shard review session end-to-end; confirm every disposition required a keystroke; no batch/auto flags exist. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 45s (unit), < 120s (full)
- [ ] `nyquist_compliant: true` set in frontmatter (after planner populates task-ID map)

**Approval:** pending
