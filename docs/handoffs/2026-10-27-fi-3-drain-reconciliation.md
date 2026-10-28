# fi-3 drain reconciliation: controller handoff

**Status: partial; final reconciliation and branch closure remain blocked.**
The build ran on `drawdown/fi-3` from the committed
[fi-3 plan](../plans/2026-10-27-2141-refactor-fi3-drain-reconciliation-plan.md).
The [evidence ledger](../plans/evidence/fi-3-drain-reconciliation.md) records the
exact revisions, historical branch dispositions, source/test map and checks.

## Delivered locally

- Accounted for seven known historical branch names without presenting them as
  the complete current inventory. Verified four recorded merge parents and
  eight supplemental landings/replacements against both build entry and local
  `master`.
- Inspected shared-path integration differences in the wave and ingest merges.
  No demonstrated missing production change justified a port. The old active
  hierarchy is superseded by the measured-propositions flat-reference contract.
- Created the evidence ledger and this handoff, and appended a coordination
  note. Existing plans, implementation, viewer, tests and refs are preserved.

The entry revision is `ee97bfdffe0de158b7746e70be58727c2d5d3bcf` and the local
comparison target is `269171e47bdfc20fa574fa9eeeff730b91919b91`. Their runtime and
manifest trees match. The target's session/planning metadata commit was not
imported into this branch. The branch's build commit contains only the three
documents listed above; the earlier plan commit remains separate.

## Verification limits

The offline frozen dependency install failed because the empty cache lacks
locked Torch. The quick suite then stopped before collection because pytest
was unavailable. The exclusion scanner stopped at a missing `jcs` import.
**No repository tests executed; no green-suite or public-scan claim is made.**
The ledger includes exact commands, exit results and compatible-Python details.
No production behavior changed, so no new regression test or screenshot was
required. Document validation is limited to local evidence consistency and
preservation checks.

## Required controller inputs

1. Chief campaign Goal Capsule and the cited campaign rules. The chief
   repository is absent in this sandbox.
2. Complete captured source inventory with current `feat/drain-*` tips, Git
   objects, authoritative target and external PR state. None of the current
   source refs was supplied. Include dispositions for historical names omitted
   from that inventory.
3. Existing locked dependencies and required sibling/model/JRE inputs, plus
   host execution where the sandbox denies sockets. Re-run the checks recorded
   in the ledger before treating runtime verification as satisfied.

These are controller preparation tasks, not requests for Damien's time,
credentials, a login, spend or a product decision. **There are no branch-closure
candidates from this partial receipt.** Once inputs arrive, compare only the
unresolved source tails and revalidate the target; do not replay retired
hierarchy or start unrelated mandate items.

## Delivery state

The local documentary result is committed for controller pickup. Nothing has
been pushed, merged, deployed or externally closed by this lane. No remote was
added. The controller must scan, publish and obtain the campaign reviews.

LFG stops at `ce-work` with `status: blocked`, because the plan's full inventory
and verification prerequisites are absent. The downstream simplification,
code-review and shipping stages did not run; no DONE promise is issued. No
settled decision was invalidated, and no held schema/data/service change was
introduced.
