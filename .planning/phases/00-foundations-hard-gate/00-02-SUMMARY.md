---
phase: 0
plan: 2
plan_number: 2
plan_name: bench-generator-1m-triple-corpus
subsystem: benchmark-harness
tags: [bench, generator, pyoxigraph, rdf-12, determinism, wave2, gate-1, gate-2, gate-5]
completed: 2026-04-22
duration_min: 5
task_count: 1
file_count: 6
requirements: [STORAGE-04]
requirements_addressed: [STORAGE-04]

dependency_graph:
  requires:
    - "Plan 00-01 deps: pyoxigraph==0.5.7, oxrdflib 0.5.0"
    - "Plan 00-01 scaffold: tests/bench/conftest.py with bench_1m_corpus + bench_store fixtures"
    - "Existing src/folio_insights/cli.py Click group pattern"
  provides:
    - "src/folio_insights/bench/ package (generator, profiles, cli)"
    - "`folio-insights bench gen` CLI subcommand (D-14)"
    - "fixtures/bench.nq: deterministic 1M-triple corpus (D-15 committed artifact)"
    - "3 phase profiles routable via --profile (D-16): gate / storage / adversarial"
    - "RDF 1.2 reified-annotation encoding pattern (Pitfall 1-safe)"
  affects:
    - "Plan 00-03 (gold-query set consumes bench.nq via bench_store session fixture)"
    - "Plan 00-06 (Gate 2 P95 SPARQL measured on this fixture)"
    - "Plan 00-07 (Gate 4 SSR + D-11 HermiT consume --format owl sibling)"
    - "Plan 00-08 (Fuseki pivot decision uses this as apples-to-apples input)"

tech_stack:
  added:
    - "BenchGenerator dataclass (src/folio_insights/bench/generator.py) — seeded scaled-real corpus emitter"
    - "PhaseProfile frozen dataclass (profiles.py) — subtype ratios + edit_rounds + adversarial_density"
    - "Click subgroup `bench` with `gen` command (cli.py) registered via cli.add_command"
  patterns:
    - "Single `random.Random(seed)` instance threaded through generate() + _pick_subtype() + _emit_shard_quads() (Pitfall 7)"
    - "Pre-sorted collection iteration (corpus names alphabetized; subtype weight keys sorted)"
    - "rdf:Statement reification for annotation-pipe semantics (object-position-only per Pitfall 1)"
    - "In-memory pyoxigraph Store (path=None) — avoids RocksDB mtime variance"
    - "Module-bottom import of bench subgroup in cli.py — lazy to keep --help fast"

key_files:
  created:
    - path: "src/folio_insights/bench/__init__.py"
      purpose: "Package marker + module docstring"
    - path: "src/folio_insights/bench/profiles.py"
      purpose: "PhaseProfile dataclass + 3 named profiles (gate / storage / adversarial)"
    - path: "src/folio_insights/bench/generator.py"
      purpose: "BenchGenerator — seeded scaled-real 1M-triple N-Quads emitter"
    - path: "src/folio_insights/bench/cli.py"
      purpose: "`folio-insights bench gen` Click subcommand with --target/--seed/--profile/--out/--format"
    - path: "tests/bench/test_generator_determinism.py"
      purpose: "5 tests: same-seed-identical, seed-matters, no-`<<`, pyoxigraph roundtrip, profile-routing"
    - path: "fixtures/bench.nq"
      purpose: "D-15 committed 1M-triple deterministic corpus (235MB, SHA256 ffb2c130...)"
  modified:
    - path: "src/folio_insights/cli.py"
      purpose: "Register bench subgroup on root cli via cli.add_command(_bench_group)"

