---
phase: 2
slug: task-hierarchy-discovery
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-19
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (backend) / vitest (frontend) |
| **Config file** | `pyproject.toml` / `viewer/vitest.config.ts` |
| **Quick run command** | `python -m pytest tests/ -x -q --tb=short` |
| **Full suite command** | `python -m pytest tests/ -v && cd viewer && npx vitest run` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/ -x -q --tb=short`
- **After every plan wave:** Run `python -m pytest tests/ -v && cd viewer && npx vitest run`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 01 | 1 | TASK-01 | unit | `pytest tests/test_task_discovery.py` | ❌ W0 | ⬜ pending |
| 02-01-02 | 01 | 1 | TASK-02 | unit | `pytest tests/test_hierarchy_builder.py` | ❌ W0 | ⬜ pending |
| 02-02-01 | 02 | 2 | TASK-03 | unit | `pytest tests/test_cross_source_merger.py` | ❌ W0 | ⬜ pending |
| 02-02-02 | 02 | 2 | TASK-04 | unit | `pytest tests/test_contradiction_detector.py` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_task_discovery.py` — stubs for TASK-01
- [ ] `tests/test_hierarchy_builder.py` — stubs for TASK-02
- [ ] `tests/test_cross_source_merger.py` — stubs for TASK-03
- [ ] `tests/test_contradiction_detector.py` — stubs for TASK-04
- [ ] `tests/conftest.py` — shared fixtures (extend existing)

*Existing pytest infrastructure covers framework installation.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Drag-and-drop task restructuring | TASK-02 | Browser interaction | Drag subtask between tasks in viewer, verify tree updates |
| SSE progress display | TASK-01 | Real-time UI | Trigger discovery, verify stage pills advance |
| Contradiction side-by-side view | TASK-04 | Visual layout | Open flagged contradiction, verify both positions shown |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
