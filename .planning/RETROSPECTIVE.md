# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v1.0 — MVP

**Shipped:** 2026-04-04
**Phases:** 5 | **Plans:** 17 | **Tasks:** 40

### What Was Built
- Complete knowledge extraction pipeline: 14-format ingestion, tiered boundary detection (structural/semantic/LLM), 4-path FOLIO tagging against 27K+ concepts, cross-document deduplication
- Web-based corpus management: drag-drop upload, SSE real-time processing progress, auto-navigation
- Task hierarchy discovery: heading analysis, content clustering, NLI contradiction detection, 6-stage pipeline
- OWL ontology output: SHACL-validated FOLIO-compatible OWL, Turtle, JSON-LD RAG chunks, browsable HTML, incremental changelog
- Full end-to-end workflow: Upload → Process → Discover → Review → Export (CLI + web UI)

### What Worked
- **Bridge adapter pattern** — importing folio-enrich services via sys.path avoided code duplication while keeping codebases independent
- **Wave-based parallel execution** — plans within a wave ran in parallel worktrees, cutting execution time significantly
- **Checkpoint system** — human verification gates caught the export integration breaks before they shipped unnoticed
- **Phase verification + milestone audit** — the two-layer verification (per-phase + cross-phase integration) caught wiring bugs that individual phase checks missed

### What Was Inefficient
- **Phase 03.1 was avoidable** — the export UI integration breaks (wrong status value, ZIP-as-JSON parsing) were straightforward bugs that should have been caught during initial Plan 03-02 execution via browser testing
- **Parallel worktree merge conflicts** — every parallel execution required manual merge conflict resolution for STATE.md; a lock-free state update mechanism would save orchestrator time
- **15 scaffold test stubs** shipped in Phase 02 and lingered until gap closure — should have been real tests from the start or flagged as tech debt immediately

### Patterns Established
- Lazy imports in CLI commands (avoid heavy bridge deps on `--help`)
- Disk-based job persistence with atomic writes (tempfile + os.replace)
- SSE EventSource pattern for real-time pipeline progress
- 4-state dialog machine (idle/processing/complete/error) for async operations
- Recursive tree walks for nested TaskTreeNode data (not flat array checks)

### Key Lessons
1. **Integration checks matter more than unit verification** — all 4 phases passed their individual verification, but cross-phase wiring was broken. The milestone audit was essential.
2. **TypeScript types must match API contracts exactly** — phantom fields in interfaces cause silent runtime failures that tests don't catch
3. **Binary response endpoints need their own fetch path** — generic JSON-parsing request helpers break on non-JSON content types
4. **Browser testing during execution catches UI bugs early** — the export dialog issues would have been caught immediately with a screenshot check

### Cost Observations
- Model mix: ~70% opus (execution), ~25% sonnet (verification/integration), ~5% haiku
- Plans executed: 17 across 5 phases
- Notable: Gap closure phase (03.1) was 2 plans / ~7 minutes — fast turnaround for targeted fixes

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Plans | Key Change |
|-----------|--------|-------|------------|
| v1.0 | 5 | 17 | Initial release — established GSD workflow, bridge adapter pattern, verification gates |

### Cumulative Quality

| Milestone | Tests | Key Metric |
|-----------|-------|------------|
| v1.0 | 197 | 30/30 requirements satisfied, 5/5 E2E flows verified |

### Top Lessons (Verified Across Milestones)

1. Cross-phase integration auditing catches bugs that per-phase verification misses
2. TypeScript interfaces must be kept in sync with API response shapes — phantom fields cause silent failures