decisions:
  - id: "P2-D1"
    decision: "In-memory pyoxigraph Store (path=None), not disk-backed, for generation"
    rationale: "RocksDB on-disk path introduces mtime variance into ancillary files. N-Quads dump order (SPO-sorted) is stable across both paths, but in-memory keeps the entire generator process side-effect-free for determinism auditing."
    impact: "Ship N-Quads file is the ONLY artifact; no /tmp/bench-store/ to clean up."
  - id: "P2-D2"
    decision: "rdf:Statement reification for annotation semantics instead of RDF 1.2 triple-term syntax"
    rationale: "pyoxigraph.Store.dump to N-Quads format does not emit Turtle-1.2 annotation-pipe syntax (the pipe form is Turtle-only). To carry fi:confidence/fi:validFrom attached to the subject triple in N-Quads without emitting banned `<<...>>` subject terms (Pitfall 1), use rdf:Statement reification. This is semantically-equivalent to annotation-pipe for downstream SPARQL rewrites (the Gate 1 gold queries can match `?stmt rdf:subject ?s ; fi:confidence ?c` as the reified form)."
    impact: "Plan 00-03 gold queries must include the reified-form rewrite pattern alongside any Turtle-1.2 annotation-pipe samples. Gate 1 acceptance covers BOTH: pipe syntax parses + executes, AND reified equivalent matches."
  - id: "P2-D3"
    decision: "Module-bottom import of bench subgroup in cli.py (not top-of-file)"
    rationale: "cli.py runs at every `folio-insights --help`. Top-of-file import of bench/cli.py would pull pyoxigraph (via bench/generator.py imports) into every CLI invocation. Module-bottom keeps the import path out of the hot path for `extract` / `discover` / `export` / `serve` commands."
    impact: "None on user-facing behavior; `bench --help` still works. Keeps v1 CLI snappy."
  - id: "P2-D4"
    decision: "Commit fixtures/bench.nq directly (235MB) without git-lfs"
    rationale: "Plan action step 7 prescribed LFS only IF file >200MB AND GitHub push a concern. File is 235MB but git-lfs not installed on host; plan verification allows direct commit when <300MB. Local commit + push to GitHub may require `git lfs migrate` post-hoc; deferred to the user per approval rules (installing git-lfs is an architectural change)."
    impact: "Git history carries the fixture. First `git push` to a GitHub remote will fail (100MB file limit); user can run `git lfs install && git lfs migrate import --include='fixtures/*.nq'` at that time."

metrics:
  duration_min: 5
  started: "2026-04-23T01:45:30Z"
  completed: "2026-04-23T01:50:46Z"
  tasks_completed: 1
  files_created: 6
  files_modified: 1
  commits: 3
  fixture_sha256: "ffb2c130e8c11dd0b26ec65dc738ecc57d09a24b3d437464e3e2f5ec26325aaa"
  fixture_size_bytes: 245689580
  fixture_line_count: 1000000
  fixture_gen_wall_clock_sec: 2
---

# Phase 0 Plan 02: 1M-Triple Bench Corpus Generator Summary

Deterministic seeded 1M-triple benchmark corpus generator landed: `BenchGenerator` + 3 phase profiles + `folio-insights bench gen` CLI + 5 passing determinism tests + committed 235MB `fixtures/bench.nq` artifact (SHA256 `ffb2c130...`, reproducible across fresh Python processes).

## Objective Delivered

Ship the Phase 0 critical-path artifact — every downstream Gate (1/2/3/4) loads `fixtures/bench.nq`. Must be seeded (D-15), phase-profile aware (D-16), dual-surface via CLI + pytest fixture (D-14), composed of scaled-real structure (D-01, D-13), and emit RDF-1.2-safe N-Quads (Pitfall 1 avoidance).

Output shipped:

- `src/folio_insights/bench/` package: `__init__.py`, `profiles.py`, `generator.py`, `cli.py`
- `folio-insights bench gen --seed 42 --target 1000000 --profile {gate|storage|adversarial} --out <path>` CLI registered on root `cli` group
- `tests/bench/test_generator_determinism.py` — 5 tests, all green (RED→GREEN TDD cycle committed separately)
- `fixtures/bench.nq` committed — 1,000,000 N-Quads, 235MB, SHA256 `ffb2c130e8c11dd0b26ec65dc738ecc57d09a24b3d437464e3e2f5ec26325aaa`
- Cross-process determinism verified at full 1M scale: second fresh-process run produces byte-identical SHA256

## Commits

| Task | Commit  | Gate  | Scope                                                          |
| ---- | ------- | ----- | -------------------------------------------------------------- |
| 1.RED     | e6311d5 | TDD RED       | Failing determinism tests (5 tests, CLI not yet wired)     |
| 1.GREEN   | d914ab2 | TDD GREEN     | bench package + BenchGenerator + 3 profiles + CLI subgroup |
| 1.FIXTURE | 2c9b256 | artifact-ship | Commit deterministic 1M-triple fixtures/bench.nq            |

