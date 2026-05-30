---
rfc: 0
title: Template — Replace With Your RFC Title
status: draft
authors:
  - did:key:z6Mk... (replace with your DID — see `folio-insights did generate`)
created: 2026-05-30
---

<!--
  This template is exempt from `folio_insights.rfc.lint` (skipped by filename).
  Phase 18 wires the pre-commit hook config (CONTRIBUTING.md / GOVERNANCE.md prose).
  D-02: Phase 7 owns ONLY this fixture; contributor-facing prose lives in Phase 18.
-->

## Summary

One-paragraph summary of the proposal. What changes? Why now?

## Motivation

What problem does this solve? Cite the upstream pain point — link to issues, prior
discussion, or shards. Why is the status quo not good enough?

## Detailed Design

The substance. Pseudocode, schema, shape definitions, SPARQL queries, decision
trees — whatever the reviewer needs to understand the change end-to-end.

Subsections to consider:

- New / changed shard subtypes
- New / changed SHACL shapes
- New SignedAction members
- Migration / backfill plan
- Backwards-compatibility story

## Drawbacks

Why might we NOT do this? What's the cost — to the substrate, to contributors,
to operators, to downstream consumers?

## Alternatives Considered

What other approaches did you evaluate? Why did you reject each one? Reviewers
will ask anyway — preempting saves a round-trip.

## Unresolved Questions

What's still open? Tag each with a tracking issue or follow-up RFC number.

## Prior Art

What other projects, papers, or specs informed this design? Cite W3C drafts,
SEP/PEP/JEP precedents, decentralized-identity literature, etc.

---

## Lifecycle Lint Cheat Sheet

This RFC's `status:` field walks the D-22 DAG:

    draft → discussion → {accepted, rejected} → implemented

Both `rejected` and `implemented` are **terminal**. Every status change
MUST carry either:

- A `Reason: <one-line explanation>` trailer in the commit message, **OR**
- A `status_change_reason: <one-line explanation>` frontmatter line.

The RFC linter (`python -m folio_insights.rfc.lint .planning/rfcs/`)
refuses any status change without one of those rationales.
