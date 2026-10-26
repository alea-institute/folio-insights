---
session: "35427fe9-7529-415d-9172-a503eeb78bbc"
written_at: "2026-10-26T12:20:02.778Z"
head: "6e7b1569d0c43bfbb8b3b48c434158e0e69e9a90"
worktree: "/home/damienriehl/Coding Projects/folio-insights"
branch: "master"
---
# Handoff: measured propositions and workbench, Codex drain (2026-10-26)

## State
- **Merged:** README rewrite (PR #48, then flattened to propositions in PR #49). The GitHub About panel now has a description and 15 topics.
- **Merged:** the requirements-only plan `docs/plans/2026-10-26-0716-feat-measured-propositions-and-workbench-plan.md` (PR #50). Its decisions are recorded in the Cockpit record `folio-insights-2026-10-26-1218-measured-propositions-decisions`.
- **Running:** a Codex planner (worker `folio-measured-plan-20261026`) enriches that plan in place via `ce-plan` on branch `docs/measured-plan-enrich`, in a worktree under `~/worktrees/`. Done: 60 units; the orchestrator rescheduled them to 21 waves (KTD15: Codex builds offline, live runs and corpus fetching belong to the orchestrator, output-changing units merge behind a live gate) and added pooled tag-recall gold (KTD2).

## Next
1. **Verify planner output.** When the planner reaches `review_ready`, confirm three things, then push, open a PR, and merge:
   - **Plan commit:** the enriched plan is committed on the branch.
   - **Product Contract:** it is unchanged.
   - **Units:** every unit has its files, tests, verify command, and wave.
2. **Dispatch waves.** Send each wave to Codex workers through `agents/worker-wrapper.sh`, with at most 3 at a time; this shares `agent-admit` limits with the Chief drain. Units marked "network: yes" go to Claude subagents.
3. **Instrument first.** Land the measuring loop before any pipeline change: gold suite, scorer, judges, annotation store, gate, and README regeneration.

## Constraints
- **Autonomous week:** Damien is at a conference the week of 2026-10-26. Judge autonomously, and label every score "judge agreement, unanchored" (R5).
- **Codex credits:** Damien's Codex credits expire about 2026-10-28. Prefer Codex workers for everything Codex can do.
- **Pending from Damien:** the location of his know-how materials, and verification of the anchor sets.