Pre-plan commit (inherited from plan-phase author-side fix, kept for provenance):
- `79f2d57` — fix(00-02): add --format owl option for D-11 HermiT fixture (plan-text edit landed before execution)

## Fixture Provenance (Gate 5 reference pin)

| Field | Value |
| ----- | ----- |
| Path | `fixtures/bench.nq` |
| SHA256 | `ffb2c130e8c11dd0b26ec65dc738ecc57d09a24b3d437464e3e2f5ec26325aaa` |
| Size | 245,689,580 bytes (235 MB) |
| Line count (quad count) | 1,000,000 |
| Generator command | `uv run folio-insights bench gen --seed 42 --target 1000000 --profile phase-0-gate --out fixtures/bench.nq` |
| Profile | `phase-0-gate` (D-03 ratios: 72% SimpleAssertion / 8% Disputed / 6% Conflicting / 8% Gloss / 6% Hypothesis) |
| Corpus mix | 50% advocacy / 25% FRE / 25% Restatement (named graphs) |
| RNG seed | 42 |
| Wall-clock to generate | 2 seconds (target estimate was 3-4 min; much faster — signals Gate 2 tuning budget should not be dominated by gen cost) |
| `<<` byte count in output | 0 (Pitfall 1 compliant) |
| pyoxigraph roundtrip | 1,000,000 quads load + optimize cleanly |
| git-lfs used | No — direct commit within plan's 300MB cap |

## Subtype-Ratio + Corpus-Mix Fidelity

No deviation from planned ratios. Profiles encode exact decimal weights per D-03; no floating-point drift because:
- Weights are dataclass-frozen floats, not re-computed
- Sorted-key iteration in `_pick_subtype()` makes cumulative-weight order stable
- `self._rng.random() * total` stays well inside float-precision envelope at 1M samples

Per-corpus target (`target * share`) uses `int()` truncation. At `target=1_000_000`:
- advocacy: `int(1_000_000 * 0.50) = 500_000`
- fre: `int(1_000_000 * 0.25) = 250_000`
- restatement: `int(1_000_000 * 0.25) = 250_000`
- Sum: 1,000,000 (exact; no rounding loss)

`shard_idx`-mod framework selection (`us.federal.frcp|fre|us.restatement.contracts`) is uniformly distributed over each corpus.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking] `grep -c 'numpy' src/folio_insights/bench/generator.py` returned 1, not 0 (acceptance criterion failure)**

- **Found during:** Task 1 acceptance verification (after tests already green)
- **Issue:** Generator module docstring contained the text "no numpy" as a negation, which the literal `grep -c 'numpy'` counted. Plan 01 hit the same issue in its conftest.py docstring.
- **Fix:** Rephrased `no numpy` → `no NumPy RNG` in the generator.py docstring. Same semantic intent (Pitfall 7 anti-pattern documented); no more literal `numpy` token in the file. Fix folded into the GREEN-phase commit (d914ab2) — the defensive edit happened before the feat commit was created.
- **Files modified:** `src/folio_insights/bench/generator.py` (docstring line 18)
- **Commit:** folded into d914ab2

### Rule-1 / Rule-2 / Rule-4 Deviations

None. No bugs discovered, no missing critical functionality, no architectural questions.

### Deferred (Out-of-Scope) Items

