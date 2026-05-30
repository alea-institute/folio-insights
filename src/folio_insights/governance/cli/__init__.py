"""``folio-insights governance`` Click subgroup (D-03, D-15, D-19).

Phase 7 CLI surface for the governance substrate. Mirrors the Phase-6 ``did``
subgroup idiom — a single ``@click.group()`` decorated with subcommands
imported at module bottom (the same pattern bench / polysemy / identity use).

Three subcommands ship in 07-04b:

  * ``governance promote <shard_iri> --status <s> --cite <iri>... --corpus <c>``
    — promote a HypothesisShard to an attested status (D-20 + D-21 validators).
  * ``governance assert-role <subject_did> --role <r> --corpus <c>`` — issue a
    role assertion (corpus_admin-only per the authorize() table).
  * ``governance revoke-role <subject_did> --revoked-role <r> --corpus <c>``
    — revoke a previously-asserted role (D-11 lockout refusal surfaces here).

07-05a will extend this group with ``contest``, ``supersede``,
``resolve-contest``; 07-05b will extend with ``retract``, ``export``.

D-19 invariant: every command's first awaited step is ``await authorize(...)``
— enforced AST-level by ``tests/governance/test_authorize_called_first.py``.

D-03 boundary: this ships CLI + library surface ONLY. No web UI in Phase 7.
"""
from __future__ import annotations

import click


@click.group(name="governance")
def governance_group() -> None:
    """Governance substrate: promote / assert-role / revoke-role (Phase 7).

    Every command's first step is ``await authorize(...)`` per D-19. The
    central authorize() gate decides; per-event SHACL belts run at log
    layer; Phase 6 sign_attestation provides the cryptographic substrate.
    """


# Subcommand registration — module-bottom imports mirror the Phase 6 did
# subgroup pattern. Keeps top-of-module light at `governance --help` time.
from folio_insights.governance.cli.promote import promote_cmd  # noqa: E402
from folio_insights.governance.cli.role_assert import role_assert_cmd  # noqa: E402
from folio_insights.governance.cli.role_revoke import role_revoke_cmd  # noqa: E402

governance_group.add_command(promote_cmd)
governance_group.add_command(role_assert_cmd)
governance_group.add_command(role_revoke_cmd)


__all__ = ["governance_group"]
