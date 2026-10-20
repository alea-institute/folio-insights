---
title: Review UI Re-scope (Phases 14–15 + In-App Annotator + Approval Queue) - Plan
type: feat
date: 2026-10-20
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-plan-bootstrap
execution: design
---

# Review UI Re-scope (Phases 14–15 + In-App Annotator + Approval Queue) - Plan

## Goal Capsule

- **Objective:** One design contract for the SvelteKit `viewer/` that merges three review surfaces into a single app, with one design system and one review inbox:
  - **Phase 14/15 review UI:** shard page, polysemy fork, supersession timeline, contest/retract/supersede wizards and dependency graph (`.planning/ROADMAP.md` Phases 14–15).
  - **In-app annotator:** span-anchored full-text rendering with per-tag correct/weak/wrong verdicts (`docs/brainstorms/2026-07-15-folio-matching-platform-brainstorm.md` §6).
  - **Proposed-class approval queue:** approve, reject, merge or needs-work decisions, now recorded through the single ledger (`docs/plans/2026-10-04-1033-fix-single-approval-surface-plan.md`).
- **Authority:** Decision Sheet `folio-insights-2026-10-04-1531-v2-next-phases`, question `q4-review-ui`, answered "Re-scope plan, then show me" on 2026-10-20. Chief, the automated first responder, gave the answer under the 2026-09-30 Decision Bar, and Damien can overrule it.
  - **Lineage:** migration-plan U10 (`docs/plans/2026-09-27-1930-refactor-v2-gsd-to-ce-migration-plan.md`) required this re-scope before Phase 14 or 15 planning starts.
- **Execution profile:** this plan and the static mockups only. **No viewer code gets built** until Damien reviews the look and workflow, which the answer reserves for him ("then show me").
- **Stop conditions:**
  - Any build of `viewer/` surfaces from this plan stops until Damien's review answer arrives.
  - Any mockup that renders real, non-public source text stops; mockups use synthetic text only.
- **Delivery:** branch `docs/review-ui-rescope`: plan and mockups under `docs/design/review-ui/`. Damien's look-and-workflow review rides a Decision Sheet.

## Product Contract

### Summary

