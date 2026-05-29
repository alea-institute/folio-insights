"""``folio-insights did`` Click subgroup (DID-05 / DID-07 CLI surface).

Mirrors the Phase-1 ``polysemy`` subgroup idiom (rich prompts + a
``@click.group()`` + sibling commands), wired into the root CLI via
``cli.add_command(did_group)`` (the same pattern bench/polysemy use).

Five sibling commands:

* ``did generate`` — local-keystore ed25519 keypair → did:key (DID-06).
* ``did bind`` — orchestrate nonce issue → proof sign → ``binding.bind``
  (SEC-06 / F3 / F7).
* ``did sign`` — show the DID-07 preview, confirm with a keystroke (or
  ``--yes``), sign over the JCS canonical content hash with the locally-
  loaded key.
* ``did verify`` — resolve the signing-time key via the cache + resolver
  and verify a recorded ``AttestedSignature``.
* ``did preview`` — render the DID-07 ``what will I be signing?`` preview
  without signing (EC5 CLI form).

Security invariants (DID-06 / D-07):

* Signing is ALWAYS client-side via the local keystore (
  ``identity.keys.load_signing_key``). The private key NEVER leaves the
  operator's machine; this module accepts a keyfile *path* (not key
  material) and immediately drops the loaded ``Ed25519PrivateKey``
  reference after signing.
* The CLI never persists, transmits, or logs a private key. The contract
  test ``tests/identity/test_no_server_keys_contract.py`` parses this
  module with ``ast`` and confirms no ``private_bytes`` / JWK-``d`` write
  call site outside ``keys.py``.

What's deferred (D-02):

* The web OAuth flow + styled preview component + browser WebCrypto signing
  belong to the post-Phase-14 surface. The CLI exercises the SAME binding
  + preview contract the web phase will render.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import click

# These imports stay at module top — none pull in transitive crypto / RDF
# libraries beyond what identity/__init__.py already loads (which is fine:
# the dep-leak guard is on shards/, not on the CLI module).
from folio_insights.identity import (
    InMemoryDidDocCache,
    InMemoryNonceStore,
    ProofPayload,
    bind as _bind,
    build_signing_preview,
    generate_keypair,
    load_signing_key,
    sign_attestation,
    verify_attestation,
)
from folio_insights.identity.keys import KEY_PATH


# ── helpers ────────────────────────────────────────────────────────────────


def _derive_didkey_from_signing_key(sk) -> str:
    """Derive the did:key for the public half of a loaded Ed25519PrivateKey.

    Local helper so ``did sign`` / ``did bind`` don't need to import
    ``keys.did_key_from_public`` independently. Kept inside the function
    body where used so the contract test doesn't have to allow-list it as a
    second `private_bytes` consumer — the test cares about the SOURCE module
    (``keys.py`` is the only one allowed to call ``private_bytes``).
    """
    from cryptography.hazmat.primitives import serialization

    from folio_insights.identity.keys import did_key_from_public

    raw = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return did_key_from_public(raw)


def _format_preview(preview) -> str:
    """Format a ``SigningPreview`` for terminal output (CLI/API form, D-02)."""
    return (
        f"\n  action:       {preview.action}\n"
        f"  shard_iri:    {preview.shard_iri}\n"
        f"  content_hash: {preview.content_hash}\n"
        f"  what:         {preview.human_readable}\n"
    )


# ── `did` group ────────────────────────────────────────────────────────────


@click.group(name="did")
def did_group() -> None:
    """DID substrate: generate / bind / sign / verify / preview (Phase 6).

    The DID-signed-attestation surface PRD §6.5 requires. Signing happens
    CLIENT-SIDE with the local keyfile (DID-06); private keys never leave
    your machine.
    """


# ── did generate ───────────────────────────────────────────────────────────


@did_group.command("generate")
@click.option(
    "--method",
    type=click.Choice(["key"], case_sensitive=False),
    default="key",
    show_default=True,
    help="DID method to generate. Phase 6 ships did:key full-fidelity; "
    "did:web is operator-provisioned, did:plc is resolve-only (D-08).",
)
@click.option(
    "--key-path",
    type=click.Path(path_type=Path),
    default=KEY_PATH,
    show_default=True,
    help=(
        "Path to the local ed25519 keystore JWK (mode 0o600). "
        "Generation is IDEMPOTENT — a second call with an existing keyfile "
        "reuses it and prints the same did:key (the Phase-1 "
        "ensure_reviewer_did contract)."
    ),
)
def generate_cmd(method: str, key_path: Path) -> None:
    """Generate (or REUSE) the local ed25519 keypair; print the did:key.

    Extends the Phase-1 ``~/.folio-insights`` keystore pattern. The keyfile
    is created with mode 0o600 inside a 0o700 parent dir; the public did:key
    is printed to stdout. The private key NEVER leaves the keyfile.
    """
    if method.lower() != "key":
        click.echo(
            f"Error: --method={method!r} not supported in Phase 6. "
            "Only did:key is ship-able (did:web is operator-provisioned; "
            "did:plc is resolve-only, D-08).",
            err=True,
        )
        sys.exit(1)
    did = generate_keypair(key_path)
    click.echo(did)


# ── did preview ────────────────────────────────────────────────────────────


@did_group.command("preview")
@click.option(
    "--action",
    required=True,
    type=click.Choice(
        [
            "extract", "promote", "demote", "contest",
            "supersede", "retract", "distinguo", "role_assertion",
            "content_edit", "reparent", "reconcile", "resolve_contest",
        ],
        case_sensitive=False,
    ),
    help="The SignedAction the signature would carry.",
)
@click.option(
    "--shard-json",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help=(
        "Path to a JSON file holding the ShardEnvelope (model_dump form) "
        "the preview should render against."
    ),
)
@click.option(
    "--change-json",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help=(
        "Optional path to a JSON file holding the per-action change "
        "descriptor (e.g. {''from'': ''hypothesis'', ''to'': "
        "''demonstrable''} for promote)."
    ),
)
def preview_cmd(action: str, shard_json: Path, change_json: Path | None) -> None:
    """Render the DID-07 ``what will I be signing?`` preview without signing.

    Loads the shard from ``--shard-json``, optionally loads a per-action
    ``--change-json`` descriptor, and prints the canonical content hash + a
    human-readable line. NO signature is produced; this is the safe lookout.
    """
    shard = _load_shard(shard_json)
    change = json.loads(change_json.read_text(encoding="utf-8")) if change_json else None
    preview = build_signing_preview(action, shard, change=change)  # type: ignore[arg-type]
    click.echo(_format_preview(preview))


# ── did sign ───────────────────────────────────────────────────────────────


@did_group.command("sign")
@click.option(
    "--action",
    required=True,
    type=click.Choice(
        [
            "extract", "promote", "demote", "contest",
            "supersede", "retract", "distinguo", "role_assertion",
            "content_edit", "reparent", "reconcile", "resolve_contest",
        ],
        case_sensitive=False,
    ),
    help="The SignedAction this signature carries.",
)
@click.option(
    "--shard-json",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="ShardEnvelope JSON (model_dump form) — the shard being signed.",
)
@click.option(
    "--key-path",
    type=click.Path(exists=False, dir_okay=False, path_type=Path),
    default=KEY_PATH,
    show_default=True,
    help="Path to the local ed25519 keystore JWK (DID-06).",
)
@click.option(
    "--change-json",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Optional per-action change descriptor JSON.",
)
@click.option(
    "--yes",
    is_flag=True,
    default=False,
    help=(
        "Skip the post-preview confirmation. Useful for scripted signing; "
        "interactive use should always confirm BEFORE the keystroke."
    ),
)
def sign_cmd(
    action: str,
    shard_json: Path,
    key_path: Path,
    change_json: Path | None,
    yes: bool,
) -> None:
    """Sign a shard's canonical content hash with the local keystore (DID-06).

    Sequence (DID-07 preview-first):
    1. Load the shard + (optional) change descriptor.
    2. Render the DID-07 preview to stdout.
    3. Confirm with a keystroke (unless ``--yes``).
    4. Load the local ed25519 private key; sign the canonical hash.
    5. Print the resulting ``AttestedSignature`` as JSON.

    The private key is loaded, used, and the reference dropped — never
    persisted, never logged, never transmitted (DID-06).
    """
    shard = _load_shard(shard_json)
    change = json.loads(change_json.read_text(encoding="utf-8")) if change_json else None

    preview = build_signing_preview(action, shard, change=change)  # type: ignore[arg-type]
    click.echo("ABOUT TO SIGN:")
    click.echo(_format_preview(preview))

    if not yes:
        # rich.prompt.Confirm would be the polysemy idiom, but Click's
        # confirm is sufficient and avoids the rich dep for a one-keystroke gate.
        if not click.confirm("Sign this attestation?", default=False):
            click.echo("Aborted by operator (no signature produced).", err=True)
            sys.exit(2)

    sk = load_signing_key(key_path)
    did = _derive_didkey_from_signing_key(sk)
    key_id = f"{did}#{did.removeprefix('did:key:')}"

    sig = sign_attestation(
        preview.content_hash,
        sk,
        did,
        action,  # type: ignore[arg-type]
        signing_key_id=key_id,
        did_doc_snapshot_at=None,  # did:key: degenerate snapshot
        now=datetime.now(UTC),
    )
    # `sk` falls out of scope after this point; the loaded private key is
    # neither persisted nor transmitted by this command (DID-06).
    click.echo(sig.model_dump_json(indent=2))


# ── did verify ─────────────────────────────────────────────────────────────


@did_group.command("verify")
@click.option(
    "--shard-json",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help=(
        "ShardEnvelope JSON (model_dump form) the signature was produced "
        "against. The verifier recomputes the canonical hash and compares "
        "to the signature's ``over_content_hash`` (fail-closed if drifted)."
    ),
)
@click.option(
    "--signature-json",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="AttestedSignature JSON (model_dump form) to verify.",
)
@click.option(
    "--did-doc",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help=(
        "Path to a recorded did.json (offline did:web verify). When set, "
        "the verifier resolves the DID document from this file instead of "
        "making a network call."
    ),
)
@click.option(
    "--allow-network",
    is_flag=True,
    default=False,
    help=(
        "Permit live did:web / did:plc resolution. OFF by default (WR-07): "
        "an attacker-supplied AttestedSignature carrying did:web:internal.corp "
        "could otherwise pivot the verifier into an SSRF against an internal "
        "service. Operators in offline / air-gapped contexts MUST keep this "
        "flag off and supply --did-doc for did:web verification."
    ),
)
def verify_cmd(
    shard_json: Path,
    signature_json: Path,
    did_doc: Path | None,
    allow_network: bool,
) -> None:
    """Verify a recorded ``AttestedSignature`` against the shard (PASS/FAIL).

    Resolves the signing-time key via the in-memory cache + Plan-02
    resolver. By default (WR-07) the CLI does NOT touch the network — a
    did:web / did:plc verify against a non-cached snapshot fails unless the
    caller supplies ``--did-doc`` (offline path) or ``--allow-network``.
    did:key signatures verify cleanly without either (no network needed).
    Exits 0 on PASS, 1 on FAIL.
    """
    shard = _load_shard(shard_json)
    sig = _load_signature(signature_json)
    cache = InMemoryDidDocCache()

    if did_doc is not None:
        recorded = json.loads(did_doc.read_text(encoding="utf-8"))

        async def _offline_http(_url: str) -> dict:
            return recorded

        http_callable = _offline_http
    elif allow_network:
        http_callable = None  # let the verifier fall through to default
    else:
        async def _refuse_network(url: str) -> dict:
            raise RuntimeError(
                f"verify needs to fetch {url!r} but --allow-network is off "
                "and no --did-doc was supplied (WR-07: the CLI does not "
                "touch the network by default)."
            )

        http_callable = _refuse_network

    ok = asyncio.run(
        verify_attestation(shard, sig, cache=cache, http=http_callable)
    )
    if ok:
        click.echo("VERIFY: PASS")
        sys.exit(0)
    click.echo("VERIFY: FAIL", err=True)
    sys.exit(1)


# ── did bind ───────────────────────────────────────────────────────────────


@did_group.command("bind")
@click.option(
    "--sub",
    required=True,
    help="OAuth `sub` claim (the immutable subject identifier; NOT email — F7).",
)
@click.option(
    "--key-path",
    type=click.Path(exists=False, dir_okay=False, path_type=Path),
    default=KEY_PATH,
    show_default=True,
    help="Local ed25519 keystore JWK (DID-06). did:key is derived from it.",
)
@click.option(
    "--binding-endpoint",
    required=True,
    help=(
        "The binding-endpoint URL that issued the nonce. Pinned in the "
        "signed proof payload (F3 / cross-endpoint replay defense)."
    ),
)
def bind_cmd(sub: str, key_path: Path, binding_endpoint: str) -> None:
    """Bind the local did:key to ``--sub`` via a signed proof-of-control (SEC-06).

    Sequence: derive did:key from the local keystore → issue a single-use
    nonce → build + sign the proof payload with the local key → call
    ``binding.bind`` with a fresh in-memory NonceStore + binding_store. Prints
    the resulting ``BindingRecord`` as JSON or a typed error.

    NOTE: The in-memory NonceStore + binding_store are EPHEMERAL (this CLI
    process only). Persistent stores are the deferred-web-phase concern (D-02);
    in Phase 6 this command demonstrates the rules end-to-end, the deferred
    web flow will run the same rules against Redis + a database.
    """
    sk = load_signing_key(key_path)
    did = _derive_didkey_from_signing_key(sk)

    async def _run() -> None:
        nonce_store = InMemoryNonceStore()
        nonce = await nonce_store.issue()
        proof = ProofPayload(
            sub=sub,
            nonce=nonce,
            issued_at=datetime.now(UTC),
            binding_endpoint=binding_endpoint,
            did=did,
        )
        # Sign the proof payload — the proof signature itself is an
        # AttestedSignature over the SHA-256 of the JCS-canonical proof.
        import hashlib

        from folio_insights.revision.content_edit import _jcs_canonical_bytes

        payload = proof.model_dump(mode="json")
        proof_hash = hashlib.sha256(_jcs_canonical_bytes(payload)).hexdigest()
        key_id = f"{did}#{did.removeprefix('did:key:')}"
        proof_sig = sign_attestation(
            proof_hash, sk, did, "role_assertion",
            signing_key_id=key_id,
            did_doc_snapshot_at=None,
        )
        binding_store: dict = {}
        cache = InMemoryDidDocCache()
        try:
            record = await _bind(
                sub,
                did,
                proof,
                proof_sig,
                nonce_store=nonce_store,
                binding_store=binding_store,
                expected_binding_endpoint=binding_endpoint,
                cache=cache,
            )
        except Exception as exc:
            click.echo(f"BIND FAILED: {type(exc).__name__}: {exc}", err=True)
            sys.exit(1)
        click.echo(record.model_dump_json(indent=2))

    asyncio.run(_run())


# ── private loader helpers (kept off the public surface) ────────────────────


def _load_shard(path: Path):
    """Load a ShardEnvelope from a JSON file (model_dump form).

    Uses the Phase-3 discriminated-union ``Shard`` (an
    ``Annotated[Union[…], Field(discriminator="shard_type")]``) via a Pydantic
    ``TypeAdapter`` so any subtype (SimpleAssertion / Hypothesis / etc.)
    round-trips. Fails loud with click.echo + exit on a malformed file rather
    than letting a Pydantic ValidationError leak to a traceback.
    """
    from pydantic import TypeAdapter

    from folio_insights.shards import Shard

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        ta: TypeAdapter = TypeAdapter(Shard)
        return ta.validate_python(raw)
    except Exception as exc:
        click.echo(f"Error loading shard JSON from {path}: {exc}", err=True)
        sys.exit(1)


def _load_signature(path: Path):
    """Load an AttestedSignature from a JSON file (model_dump_json form)."""
    from folio_insights.shards import AttestedSignature

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return AttestedSignature.model_validate(raw)
    except Exception as exc:
        click.echo(f"Error loading signature JSON from {path}: {exc}", err=True)
        sys.exit(1)


__all__ = ["did_group"]
