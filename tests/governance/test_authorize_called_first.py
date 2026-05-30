"""D-19 source-scan regression: authorize() is the first awaited call in every CLI command.

AST-walks each Click-decorated command function in:
  * src/folio_insights/governance/cli/promote.py
  * src/folio_insights/governance/cli/role_assert.py
  * src/folio_insights/governance/cli/role_revoke.py
  * src/folio_insights/corpus/cli/corpus.py    ← Issue #3 closure: NO CLI exemption

For each Click command function body, assert the first ``Await(Call)`` whose
target is either ``authorize(...)`` OR a call returning the authorize coroutine
appears BEFORE any ``Await(Call(Attribute('append')))`` (the governance log
append step).

This is the structural invariant D-19 codifies: no CLI command may write to
the governance log without first passing through the central authorize() gate.
The genesis bootstrap is NOT exempt — corpus init's action="corpus_init"
passes the same gate (the carve-out lives inside authorize() per 07-04a).
"""
from __future__ import annotations

import ast
import pathlib

import pytest

pytestmark = pytest.mark.governance


# The 4 Click command modules MUST satisfy authorize-called-first.
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_COMMAND_FILES = [
    _REPO_ROOT / "src/folio_insights/governance/cli/promote.py",
    _REPO_ROOT / "src/folio_insights/governance/cli/role_assert.py",
    _REPO_ROOT / "src/folio_insights/governance/cli/role_revoke.py",
    _REPO_ROOT / "src/folio_insights/corpus/cli/corpus.py",
]


def _click_command_functions(module_ast: ast.Module) -> list[ast.FunctionDef]:
    """Return every async or sync function decorated with @<group>.command(...)."""
    out: list[ast.FunctionDef] = []
    for node in ast.walk(module_ast):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            # @<grp>.command("...") OR @<grp>.command(...).
            target = dec
            if isinstance(dec, ast.Call):
                target = dec.func
            if isinstance(target, ast.Attribute) and target.attr == "command":
                out.append(node)
                break
    return out


def _is_authorize_call(call: ast.Call) -> bool:
    """Heuristic: the call IS `authorize(...)` (Name) or `.authorize(...)`."""
    func = call.func
    if isinstance(func, ast.Name) and func.id == "authorize":
        return True
    if isinstance(func, ast.Attribute) and func.attr == "authorize":
        return True
    return False


def _is_append_call(call: ast.Call) -> bool:
    """Heuristic: the call is `<log>.append(...)`."""
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr == "append":
        return True
    return False


def _walk_awaits(body: list[ast.stmt]) -> list[ast.Await]:
    """Return every ``Await(Call(...))`` node in declaration order across the
    function body (descending into nested ``async def _run()`` helpers so the
    common ``asyncio.run(_run())`` idiom is covered)."""
    awaits: list[ast.Await] = []
    for stmt in body:
        for sub in ast.walk(stmt):
            if isinstance(sub, ast.Await):
                awaits.append(sub)
    return awaits


@pytest.mark.parametrize(
    "command_file", _COMMAND_FILES, ids=lambda p: f"{p.parent.name}/{p.name}"
)
def test_authorize_is_first_await_before_append(command_file: pathlib.Path) -> None:
    """Every Click command function in ``command_file`` MUST call
    ``authorize(...)`` (an ``Await`` over a ``Call`` to ``authorize``) BEFORE
    any ``Await`` over a ``.append(...)`` call.

    This is the structural D-19 invariant. Even ``corpus init`` (Issue #3
    closure — no CLI exemption) must satisfy it; the carve-out for genesis
    bootstrap lives inside ``authorize()`` via ``action="corpus_init"``.
    """
    assert command_file.exists(), (
        f"D-19 regression target {command_file} does not ship — every command "
        "module in the parametrize list MUST exist in 07-04b."
    )
    source = command_file.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(command_file))

    commands = _click_command_functions(tree)
    assert len(commands) >= 1, (
        f"{command_file.name}: no @<group>.command(...)-decorated functions "
        "found — D-19 regression cannot run."
    )

    for cmd in commands:
        awaits = _walk_awaits(cmd.body)
        # Collect indices of authorize-awaits + append-awaits in declaration order.
        authorize_idx: int | None = None
        append_idx: int | None = None
        for i, aw in enumerate(awaits):
            if not isinstance(aw.value, ast.Call):
                continue
            call = aw.value
            if authorize_idx is None and _is_authorize_call(call):
                authorize_idx = i
            if append_idx is None and _is_append_call(call):
                append_idx = i

        assert authorize_idx is not None, (
            f"{command_file.name}::{cmd.name}: NO `await authorize(...)` call "
            f"found in the command body. D-19 requires authorize() as the "
            f"first awaited step of every CLI command — including "
            f"`corpus init` (Issue #3 closure)."
        )
        if append_idx is not None:
            assert authorize_idx < append_idx, (
                f"{command_file.name}::{cmd.name}: `await authorize(...)` "
                f"appears AFTER `await <log>.append(...)`. D-19 requires "
                f"authorize() to gate the log write."
            )


def test_corpus_init_uses_corpus_init_action() -> None:
    """corpus init MUST pass ``action="corpus_init"`` to authorize() — the
    bookkeeping action name that triggers the genesis carve-out inside
    authorize() (Issue #3 closure — no CLI exemption)."""
    corpus_cli = _REPO_ROOT / "src/folio_insights/corpus/cli/corpus.py"
    source = corpus_cli.read_text(encoding="utf-8")
    assert 'action="corpus_init"' in source or "action='corpus_init'" in source, (
        "corpus init MUST call authorize(..., action=\"corpus_init\", ...). "
        "The genesis carve-out lives inside authorize() per 07-04a; the CLI "
        "command is NOT exempt from the authorize-first rule (Issue #3 fix)."
    )