The viewer gained commits after the 2026-05-31 freeze the migration plan noted: operator tokens, per-session LLM keys (BYOK) and, on 2026-10-20, the bounded shard dependency graph (`viewer/src/routes/shards/[id]/graph`, PR #38). Three designs still compete for the app:

- **Roadmap Phase 15** imagines seven inspection and governance surfaces built around the shard.
- **The annotator** imagines a reading surface built around the source text, with verdicts on each tag.
- **The approval queue** lives today as a generated HTML artifact (`scripts/build_approval_queue.py`) plus a local-only API (`api/routes/review.py` `/proposed-classes`).

All three surfaces ask a reviewer for a judgment on a machine claim. This plan treats them as one review loop with three **modes** over one shared design system.

### Requirements

- **R1. One app, three modes.** **Read** (annotated source text), **Inspect** (shard page, timeline, graph) and **Decide** (one review inbox). They share one shell, one token set and one component library.
- **R2. One review inbox.** Tag verdicts, proposed-class decisions, polysemy forks and contests share one queue. The queue groups items by kind, but every item uses one review card: claim, evidence span, machine rationale, actions and a note.
- **R3. Per-tag verdicts.** Each tag chip in Read mode takes **correct / weak / wrong** plus a note, and shows `extraction_path` and match score (brainstorm §6). Verdicts persist in a new `tag_verdicts` table. That table becomes the alias blocklist, the calibration data and the regression fixtures.
- **R4. Ledger-only approvals.** The proposed-class decisions the inbox makes write through the single approval ledger, so the inbox, `apply_approvals.py` and the API never disagree (single-approval-surface plan, R1).
- **R5. Shard page parity.** The Phase 15 roll-up exit criteria stand: 15-field inspector, signature badge, subtype and status chips, copy-as-citation, timeline under 500 ms on a 10-link chain, and a graph under 1 s on a 100-node fixture.
- **R6. Accessibility gate.** WCAG 2.1 AA, with an axe-core CI gate that blocks merges; keyboard paths for every verdict and decision; colour never the sole carrier of a verdict or branch.
- **R7. Novel-UX gate kept.** Polysemy fork and contest wizard still need 3–5 legal-practitioner think-aloud sessions with at least 80% task completion before GA (QUALITY-05).

### Scope Boundaries

- **In:** the design contract, the information architecture, the token set, the component inventory, sub-phase ordering, and static mockups of four screens.
- **Out:** viewer implementation; the `tag_verdicts` migration; the domain-prior manifest field; the SPARQL Explorer (Phase 16 owns it).
- **Unchanged:** the Phase 10 minter, Phase 11 SHACL and Phase 13 storage contracts.

## Planning Contract

### Key Technical Decisions

These follow best practice, so the plan settles them and leaves a receipt here:

- **KTD1. Drop the adapter-node swap.** Phase 3.5 reverted to adapter-static, so FastAPI serves the SPA, and the deploy depends on that. FastAPI also owns content negotiation (`Accept: text/turtle` and `application/ld+json` return RDF; `text/html` returns the SPA shell), so the app needs no SSR to meet UI-02. Re-open the swap only if a measured SEO or first-paint need appears.
- **KTD2. The annotator owns the design system.** The roadmap rule says whichever track lands first owns the design system. This plan settles the race on purpose: the token set and components start from the existing viewer tokens (`--gilt`, `--kernel-bg`, `--path-semantic`, branch colours) and extend them to cover Phase 15.
- **KTD3. One review-card component.** `ReviewCard` takes `{kind, claim, evidence[], rationale, actions[], note}`. Each kind supplies only its action set: tag verdict (correct/weak/wrong), proposal (approve/reject/merge/needs-work), fork (accept/edit/decline) and contest (arbiter/distinguo/aporetic). Distinct copy and distinct server code paths stay as UI-10 requires; only the visual frame is shared.
- **KTD4. Keyboard-first decisions.** `j`/`k` move between items, `1`–`4` pick an action, `n` focuses the note, `u` undoes inside the 15-minute window (UI-14). The existing `KeyboardShortcuts.svelte` hosts the map.
- **KTD5. Evidence spans are the anchor.** Read mode and every review card render source text through one `AnnotatedText` component: a port of folio-enrich's boundary-sweep `renderAnnotatedText` that stays safe with nested spans. A verdict always shows the span it judges.
- **KTD6. Retire the generated approval artifact after parity.** `build_approval_queue.py` stays until the inbox reaches feature parity, then becomes an offline export only.

### Information Architecture

```
Shell: corpus selector · mode switch [Read | Inspect | Decide (n)] · operator token · BYOK key
├── Read     /read/<corpus>/<doc>#<unit>        annotated text, tag chips, verdict popover, margin rail
├── Inspect  /shards/<hex16>                    15-field inspector, badges, citation, tabs:
│            ├── timeline                       supersession ribbon + as-of picker + bitemporal toggle
│            └── graph                          bounded 3-hop DAG (PR #38) + Tractarian breadcrumb
└── Decide   /inbox?kind=tag|proposal|fork|contest
             ├── ReviewCard list (grouped by kind, sorted by machine confidence ascending)
             └── wizards: polysemy fork · contest · retract/supersede/disambiguate
```

### Sub-phase Ordering (replaces Phase 14 + 15.* order)

1. **RUI-1 Design system:** tokens, type scale, `ReviewCard`, `AnnotatedText`, `Chip`, the axe CI gate. (Old Phase 14, minus adapter-node.)
2. **RUI-2 Read mode + tag verdicts:** the annotator plus the `tag_verdicts` table and its API.
3. **RUI-3 Decide inbox:** tag and proposal kinds on the ledger API; the generated artifact stays for an export path.
4. **RUI-4 Shard page:** 15.shard-page (UI-02..05) inside Inspect.
5. **RUI-5 Timeline and graph:** 15.supersession-timeline and 15.dependency-graph (graph route already merged in PR #38; needs adoption of the RUI-1 tokens).
6. **RUI-6 Wizards:** 15.polysemy-fork, 15.contest-wizard and 15.retract-supersede-disambiguation. Each needs its discussion artifact first and must pass the think-aloud gate.

Each RUI unit gets its own CE plan before build.

### Mockups

Static HTML with synthetic data, under `docs/design/review-ui/`:

- `01-read-mode.html`: annotated text with branch-coloured tag chips and an open verdict popover.
- `02-decide-inbox.html`: a grouped inbox with tag-verdict and proposal cards and keyboard hints.
- `03-shard-page.html`: the Inspect shard page, with the timeline ribbon and the graph tab.
- `04-polysemy-fork.html`: a polysemy fork wizard step, with an impact preview.

## Verification Contract

- **Mockups:** each renders in Playwright Chromium at 1440 and 390 px widths, with no horizontal scroll at 390 px; the inspected screenshots appear in the review artifact.
- **Plan:** each Phase 15 exit criterion and each brainstorm §6 bullet maps to an RUI unit (table below).

| Source requirement | RUI unit |
|---|---|
| UI-01, UI-18, UI-19, QUALITY-02 (Phase 14) | RUI-1 |
| Annotator span rendering, per-tag verdicts, `tag_verdicts` | RUI-2 |
| Approval queue (governance Stage C), single ledger | RUI-3 |
| UI-02, UI-03, UI-04, UI-05 | RUI-4 |
| UI-08, UI-09, UI-11, UI-12 | RUI-5 |
| UI-06, UI-07, UI-10, UI-13, UI-14, QUALITY-05 | RUI-6 |
| Domain-prior manifest field | RUI-2 (model addition, its own plan) |

## Open Questions

### For Damien (taste, on the review Decision Sheet)

1. **Look:** keep and extend the dark "illuminated manuscript" palette (ink ground, gilt accents) shown in the mockups, or move to a light, paper-like reading surface?
2. **Workflow:** one combined Decide inbox for all four kinds (recommended), or separate queues per kind?
3. **Build order:** start with Read mode and tag verdicts (RUI-2) before the shard page (RUI-4), as recommended, or start with the shard page?

### Resolved here (technical)

- Adapter-node: dropped (KTD1).
- Design-system ownership: the annotator, built from the existing tokens (KTD2).
- Approval writes: ledger only (KTD3, R4).
