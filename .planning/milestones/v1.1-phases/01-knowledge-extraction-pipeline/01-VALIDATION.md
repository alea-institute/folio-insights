---
phase: 1
slug: knowledge-extraction-pipeline
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-17
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | pyproject.toml `[tool.pytest.ini_options]` |
| **Quick run command** | `pytest tests/ -x -q --timeout=30` |
| **Full suite command** | `pytest tests/ -v --timeout=120` |
| **Estimated runtime** | ~45 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/ -x -q --timeout=30`
- **After every plan wave:** Run `pytest tests/ -v --timeout=120`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 45 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 01-01-01 | 01 | 1 | INGEST-01 | integration | `pytest tests/test_ingestion.py -k test_ingest_directory` | ❌ W0 | ⬜ pending |
| 01-01-02 | 01 | 1 | INGEST-02 | unit | `pytest tests/test_ingestion.py -k test_preserve_structure` | ❌ W0 | ⬜ pending |
| 01-01-03 | 01 | 1 | INGEST-03 | unit | `pytest tests/test_ingestion.py -k test_variable_length` | ❌ W0 | ⬜ pending |
| 01-02-01 | 02 | 2 | EXTRACT-01 | integration | `pytest tests/test_extraction.py -k test_boundary_detection` | ❌ W0 | ⬜ pending |
| 01-02-02 | 02 | 2 | EXTRACT-02 | unit | `pytest tests/test_extraction.py -k test_distill_ideas` | ❌ W0 | ⬜ pending |
| 01-02-03 | 02 | 2 | EXTRACT-03 | unit | `pytest tests/test_extraction.py -k test_distill_nuance` | ❌ W0 | ⬜ pending |
| 01-02-04 | 02 | 2 | EXTRACT-04 | unit | `pytest tests/test_extraction.py -k test_extract_obvious` | ❌ W0 | ⬜ pending |
| 01-02-05 | 02 | 2 | EXTRACT-05 | unit | `pytest tests/test_extraction.py -k test_flag_novelty` | ❌ W0 | ⬜ pending |
| 01-02-06 | 02 | 2 | EXTRACT-06 | integration | `pytest tests/test_dedup.py -k test_dedup_across_docs` | ❌ W0 | ⬜ pending |
| 01-02-07 | 02 | 2 | CLASS-01,02,03 | unit | `pytest tests/test_classification.py` | ❌ W0 | ⬜ pending |
| 01-02-08 | 02 | 2 | FOLIO-01,02,03,04 | integration | `pytest tests/test_folio_tagging.py` | ❌ W0 | ⬜ pending |
| 01-03-01 | 03 | 3 | QUAL-01 | integration | `pytest tests/test_output.py -k test_human_reviewable` | ❌ W0 | ⬜ pending |
| 01-03-02 | 03 | 3 | QUAL-02 | unit | `pytest tests/test_output.py -k test_confidence_gating` | ❌ W0 | ⬜ pending |
| 01-03-03 | 03 | 3 | QUAL-03 | integration | `pytest tests/test_output.py -k test_machine_parseable` | ❌ W0 | ⬜ pending |
| 01-03-04 | 03 | 3 | PIPE-02 | integration | `pytest tests/test_cli.py -k test_batch_pipeline` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/conftest.py` — shared fixtures (sample MD/DOCX files, mock FolioService)
- [ ] `tests/test_ingestion.py` — stubs for INGEST-01, INGEST-02, INGEST-03
- [ ] `tests/test_extraction.py` — stubs for EXTRACT-01 through EXTRACT-06
- [ ] `tests/test_classification.py` — stubs for CLASS-01, CLASS-02, CLASS-03
- [ ] `tests/test_folio_tagging.py` — stubs for FOLIO-01 through FOLIO-04
- [ ] `tests/test_dedup.py` — stubs for EXTRACT-06
- [ ] `tests/test_output.py` — stubs for QUAL-01, QUAL-02, QUAL-03
- [ ] `tests/test_cli.py` — stubs for PIPE-02
- [ ] `pytest` + `pytest-asyncio` + `pytest-timeout` — install via pyproject.toml

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Review viewer three-pane layout renders correctly | QUAL-01 | Visual layout verification | Open folio-insights viewer, verify tree/detail/source panes render |
| FOLIO tree navigation matches folio-mapper patterns | QUAL-01 | UX consistency check | Compare tree behavior with folio-mapper side by side |
| Distilled text preserves tactical nuance | EXTRACT-03 | Subjective quality judgment | Review 20 random extractions for nuance preservation |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 45s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
