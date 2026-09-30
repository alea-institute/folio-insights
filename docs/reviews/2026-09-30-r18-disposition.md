# R18: folio-insights v2.0 confirmed review disposition

> **Confirmed 2026-09-30.** Damien directed: “confirm R18 as drafted; Phase 13 after R18; governance pipeline after Phase 13.” This is the local folio-insights record of that answer, supplied in the U12 execution task. It does not claim the upstream PR merged or the upstream draft was updated.

Source: `alea-institute/folio-propositions`, `docs/review-disposition-v2.0.md`, local draft prepared 2026-09-27. Source SHA-256: `618372f52f6200e97d80290d95a964abefbeb7432f62ea1b0cdcd395e5e9ef6d`. Vocabulary ownership remains upstream. The orchestrator must synchronize the confirmation there; this worker may only edit folio-insights.

## Review record

- Packet version: `folio-propositions` v0.3.0 (schema version 3), git `cb1e6a7`
- Review date: 2026-09-30 (draft prepared 2026-09-27)
- Record completed by: Codex (AI, delegated) — records Damien Riehl’s supplied confirmation; original recommendations drafted by Claude Opus 5.5
- Attendees: Damien Riehl — reviewer (self-review, per his 2026-08-17 choice to self-review and stay git-pinned)
- Source packet: `folio-propositions/docs/rationale.md`, `folio-propositions/docs/shard-mapping.md`, `folio-propositions/docs/exit-record-phase-a.md`, `folio-propositions/docs/migration-0.3.0.md`, `folio-propositions/docs/cycle-1-palsgraf-learnings.md`

## Disposition by packet element group

| Packet element group | Disposition (`accepted` / `revised` / `rejected`) | Revision or rejection detail | Decision owner |
|---|---|---|---|
| Identity and reference boundary | `accepted` | None. Freeze proposition/document identifiers, document binding, `schema_version` stamps, span mechanics, and reference-container positions, per the rationale's "Adopt into frozen storage now". | Damien Riehl |
| Proposition ledger fields and null semantics | `accepted` | None now. `null` stays data, not absence. The polarity field and per-opinion validator stance stay deferred to more cycle evidence (Damien, 2026-08-17). | Damien Riehl |
| Working proposition taxonomy | `revised` (confirmed 2026-08-17) | Already decided: ADOPT WITH REVISIONS as `WORKING_TAXONOMY` v0.3.0 (three promotions, dissent modeled via asserter + validator, one merge, definitional held as tag, four FOLIO-canonical renames). Stays revisable between ladder cycles. | Damien Riehl |
| Actor and adjudication vocabularies | `accepted` | Accepted as revisable: `ActorRole` and `AdjudicationMode` change only between cycles, with a schema version and migration. | Damien Riehl |
| Disposition vocabulary | `accepted` | Accepted as revisable, same between-cycle rule. | Damien Riehl |
| Citation-edge vocabulary | `accepted` | Accepted as revisable. Unexercised in cycle 1; target it in the next ladder opinions. | Damien Riehl |
| Shape descriptors and application-level composites | `accepted` | The five folio-insights shard subtypes become configurations or composites of the shared model, as marked in `shard-mapping.md`, not a second ontology. | Damien Riehl |
| Axiom lifecycle status | `accepted` | Accepted as design-only; `AxiomStatus` stays on the same `Proposition` identity. Exercise it when folio-insights promotes its first axiom. | Damien Riehl |
| Interchange record and migration policy | `accepted` | None. Versioned revisions with `migrate_record` between cycles, as shipped for v1→v2→v3. | Damien Riehl |
| Annotation-testing and Phase A evidence plan | `revised` | Continue the gold-corpus ladder (4–5 more opinions: federal appellate, federal district, state intermediate appellate, state trial, one post-1980). Before cycle 1 is called human-validated gold, Damien reviews the AI-annotated session or adds a human second opinion. Use designate-before-render for blind segments. | Damien Riehl |

## Adopted-vocabulary ownership

- Owning person or team: Damien Riehl (annotator-taxonomist)
- Repository/system of record: `alea-institute/folio-propositions`
- Change-approval authority: Damien Riehl, between annotation cycles only
- Versioning and migration responsibility: the folio-propositions maintainer, shipping `schema_version` bumps with `migrate_record` migrations

## Next handoff

| Who | What | Recipient | Due date | Completion evidence |
|---|---|---|---|---|
| folio-insights agent | Replace the PRD §6–§7 HOLD banner with a pointer to this confirmed record | folio-insights `PRD-v2.0-draft-2.md` | Confirmation recorded locally on 2026-09-30 | Banner commit on folio-insights `master` |
| folio-insights agent | Plan the shard-envelope migration (U17) sized by the `accepted` / `revised` groups | folio-insights `docs/plans/` | After separate U17 scope dispatch; not authorized by the planning-only storage answer | A ce-plan doc for U17 |
| Damien Riehl | Pick the next gold-ladder opinion | folio-enrich gold corpus | Next annotation cycle | Cycle-2 learnings record |

## Open risks carried forward

| Risk | Impact | Mitigation or next test | Owner | Review date |
|---|---|---|---|---|
| Extraction recall (lexicon-only proxy 0.077) | Phase B's zero-LLM stage misses most assertions | Add assertion-level patterns; benchmark on the cycle-1 gold set | Phase B planner | Phase B brainstorm |
| Polarity not representable | Negation-blind extraction produces inverted candidates | Deferred to more cycle evidence (Damien, 2026-08-17) | Damien Riehl | After cycle 2 |
| Per-opinion validation stance | Majority/dissent stances collapse to the institutional outcome | Revisit if folio-insights needs `disputed_proposition` threads | Damien Riehl | After cycle 2 |
| Cycle 1 is AI-annotated | Packet could be overstated as human-validated gold | Human review or second opinion before the gold label | Damien Riehl | Before Phase B |
| Unexercised schema surface | Judicial notice, disputatio, axiom lifecycle, citation edges on hand-adds, interchange untested | Target them in the remaining ladder opinions | Damien Riehl | Each ladder cycle |

## Final confirmation

- Overall packet disposition: `revised` — every group accepted except the taxonomy, already revised, and the evidence plan
- Review chair confirmation: Damien Riehl — confirmed as drafted, 2026-09-30
- Vocabulary owner confirmation: Damien Riehl — confirmed as drafted, 2026-09-30
- Notes: Draft prepared by the folio-insights GSD-to-CE migration (plan U5). Confirmation is supplied by the 2026-09-30 backlog-sheet answer quoted above.
