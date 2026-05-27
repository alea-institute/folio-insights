---
phase: 5
slug: content-versioning-6-4
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-27
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (with pytest-asyncio 1.3.0, `asyncio_mode="auto"` — installed) |
| **Config file** | `pyproject.toml` / `pytest.ini` (asyncio_mode already set) |
| **Quick run command** | `uv run pytest tests/shards -q` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | ~{N} seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/shards -q`
- **After every plan wave:** Run `uv run pytest -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** {N} seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| {N}-01-01 | 01 | 1 | SHARD-09 | T-5-01 / — | {expected secure behavior or "N/A"} | unit | `{command}` | ✅ / ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Populated by the planner / nyquist auditor once PLAN.md task IDs exist.*

---

## Wave 0 Requirements

- [ ] `tests/shards/test_content_edit_audit_append_only.py` — exit criterion 1 (SHARD-09)
- [ ] `tests/shards/conftest.py` — extend `_sample_shard` for the new `field_path`/`rationale`/`signature` ContentEdit shape
- [ ] 10-edit fixture — exit criterion 3 (`get_shard_at` reverse-replay)

*Existing pytest + pytest-asyncio infrastructure covers framework needs; no install required.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| {behavior} | SHARD-09 | {reason} | {steps} |

*Candidate: none expected — append-only, reverse-replay, and SHACL-guard behaviors are all automatable.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < {N}s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
