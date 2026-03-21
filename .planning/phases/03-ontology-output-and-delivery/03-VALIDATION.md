---
phase: 03
slug: ontology-output-and-delivery
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-21
---

# Phase 03 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | pytest.ini |
| **Quick run command** | `pytest tests/ -x -q --tb=short` |
| **Full suite command** | `pytest tests/ -v --tb=long` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/ -x -q --tb=short`
- **After every plan wave:** Run `pytest tests/ -v --tb=long`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 1 | OWL-01 | unit | `pytest tests/test_owl_serializer.py -x` | ❌ W0 | ⬜ pending |
| 03-01-02 | 01 | 1 | OWL-02 | unit | `pytest tests/test_iri_generation.py -x` | ❌ W0 | ⬜ pending |
| 03-01-03 | 01 | 1 | OWL-03 | unit | `pytest tests/test_skos_companion.py -x` | ❌ W0 | ⬜ pending |
| 03-02-01 | 02 | 2 | OWL-04 | unit | `pytest tests/test_output_formats.py -x` | ❌ W0 | ⬜ pending |
| 03-02-02 | 02 | 2 | OWL-05 | unit | `pytest tests/test_owl_validation.py -x` | ❌ W0 | ⬜ pending |
| 03-02-03 | 02 | 2 | PIPE-01 | integration | `pytest tests/test_incremental.py -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_owl_serializer.py` — stubs for OWL-01 (OWL module generation)
- [ ] `tests/test_iri_generation.py` — stubs for OWL-02 (deterministic IRI generation)
- [ ] `tests/test_skos_companion.py` — stubs for OWL-03 (SKOS/RDFS companion file)
- [ ] `tests/test_output_formats.py` — stubs for OWL-04 (SPARQL, JSON-LD, HTML/MD)
- [ ] `tests/test_owl_validation.py` — stubs for OWL-05 (validation pipeline)
- [ ] `tests/test_incremental.py` — stubs for PIPE-01 (incremental processing)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Human-browsable HTML renders knowledge hierarchy | OWL-04 | Visual rendering quality | Open generated HTML in browser, verify hierarchy navigation works |
| FOLIO maintainer review artifacts (annotated diffs) | OWL-05 | Requires human judgment | Inspect diff output for clarity and completeness |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
