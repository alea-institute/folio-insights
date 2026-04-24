---
status: complete
phase: 01-polysemy-distinguo-spike
source:
  - 01-SUMMARY.md
  - 01-01-SUMMARY.md
  - 01-02-SUMMARY.md
  - 01-03-SUMMARY.md
  - 01-04-SUMMARY.md
  - 01-05-SUMMARY.md
  - 01-06-SUMMARY.md
started: 2026-04-24T18:28:16Z
updated: 2026-04-24T18:34:00Z
---

## Current Test

[testing complete]

## Tests

### 1. CLI subgroup registers and shows help
expected: `folio-insights polysemy --help` lists subcommands `detect`, `review`, `audit`.
result: pass
observed: Help output lists all three subcommands (`audit`, `detect`, `review`) under the "Commands" heading.

### 2. Detector runs end-to-end on fixture corpus
expected: |
  Detector prints verdict with `decision=coincidence`, `matched_rules=["R1-no-conflict"]`, `evidence_score≈0.6728`.
result: pass
observed: |
  Verdict table showed decision=coincidence, kind=rule, matched_rules=R1-no-conflict, evidence_score=0.673.
  (Exact value 0.6728161573410034 visible in disposition record from Test 4.)

### 3. Review CLI enforces keystroke gate (PRINCIPLE-06)
expected: |
  `review --help` lists `--fixtures`, `--term`, `--dispositions-path`, `--llm-provider` only.
  No `--auto`, `--yes`, `--batch`, `--accept-all`, `--no-prompt`, `--force`.
result: pass
observed: |
  Help lists exactly the four expected flags plus `--help`. No bypass flag present.
  Docstring also states: "PRINCIPLE-06 (no auto-apply) is enforced by the CliRunner test suite: no flag exists to skip the rich.prompt.Prompt.ask() gate."

### 4. Review path accepts disposition with keystroke input
expected: |
  Stdin `"accept\n\n"` produces a JSON line with schema_version="1", proposed_fork, detector_verdict (dict), decision="accept", rationale="", reviewer_did, reviewed_at_iso.
result: pass
observed: |
  One line written to the dispositions file. All required fields present:
  - schema_version="1"
  - proposed_fork (object with cluster_id, term, frameworks, etc.)
  - detector_verdict (object with kind, decision, rule_confidence, matched_rules, evidence_score)
  - decision="accept"
  - rationale=""
  - reviewer_did="did:key:z6Mkh..."
  - reviewed_at_iso="2026-04-24T18:33:16.827305+00:00"
  Also observed: signature=null, audit_label=null, audit_agreement=null (populated later by audit pass).

### 5. Audit subcommand prints disposition summary
expected: `audit` prints `Total: 22`, breakdown `14 accept / 5 reject / 3 modify`.
result: pass
observed: Table "Dispositions summary (22 total)" with Decision/Count rows accept=14, reject=5, modify=3.

### 6. Audit emits disagreements-only LLM report (D-4 lock)
expected: |
  `audit --emit-disagreements --report-path ... --llm-provider claude-haiku-4-5` writes a Markdown table with exactly 2 disagreement rows (Lampleigh accept→uncertain; FRE-403 reject→polysemy). 20 agreements silently counted.
result: pass
verification_method: committed-artifact
observed: |
  Inspected `.planning/phases/01-polysemy-distinguo-spike/fp-labeling-audit.md` (committed):
  - Header states Total=22, Agreements=20, Disagreements=2 ✓
  - Disagreements table has exactly 2 rows ✓
    - Row 1: fi:PrototypeCluster_3824502c `consideration`, reviewer=accept, LLM=uncertain (Lampleigh/past-consideration) ✓
    - Row 2: fi:PrototypeCluster_3824502c `consideration`, reviewer=reject, LLM=polysemy (FRE 403) ✓
  - D-4 lock honored (agreements not enumerated) ✓

  Caveat (already disclosed in the artifact): the committed report was produced by a deterministic mock harness (scripts/run_llm_audit_harness.py) so the phase can close offline. The artifact itself documents this and lists a live `--llm-provider claude-haiku-4-5` re-run as post-phase reviewer sign-off item. Live API re-run NOT executed here (cost/auth side effect); report shape is verified.

### 7. False-positive rate gates against Wilson CI lower bound
expected: |
  `compute_fp_rate(...)` returns dict with fp_rate≈0.0909, ci_lower≈0.0253, ci_upper≈0.2782. Gate: ci_lower ≤ 0.10 → PASS.
result: pass
observed: |
  total=22, false_positives=2,
  fp_rate=0.09090909090909091,
  ci_lower=0.025294896282837792,
  ci_upper=0.2781538065838578,
  kappa=0.4329896907216496 (reported as signal per PRINCIPLE-06 caveat).
  Gate: 0.0253 ≤ 0.10 → PASS.

  Minor observation (not a gap): `compute_fp_rate` signature is `dispositions_path: pathlib.Path`, and `read_dispositions` calls `path.open(...)` directly. Passing a `str` raises `AttributeError: 'str' object has no attribute 'open'`. Test description implied a string literal; in practice callers must wrap in `Path(...)`. Consider `Path(dispositions_path)` coercion at entry if ergonomic string calls are desired — but this is a stylistic improvement, not a correctness bug. The signature matches the contract.

## Summary

total: 7
passed: 7
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

[none — all tests pass]

## Human-Needed Gates (from 01-VERIFICATION.md)

These are intentional design gates from the verifier. They were NOT automatically run here because they require human judgment or external API cost. Surfaced for awareness and phase-level sign-off:

1. **Live keystroke-gate UX acceptance** — CliRunner + stdin-piped test (Test 4 above) confirm the happy path. A reviewer should still run `folio-insights polysemy review` interactively in a real TTY and confirm: (a) invalid choice triggers re-prompt with no default, (b) no way to skip the keystroke gate. [Manual TTY check]

2. **FP labeling reconciliation (D-4 lock)** — Two FP-signal records (FRE-403, FRE-702) have empty rationales in `dispositions.jsonl`. The disagreements-only audit report calls these out. Reviewer must either retrofit 1-sentence reject-reasons per D-4, or confirm empty. Reviewer must also confirm/revise the 2 **draft** Final Labels in `fp-labeling-audit.md` (rows marked "**polysemy (draft)**" and "**homonymy (draft)**"). [Policy + curation decision]

3. **Per-framework threshold policy decision (§4)** — `01-SUMMARY.md §4` authors a draft threshold recommendation with Options A/B/C. Reviewer must pick one and record it as architectural input to Phase 9.P6. [Policy decision]

4. **(Optional) Live LLM audit re-run** — Test 6 was verified against the committed mock-harness artifact. A post-phase `folio-insights polysemy audit --emit-disagreements --llm-provider claude-haiku-4-5` call against the real Anthropic API can confirm the disagreement pattern is stable with a non-mocked LLM. Not a phase gate — documented as reviewer sign-off item inside the artifact itself. [Optional live validation]
