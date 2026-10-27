# Handoff: measured propositions and workbench, Codex drain (2026-10-26, refreshed)

## State
- **Plan:** `docs/plans/2026-10-26-0716-feat-measured-propositions-and-workbench-plan.md` (PRs #50 and #51). KTD15 routes Codex builds offline, assigns live runs and corpus fetches to the orchestrator, and puts output-changing units behind a live held-out gate. KTD2 defines pooled tag-recall gold.
- **Merged (20 of 60):** U5 coordinator (#74), U38b atomic list evidence (#75), and U41 ancestor branches (#76) are added to the units below.

  | Unit | Scope | PR |
  |---|---|---|
  | U1 | gold | #55 |
  | U2 | scorer | #58 |
  | U3 | annotations | #57 |
  | U4 | judges | #61, plus live-auth fix #63 |
  | U10 | corpus tooling | #64 |
  | U12 | federal statutes/regs tuning gold; unsealed; live cross-check pending | #72 |
  | U33 | proposition model | #59 |
  | U34 | atomic identity | #54 |
  | U35 | SHACL | #60 |
  | U36 | hierarchy retirement | #56 |
  | U37 | projection | #67 |
  | U38 | atomic extraction, inactive behind `FOLIO_INSIGHTS_ATOMIC_EXTRACTION` | #69 |
  | U39 | full-tag minting, atomic-gated | #71 |
  | U51 | workbench foundation | #52 |
  | U60 | dedup | #62 |

  Judge-test hardening landed in #68. Worker-report ignore landed in #65.
- **Judges proven live.** On the host, Codex and Claude both judged a 2-item synthetic packet correctly over subscription CLIs. `~/.codex/auth.json` was left untouched. Codex takes about 200 s per call against Claude's 13 s, so U5 must batch.
- **Running at handoff:**
  - **Codex workers:** U6 (held-out gate) and U5b (bind checkpoints to the annotation-store identity).
  - **Verification:** U40 (two-phase mint links) is committed on `feat/mp-u40`; its host verify job was queued in the old session, so rerun the verify step.
- **Tracked follow-ups (P2; atomic path, inactive):**
  - **U38b:** resolve canonical offsets before locating list occurrences when blank-line separators shift structural offsets (`boundary_detection.py`).
  - **U41:** recognize the excluded "ZZZ - SANDBOX" root during ancestor traversal so its descendants never enter the candidate catalog (`folio_ontology.py`).
- **Next units:**
  - **After U5:** U6 (gate), then U7, then U8, then U9 (a live synthetic baseline run by the orchestrator).
  - **Unblocked now:** U42 (deterministic deontic).
  - **After U40:** U50 (dropped candidates).
- **Receipts path:** measurement receipts go to `data/measurement/receipts/`, never `docs/evidence/`, which `scripts/check_exclusions.py` treats as an excluded prefix. Plan KTD1 was updated to match.
- **Corpus:** the federal statutes/regs cell is collected and verified under the gitignored `output/measurement/corpus/federal/statutes-regulations/`. Seal it with the `corpus seal` CLI after the live judge cross-check. The eCFR policy entry is unusable because robots.txt disallows its text API; use govinfo `/content/`. Fetch briefs must set the User-Agent to the repo URL.

## How to run the drain
- **Workers:** one Codex worker per unit, launched with `agents/worker-wrapper.sh` from a `~/worktrees/folio-mp-<unit>` worktree on `feat/mp-<unit>`.
- **Caps:** at most 3 workers at once, admitted at load below 6 with more than 16 GiB free (relaxed from 4 because other sessions hold load at about 5); host verify suites likewise run at load below 6. Count real wrapper processes only: lines starting `bash …/worker-wrapper.sh folio-mp`. Launcher shells must not count.
- **Merge rule:** rebase on master, run the host quick suite (`-m "not gate5 and not slow and not integration"`, plus `generate_shapes.py --check` for shape units), and run `codex review --base <sha>`.
  - **Defects:** fix P1 or P2 defects via a Codex follow-up task (test first).
  - **Merge:** merge with a PR, then delete the worktree and branch.
- **Sandbox notes:** Codex workers can't reach the network or bind ports, and their asyncio self-pipe is blocked; `/tmp/folio-sandbox-support/sitecustomize.py` works around that. Host suites are authoritative. Under heavy box load, `tests/bench/test_phase9_rollup.py` can time out at 180 s; rerun it at low load before treating it as real.
- **Data rule:** gold and data files never serialize excerpt-key values (`quote`, `snippet`, and similar), because the exclusion scanner forbids them.

## Waiting on Damien (ask `folio-insights-2026-10-26-1328-corpus-token-and-gaps`)
- **q1:** a CourtListener token (hard block). The paste-safe command is in the session chat.
- **q2:** a gap-cell policy for MN, TX, and NY briefs and state pleadings.
- **Also waiting:** his own know-how materials folder, and per-genre anchor verification after the conference.
- **Chief noise:** Chief re-notes q1 every few minutes; each note gets a one-line no-op trail receipt.