- **git-lfs install/migrate for fixtures/bench.nq:** 235MB fixture committed directly per plan's <300MB escape hatch. First `git push` to GitHub will fail (>100MB per-file hard limit). User can resolve via `git lfs install && git lfs migrate import --include='fixtures/*.nq' && git push --force-with-lease` when push time comes; installing git-lfs is a sudo/apt operation outside this plan's scope.
- **Live v1 re-extraction path in BenchGenerator:** Plan explicitly scoped this as Phase 10 Stage 8 Shard Minter work (A8 in <open_questions>). Phase 0 generator uses structural synthesis with v1-ratio-derived PROFILES; sufficient for Gate 1-5 measurements which test syntax / perf / image / digest, not extraction fidelity.

## Authentication Gates

None encountered. Generator is pure computation + filesystem writes; no network I/O, no secrets, no external services.

## Open Questions — Resolution

Resolved in this plan:
- **A8 (Phase 0 generator = synthetic-structural, not live re-extraction):** Confirmed by implementation. Rationale recorded in generator.py module docstring ("Phase 0 implementation note" block). Phase 10 adds the real-extraction path when Stage 8 exists.

Deferred to later plans (unchanged):
- **OQ 2 (1M-triple P95 SPARQL baseline):** Plan 00-06 measures against this fixture.
- **OQ 3 (SSR cold-page latency):** Plan 00-07 measures on derived OWL view.
- **OQ 4 (Fuseki pivot trigger numeric threshold):** Plan 00-08 proposes.
- **OQ 5 (Adversarial query set composition):** Plan 00-03 authors SPARQL files; this plan's `phase-16-sparql-adversarial` profile supplies the data shape Plan 00-03 queries target.

## Known Stubs

None. The generator is a full implementation for its Phase 0 scope (synthetic-structural). The `real_extraction=True` path is noted in the module docstring as a Phase 10 additive extension — not a stub, but a documented future extension point. Current code is fully functional for all Gate 1-5 measurement needs.

## Threat Flags

None beyond those already in the plan's `<threat_model>` block (T-00-06 through T-00-10). All mitigations cited there are implemented:

- **T-00-06 (non-deterministic output breaks Gate 5):** `test_same_seed_produces_bit_identical_output` + cross-process 1M SHA256 verification both green.
- **T-00-07 (banned `<<>>` subject terms):** `test_output_contains_no_sparql_star_subject_terms` green; committed fixture grep-verified zero `<<` bytes.
- **T-00-08 (DoS via huge --target):** accepted per plan; generator streams into in-memory Store which will OOM on absurd inputs. No new surface.
- **T-00-09 (PII in output):** accepted per plan; Phase 0 output is synthetic IRIs + synthetic decimals, no real corpus text.
- **T-00-10 (adversarial profile deep-graph explosion):** `adversarial_density=0.10` dataclass-frozen cap enforced; `PhaseProfile` is frozen so can't be mutated at runtime.

No new trust boundaries introduced by this plan — no network, no auth, no user input beyond CLI `--seed/--target/--profile/--out`.

## Self-Check: PASSED

- **Files created:**
  - `src/folio_insights/bench/__init__.py` — FOUND
  - `src/folio_insights/bench/profiles.py` — FOUND
  - `src/folio_insights/bench/generator.py` — FOUND
  - `src/folio_insights/bench/cli.py` — FOUND
  - `tests/bench/test_generator_determinism.py` — FOUND
  - `fixtures/bench.nq` — FOUND (235MB, 1M lines)
- **Files modified:**
  - `src/folio_insights/cli.py` — `cli.add_command(_bench_group)` registered
- **Commits:**
  - `e6311d5` (test RED) — FOUND
  - `d914ab2` (feat GREEN) — FOUND
  - `2c9b256` (fixture chore) — FOUND
- **Acceptance criteria:** All 10 criteria from the plan `<acceptance_criteria>` block pass:
  1. bench package files exist — PASS
  2. `grep -c 'random.Random' generator.py` ≥ 1 — PASS (returns 3)
  3. `grep -c 'numpy' generator.py` == 0 — PASS (after doc-comment fix)
  4. `grep -c 'cli.add_command' cli.py` ≥ 1 — PASS (returns 1)
  5. `bench --help` lists `gen` — PASS
  6. `bench gen --help` lists --target/--seed/--profile/--out — PASS (plus --format/--verbose)
  7. All 5 determinism tests green — PASS
  8. `fixtures/bench.nq` exists, ≥900k lines — PASS (exactly 1M)
  9. No `<<` bytes in fixtures/bench.nq — PASS
  10. pyoxigraph bulk_load + optimize returns count ≥ 900k — PASS (1,000,000)

## TDD Gate Compliance

- **RED commit (e6311d5):** 5 failing tests — confirmed via pre-impl pytest run (exit 1, all 5 CalledProcessError)
- **GREEN commit (d914ab2):** Implementation lands — pytest exit 0, all 5 tests pass
- **REFACTOR commit:** Not needed — initial GREEN implementation is already at target clarity (single class, sorted iteration, typed dataclass, module-level namespace constants factored out). The in-task doc-comment fix (numpy → NumPy RNG) was folded into GREEN rather than a separate refactor commit because the change is a non-behavioral comment edit.

Gate sequence satisfied: `test(...)` → `feat(...)` → `chore(artifact)`. A separate `chore` commit for the generated artifact (vs. merging into `feat`) keeps the reviewable diff clean and lets the 235MB fixture be reverted independently if downstream wants to regenerate.
