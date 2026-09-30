---
title: v2.0 GSD-to-CE Migration - Plan
type: refactor
date: 2026-09-27
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-plan-bootstrap
execution: code
---

# v2.0 GSD-to-CE Migration - Plan

## Goal Capsule

- **Objective:** Anyone opening folio-insights can see, from one CE plan, exactly what v2.0 shipped, what is still wanted, and what is waiting on Damien — with no dormant GSD milestone pretending to be in flight.
- **Means:** Archive the GSD milestone as partially shipped, clear the known chores, re-verify the park risks, and queue every remaining v2.0 phase as a gated candidate unit (KTD1, KTD2).
- **Authority:** Damien's answers on cockpit ask `folio-insights-2026-09-28-0024-audit-exposure-and-v2-review` (q2, q3) > this plan > `.planning/STATE.md` "Remaining Work" > `.planning/ROADMAP.md`.
- **Stop conditions:** Stop a unit and ask when it would open a gated candidate phase without Damien's yes, change Damien’s confirmed R18 disposition or implement candidates beyond the authorized planning scope.
- **Execution profile:** U1–U4, U15, and U16 are agent-doable now. U5 is confirmed locally in `docs/reviews/2026-09-30-r18-disposition.md`. Damien authorized U6 planning after R18 and U14 planning after Phase 13; implementation and the remaining candidates retain their separate gates.
- **Finishes and ships:** ce-work in this repo; merges and pushes follow the standing 2026-09-20 authorization.

---

## Product Contract

### Summary

Close out the parked GSD milestone "v2.0 shards-as-axioms" and move its surviving scope into CE. Phases 0–8 stay as shipped code. The GSD tracking files become history. The remaining phases (9–20) become candidate units that wait for an explicit scope yes. The unmerged proposed-class governance pipeline joins as one of those candidates.

### Problem Frame

v2.0 was parked on 2026-07-26 with a confirmed review date of 2026-08-23. The review never happened. The folio-propositions review packet it waited on shipped on 2026-08-17 (library v0.3.0 plus `docs/exit-record-phase-a.md`), so nothing technical still blocks the review. Meanwhile the repo carries dead Railway config, a Gate-5 test that fails on this box for want of a `python` shim, three stale worktree gitlinks, and a July 15 governance branch that no longer merges cleanly. A 2026-09-27 audit found no plans or commits in the prior 21 days: the work is not interrupted, it is undecided.

### Key Decisions

