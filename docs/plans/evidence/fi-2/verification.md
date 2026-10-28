# FI-2 build prerequisite receipt — 2026-10-27

**Status: blocked before implementation.** No detector result was measured, no
holdout was authored or exposed, and no implementation unit is complete. This
receipt does not establish an R9 pass, a regression failure, or a change in the
historical measurements.

## Starting state

- Branch: `drawdown/fi-2`; starting commit: `de561c6`.
- Work source: `docs/plans/2026-10-27-2057-fix-fi-2-polysemy-gate-plan.md`.
- The working tree was clean. No repository or ancestor `AGENTS.md` or
  `CLAUDE.md` was present; the controller's supplied lane instructions apply.
- The chief repository and its campaign plan were unavailable in this clone,
  as recorded during planning. The supplied campaign rules and the three named
  repository handoffs/plans were read.
- No Git remote is configured. No remote, login, or credential discovery was
  attempted.
- Static inspection confirms the existing large-distance Rule 3 and the
  unchanged legacy fixture with 82 cases: 29 polysemy, 19 homonymy, 34 univocal.
  File hashes are in `baseline.json` beside this receipt.

## Runtime observations

The declared controller lane cache is empty. `XDG_CACHE_HOME`, `UV_CACHE_DIR`,
`HF_HOME`, `HF_HUB_CACHE`, `HUGGINGFACE_HUB_CACHE`, and `TRANSFORMERS_CACHE` are
unset. The default Hugging Face cache does not exist. The default uv cache was
created by the offline setup attempt; the required torch wheel is absent.

The default interpreter is Python 3.14.4, outside the project's supported
`>=3.11,<3.13` range. A supported Python 3.12.12 toolchain is present, but its
environment lacks the project's dependencies and pytest. The offline setup
attempt created an ignored `.venv`; it could not install the locked dependency
closure. This environment is retained for recovery.

| Command | Observed result |
| --- | --- |
| `uv sync --offline --frozen --extra dev --python 3.12` | Exit 1: `torch==2.11.0` CPython 3.12 wheel absent from cache. Offline mode prevented a download. |
| `PYTHONPATH=src:. HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python3 -m pytest -q tests/polysemy/test_labeled_set.py tests/bench/test_phase9_rollup.py` | Exit 4: root conftest cannot import `pydantic`. This diagnostic used the unsupported default interpreter and establishes no regression result. |
| `.venv/bin/python -m pytest -q tests/polysemy/ tests/bench/test_phase9_rollup.py` | No module named `pytest` in the supported Python environment; no tests ran. |

The baseline detector evaluation, candidate evaluation, broad fast suite, and
later simplify/review stages did not run. Repeating a broader pytest selection
cannot resolve the same missing runtime. No frontend changes were made, so no
browser screenshot applies.

## Why execution stopped

Plan A3 and R5 require cache-resident dependencies and the real
`all-MiniLM-L6-v2` snapshot. U2 requires development measurements before freezing
its parameters; U4 requires baseline and holdout measurements. Missing runtime
inputs cannot be replaced by fabricated embeddings or an assumed pass.

The `ce-work` prerequisite check returned blocked. The `lfg` workflow stops on
an incomplete child return, so no implementation, simplification, or code-review
completion is claimed. Only this prerequisite evidence is committed.

## Controller recovery

1. Provide the locked Python 3.12 development dependency cache, including torch,
   and the complete local `all-MiniLM-L6-v2` snapshot. Wire the cache locations
   into the sandbox. Do not supply provider credentials or enable model
   downloads. Provide the campaign Goal Capsule and cited R-ID excerpts if the
   chief repository remains unavailable.
2. Re-run the offline setup command above and verify the focused baseline on
   the supported interpreter before implementation.
3. Resume `lfg` on the same plan and branch. Independently author and review the
   holdout before candidate tuning, preserve the legacy fixtures/tests, and
   complete U1-U4 plus the remaining local review and commit steps.

This is a controller provisioning dependency, not a product decision for Damien.
The branch is not ready for the campaign merge gate. No package release,
migration, outside service, provider call, or spend is needed for recovery.
