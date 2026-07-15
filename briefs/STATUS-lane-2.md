# STATUS — lane-2 (folio-matching proving run)

## 2026-07-15 · session 7 — Ch03 generalization confirmation

**Question answered:** Does the v7 precision fix (tuned on Ch02) GENERALIZE to a chapter it was not tuned on?
**Answer: YES.** On Ch03 (`16-ch03-trial-procedures-and-moti-final7th`, source hash `ffbc01e7…`, identical v5/v7), the same failure classes collapse on unseen source while recall rises.

Fixed run: `output/uat_ta_ch03_v7` (same branch/config as Ch02 v7 — folio-insights `feat/wire-decompose-tagger`, folio-matching `fix/ch02-precision-resolution` @ 44c1ca7/e5bb791). Baseline: `output/uat_ta_ch03_v5` (2026-07-15 extraction; 865 classes fed governance registry).

**Ch03 delta (v5 baseline → v7 fixed):**
- Non-heading place mis-maps: 3 → **0**
- Heading place-propagation: 283 tags / 30 countries → **0 / 0**
- Agency-homonym mis-maps: 15 → **3** (residual = "appeals"→IRS Office of Appeals entity_ruler alt-label — identical residual to Ch02 v7)
- Slovenia propagation (units): 5 → **0**
- Action→Auction blocklist hits: 0 → 0 · Metadata units tagged: 0 → 0
- Resolved-IRI tags (recall): 2418 → **3273** (+855)
- Proposed-class per unit: 3.01 → **2.29** (abs 1476 → 1902; proposed_classes.json 1152 → 1431)
- Recoveries preserved/grew: Jury 38→61, Witness 48→77, Hearing 40→45, Objection 13→15, Verdict 10→11
- Units/tags: 491/3894 → 830/5175 · Calls/cost: 1984/$0.121 → 3491/**$0.2023** (cap $0.30)

**Hand-verification (generalization evidence, not just counts):**
- 10 suppressed tags → **10/10 genuinely wrong** (8 countries with 0 source occurrences via heading propagation; "AI"→Anguilla where AI=artificial intelligence, 13 hits none about the country; "state"→U.S. Dept. of State, 34 common-word hits).
- 10 new v7-only mappings → **8/10 correct** (ADR, Additur, Interrogatories, Disability, Vague&Ambiguous Objection, Trial Events, Court-Appointed Expert, Counter-Claimant; 1 weak-defensible advice→Advisory Service; 1 wrong take→Seizure, an entity_ruler generic-word fragment orthogonal to the fix).
- Recall guard: concepts dropped at pair level (cross-examination, direct examination, motions in limine, ALJ, opening statements, judgments, verdicts, jurors) still resolve in v7 by IRI — re-worded, not lost.

**Verdict:** GENERALIZES — the fix did not memorize Ch02. The folio-enrich migration hold can lift.

**Deliverables:**
- Evidence pack "Ch03 generalization" section appended → `docs/evidence/books/folio-matching-proving-run/pack.html` + `ch03_data.json` + `manifest.json`.
- Artifact redeployed to same URL: https://claude.ai/code/artifact/09b62147-9c83-481f-839e-51e6d7eb09d9 (favicon 🎯 — original not recorded in repo; flagged for correction if it differed).
- No code changes (no crash-grade defect found). No migration/annotator/rubric work.

STATE: done