- **Archive GSD, re-plan in CE.** (session-settled: user-directed — chosen over resuming Phase 09 under GSD or re-parking: Damien's 2026-08-02 note already favored conversion.) Governs R1, R2, R7.
- **Fold the governance branch into this plan.** (session-settled: user-directed — chosen over rebase-and-ship-now or archiving: avoids redoing work the re-plan may change.) Governs R8.
- **Storage layer first among candidates.** (session-settled: user-approved — chosen over ROADMAP order: Phase 13 converts three shipped stubs into working features.) Governs R7.
- **Draft R18 recommendations for Damien to confirm.** (session-settled: user-approved — chosen over leaving the template blank.) Governs R5.

### Requirements

**Archive and tracking**

- R1. The GSD milestone is marked archived-as-partially-shipped, crediting Phases 0–8 as shipped, naming Phase 0 Gate 4 (SSR <200 ms) and D-11 (full-1M reasoner run) as deferred verification exceptions, and pointing to this plan as the successor.
- R2. No GSD phase directory, code, or verification artifact is deleted; `.planning/` stays as read-only history.

**Chores**

- R3. The Gate-5 Dagger test runs on a box that has only `python3`.
- R4. Dead Railway deploy config is removed, the three stale `.claude/worktrees/` gitlinks are removed, and the worktree path is ignored.

**Review and gates**

- R5. A drafted R18 disposition, with one recommended accept/revise/reject per packet element group, is ready for Damien to confirm or change.
- R6. The PRD HOLD banner is lifted only after Damien's R18 disposition is recorded, and is then replaced by a pointer to that record.
- R7. Each remaining v2.0 phase appears as a candidate unit with an explicit scope gate, with Phase 13 first.
- R10. A gated candidate unit covers migrating the shipped shard envelope and subtypes (Phases 2–3) to whatever the R18 disposition accepts or revises.
- R8. The proposed-class governance pipeline appears as a candidate unit carrying its known merge conflicts and its evidence-stripping requirement.

**Risk re-verification**

- R9. The three open park risks (viewer collision, folio-resolve drift, stack drift) are re-verified with cited evidence, and the results are recorded where the next planner will read them.

### Scope Boundaries

- Implementing any of Phases 9–20 is out of scope for this plan's active units. Each needs its own ce-plan after Damien's gate yes.
- The folio-propositions polarity field is decided in folio-enrich (answered on ask `folio-enrich-2026-08-17-1858-propositions-dns-and-cycle1`). This plan only reads that answer.
- The two public `archive/*` remote branches that still hold the Ch01 manuscript are a separate, Damien-owned deletion. They are not part of this plan.

### Deferred to Follow-Up Work

- One ce-plan per candidate phase Damien approves (U6–U13).
- Phase 0 Gate 4 (SSR <200 ms) and D-11 full-1M reasoner run remain deferred per `00-07-D6`.

---

## Planning Contract

### Key Technical Decisions

- KTD1. Archive by status, not by moving files. Update `.planning/STATE.md` frontmatter and banner, add an archive entry to `.planning/MILESTONES.md`, and leave phase directories in place. Moving files would break the many cross-references in plan SUMMARY and VERIFICATION docs. Governs R1, R2.
- KTD2. Candidate units reference ROADMAP phases rather than copying them. Each unit carries only the deltas the 2026-07-26 reality audit found: obsolete, re-scope, or retarget. Governs R7.
- KTD3. Fix Gate-5 at the call site, not the environment: invoke the current interpreter (`sys.executable`) instead of a bare `python`. This works on CI boxes and on this box without a system shim. Governs R3.
- KTD4. Delete `railway.toml`, `ci/railway.py`, and the Railway references in `ci/build.py` and `tests/bench/test_gate5_digest.py` only after confirming nothing but Phase 3.5's retired deliverable imports them. The Coolify deployment reads neither. Governs R4.
- KTD5. The governance work lands on a fresh branch cut from current master, never by replaying the old commits: bring its code and tests across as new commits with every book-derived artifact excluded, so no copyrighted prose enters history. Book-derived means `docs/evidence/books-ch0*`, the generated `data/governance/` registry, worklist, verdict, and approval-queue files (they carry `source_text_excerpt` / `supporting_excerpt` book spans), and any changed `docs/evidence/books/pack.*`. Regenerate or seed the registry without excerpts. The known conflicts are `.gitignore`, `src/folio_insights/pipeline/stages/folio_tagger.py`, and `tests/test_folio_tagging.py`. Governs R8.

### Sequencing

U1, U2, and U4 are independent; U3 follows U2 because both edit `tests/bench/test_gate5_digest.py`. U5 depends on nothing in this repo but needs Damien. U6 (Phase 13) is the first candidate once gated in and once U5's disposition is recorded. U14 (governance) follows U6, per Damien’s 2026-09-30 answer; it no longer runs in parallel.

### Assumptions

- The Coolify deployment at `folio-insights.dev.openlegalstandard.org` does not read `railway.toml` (Coolify builds from its own app config).
- `folio-resolve==0.4.0` is the intended pin; drift risk is now bounded by the exact pin rather than `>=0.1.0`.

---

## Implementation Units

### U1. Archive the GSD v2.0 milestone

**Goal:** Mark v2.0 archived-as-partially-shipped and point to this plan.
**Requirements:** R1, R2
**Dependencies:** none
**Files:** `.planning/STATE.md`, `.planning/MILESTONES.md`, `.planning/ROADMAP.md`
**Approach:**
1. Set STATE frontmatter `status` to archived with the ask stem and date, and replace the PARKED banner with an ARCHIVED banner naming this plan as successor.
2. Add a v2.0 entry to MILESTONES.md: Phases 0–8 shipped (Gate 4 and D-11 deferred), 9–20 moved to CE candidates.
3. Add a one-line pointer at the top of ROADMAP.md; leave phase text unchanged.
**Patterns to follow:** The existing PARKED banner and "Reconciliation" sections in `.planning/STATE.md`.
**Test expectation:** none -- tracking docs only.
**Verification:** STATE, MILESTONES, and ROADMAP all name this plan; no file under `.planning/phases/` changed.

### U2. Make Gate-5 run without a `python` shim

**Goal:** `tests/bench/test_gate5_digest.py` stops failing with `FileNotFoundError: 'python'`.
**Requirements:** R3
**Dependencies:** none
**Files:** `tests/bench/test_gate5_digest.py`, and `ci/build.py` if it shells out to `python` too
**Approach:** Replace bare `python` subprocess invocations with the running interpreter (KTD3). Give the two local-build Gate-5 tests a per-test timeout override, because `pyproject.toml` sets a global `timeout = 30` that would kill a real Dagger build.
**Test scenarios:**
- On a box with only `python3` on PATH, the Gate-5 test reaches its digest comparison instead of raising `FileNotFoundError`.
- If Dagger itself is unavailable, the test skips with a clear reason rather than erroring.
**Verification:** The full suite reports no Gate-5 environment failure.

### U3. Remove dead Railway config

**Goal:** No Railway deploy config remains.
**Requirements:** R4
**Dependencies:** U2 if both touch `tests/bench/test_gate5_digest.py`
**Files:** `railway.toml`, `ci/railway.py`, `ci/__init__.py`, `ci/build.py`, `tests/bench/test_gate5_digest.py`, `.claude/settings.local.json` (check only)
**Approach:** Confirm with a repo-wide reference search that only retired Phase 3.5 paths use these files, then delete them and drop their imports (KTD4). Keep `ci/build.py` if Gate-5 still needs it. Remove `test_local_matches_railway_deployed_digest`, which pulls from `registry.railway.app`; Gate 5 keeps its local bit-identical build test.
**Test scenarios:**
- The test suite collects with no `ImportError` for `ci.railway`.
- A reference search for `railway` outside `.planning/` returns only historical docs.
**Verification:** Suite passes; the Coolify health endpoint is unaffected (the deploy does not read these files).

### U4. Remove stale worktree gitlinks

**Goal:** `git status` is clean of the three deleted `.claude/worktrees/agent-*` entries.
**Requirements:** R4
**Dependencies:** none
**Files:** `.claude/worktrees/agent-a89d42039b1805b51`, `.claude/worktrees/agent-aade68719f00e1272`, `.claude/worktrees/agent-abf2288ab0e18d44b`, `.gitignore`
**Approach:** Remove the gitlinks from the index and ignore `.claude/worktrees/` so agent worktrees are never tracked again.
**Test expectation:** none -- repository hygiene.
**Verification:** `git status` shows no `.claude/worktrees` entries.

### U5. Draft the R18 review disposition

**Goal:** Damien can complete the v2.0 review as a confirmation pass.
**Requirements:** R5, R6
**Dependencies:** none (Damien confirms)
**Files:** `../folio-propositions/docs/review-disposition-v2.0.md` (new record in target repo folio-propositions, created from the unchanged `docs/review-disposition.md` template), `PRD-v2.0-draft-2.md`
**Approach:**
1. Draft a recommended disposition for each of the ten packet element groups from `docs/exit-record-phase-a.md`, `docs/review-disposition.md`, and `docs/migration-0.3.0.md` in folio-propositions, marking each line as a recommendation.
2. File it as a Decision Sheet through `cockpit-decide`, one question per element group that is not already settled (the taxonomy was confirmed on 2026-08-17).
3. After Damien answers, record the disposition and replace the PRD HOLD banner with a pointer to it (R6).
**Test expectation:** none -- review record.
**Verification:** The v2.0 record file has no bracketed placeholders, the template is unchanged, and the PRD banner cites the record.

### U6. Candidate: Phase 13 Storage Layer (gated, first)

**Goal:** Replace the in-memory `GovernanceLog`, `ShardStore`, and the `retract --apply` `NotImplementedError` with a persistent store.
**Requirements:** R7
**Dependencies:** Damien's gate yes; U5's disposition recorded; U17 when R18 revises the envelope; then its own ce-plan
**Files:** `src/folio_insights/governance/log.py`, `src/folio_insights/governance/cli/retract.py`, `src/folio_insights/revision/`
**Approach:** Re-plan from ROADMAP §Phase 13 (KTD2). Deltas: the store schema follows the accepted R18 identity and ledger field groups; and Phase 13 now runs ahead of Phase 11, so the SHACL-on-write hook and the SHACL part of its exit criterion 7 become an explicit seam that Phase 11 (U9) closes. Re-run the Gate-2 SPARQL benchmark first as the stack-drift canary.
**Test expectation:** defined by its own plan.
**Verification:** defined by its own plan.

### U7. Candidate: Phase 09 Seven Design Principles (gated)

**Goal:** Ship the §8 design principles as sub-phased capabilities.
**Requirements:** R7
**Dependencies:** Damien's gate yes
**Files:** per ROADMAP §Phase 9
**Approach:** Unchanged from ROADMAP. 9.P6 and 9.P7 already have their spikes (Phases 1 and 8). Sub-phase it.
**Test expectation:** defined by its own plan.
**Verification:** defined by its own plan.

### U8. Candidate: Phase 10 Pipeline Refactor (gated, re-plan)

**Goal:** Carry the §9 LLM-agnostic pipeline goal onto the current folio-resolve-based tagger.
**Requirements:** R7
**Dependencies:** Damien's gate yes
**Files:** `src/folio_insights/pipeline/stages/folio_tagger.py`
**Approach:** Obsolete as written. Re-plan from the current tagger (as it stands after U14, if U14 lands first), `docs/evidence/books/`, and `docs/rubrics/extraction-quality-v1.md`, not from §9.
**Test expectation:** defined by its own plan.
**Verification:** defined by its own plan.

### U9. Candidate: Phases 11, 12, 13.5 (gated)

**Goal:** SHACL hybrid, observability, and private corpora, as written in ROADMAP.
**Requirements:** R7
**Dependencies:** Damien's gate yes; 13.5 depends on U6; Phase 11 closes U6's SHACL-on-write seam
**Files:** per ROADMAP
**Approach:** Unchanged from ROADMAP.
**Test expectation:** defined by their own plans.
**Verification:** defined by their own plans.

### U10. Candidate: Phases 14 and 15 Review UI (gated, re-scope)

**Goal:** One design contract for the SvelteKit viewer.
**Requirements:** R7, R9
**Dependencies:** Damien's gate yes; U15's viewer-collision result
**Files:** `viewer/`
**Approach:** Re-scope against the CE in-app annotator design before planning. No viewer commits have landed since 2026-05-31, so the collision is still prospective.
**Test expectation:** defined by its own plan.
**Verification:** defined by its own plan.

### U11. Candidate: Phases 16, 17, 18, 18.5 (gated)

**Goal:** Public SPARQL endpoint and write API, testing consolidation, community docs, corpus fork.
**Requirements:** R7
**Dependencies:** Damien's gate yes; 16 depends on U6
**Files:** per ROADMAP
**Approach:** Unchanged from ROADMAP.
**Test expectation:** defined by their own plans.
**Verification:** defined by their own plans.

### U12. Candidate: Phase 19 Security Audit (gated)

**Goal:** Pre-release security audit; blocks release.
**Requirements:** R7
**Dependencies:** whichever of U6–U11 are approved
**Files:** per ROADMAP
**Approach:** Unchanged from ROADMAP.
**Test expectation:** defined by its own plan.
**Verification:** defined by its own plan.

### U13. Candidate: Phase 20 Release Cut (gated, retarget)

**Goal:** Release v2.0 on Hetzner/Coolify.
**Requirements:** R7
**Dependencies:** U12
**Files:** per ROADMAP
**Approach:** Rewrite the exit criterion against Coolify; Railway is gone (U3).
**Test expectation:** defined by its own plan.
**Verification:** defined by its own plan.

### U14. Candidate: Proposed-class governance pipeline (gated)

**Goal:** Land collect → judge → approve → export for proposed FOLIO classes.
**Requirements:** R8
**Dependencies:** Damien's gate yes
**Files:** from local branch `feat/proposed-class-governance` (15 commits, none patch-equivalent on master): `src/folio_insights/proposals/`, `scripts/judge_proposals.py`, `tests/proposals/`, `docs/plans/2026-07-15-001-feat-proposed-class-governance-plan.md`, plus the branch's B4–B9 tagger and discovery fixes, `persistence/review_db.py`, the anchoring and substance services, `api/db/models.py`, and boundary-detection changes with their tests
**Approach:** Build the fresh branch per KTD5 and resolve the known conflicts against the folio-resolve 0.4.0 tagger. All non-evidence code and tests on the branch come across, so Damien's gate covers everything that lands. Bring the July 15 plan across as its origin.
**Execution note:** Characterize the current tagger's proposed-class output before resolving the `folio_tagger.py` conflict.
**Test scenarios:**
- The existing `tests/proposals/` suites pass on the rebased branch.
- The tagger conflict resolution preserves the B9 rule that empty-IRI proposed tags do not vote.
- No file under `docs/evidence/books-ch0*` exists on the new branch.
- A search of the new branch's tree for non-empty `source_text_excerpt` or `supporting_excerpt` values finds none.
- The new branch's history (`master..` range) never adds a KTD5 book-derived path.
**Verification:** Suite passes, and neither the tree nor the history of the branch contains book-derived text.

### U17. Candidate: Shard envelope migration to the R18 disposition (gated)

**Goal:** Bring the shipped shard envelope and subtypes into line with the accepted or revised R18 packet groups.
**Requirements:** R10
**Dependencies:** U5's disposition recorded; Damien's gate yes; lands before U6 builds a store on the envelope
**Files:** `src/folio_insights/shards/envelope.py`, `src/folio_insights/shards/subtypes.py`, `tests/shards/`, `PRD-v2.0-draft-2.md` §6–§7
**Approach:** Size from the R18 groups marked accepted or revised; a fully rejected packet makes this unit a no-op. Honor the PRD HOLD fallback (freeze the six identity fields) if the timeline requires it.
**Test expectation:** defined by its own plan.
**Verification:** defined by its own plan.

### U15. Re-verify the park risks

**Goal:** Record current evidence for the three open park risks.
**Requirements:** R9
**Dependencies:** none
**Files:** `.planning/STATE.md` (Park Risks section), or this plan's Appendix
**Approach:**
1. Viewer collision: list `viewer/` commits since 2026-05-31 (none at planning time).
2. folio-resolve drift: confirm the exact `==0.4.0` pin and that the suite passes against it.
3. Stack drift: run the full suite and the Gate-2 benchmark, and compare with the 2026-07-26 numbers (1010 passed; q13 warm median ≈109 ms).
**Test expectation:** none -- verification only.
**Verification:** Each risk has a dated result with its command and output cited.

### U16. Queue candidates and file scope gates

**Goal:** Put every gated candidate in front of Damien, so the gates do not sit undecided.
**Requirements:** R7, R8
**Dependencies:** none
**Files:** cockpit `briefs/on-deck.json` (cockpit repo), a `cockpit-decide` ask
**Approach:**
1. Add U6–U14 and U17 to the cockpit On Deck queue, each with its gate stated and a link to this plan.
2. File the U6 (Phase 13) and U14 (governance pipeline) scope gates as `cockpit-decide` questions, alongside U5's sheet, with the other candidates as context.
**Test expectation:** none -- queue and decision records.
**Verification:** The On Deck entries render on the board, and the gate questions have a live sheet URL.

---

## Verification Contract

- Full suite: `pytest -q` from the repo `.venv`, using the same marker selection as the 2026-07-26 baseline (1010 passed, 10 skipped).
- Gate-2 benchmark: the `tests/bench/` SPARQL P95 harness stays under the 500 ms hard gate.
- Gate-5: run separately with the `gate5` marker on `tests/bench/test_gate5_digest.py`; it passes or skips with a reason, and never errors on a missing `python` or the global 30 s timeout (U2).
- Repository hygiene: `git status` is clean after U3 and U4.

---

## Definition of Done

- U1–U4 and U15 are landed and verified.
- U16's On Deck entries and gate questions are filed.
- U5's Decision Sheet is filed. The PRD HOLD banner stays until Damien's disposition is recorded.
- No abandoned-attempt code is left in the diff.
