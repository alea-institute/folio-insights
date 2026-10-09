"""Seed the axiom kernel into a corpus (drain U3, R10, KTD7).

``seed_kernel`` writes every verified kernel maxim (``kernel.catalog``) into a
corpus as one ``SimpleAssertionShard``, through the same framework-checked
storage context the minter writes through, so each kernel shard passes the
envelope model, the PII gate, the SHACL local tier and the ``FrameworkGuard``
before it is journaled.

Frameworks. Each collection is its own Carnapian framework,
``ius_commune.canon.liber_sextus`` and ``ius_commune.roman.digest``. Neither is
in the starter set, so the seed registers each one in the target corpus by a
signed corpus-admin registration (``frameworks.registry.register_framework``,
the same path as ``folio-insights framework register``) when the corpus does
not hold it yet. A non-admin signer is refused before anything is written.

Idempotence. A kernel shard's identity is a pure function of the packaged
dataset: its IRI is ``mint_shard_iri(citation_uri, latin)`` and its
``extracted_at`` is the dataset's recorded retrieval time (when the fetch
script cut the text out of its source). A maxim whose IRI the corpus already
holds is skipped, whoever seeded it. The missing maxims of a collection are
ingested as ONE atomic batch under the deterministic operation ID
``kernel-seed:<collection>:<dataset>:<numbers>`` (``<dataset>`` is the first 16
hex digits of the packaged dataset file's SHA-256, ``<numbers>`` the compact
range list of the maxims written, e.g. ``1-88``; row ``i`` of the batch commits
as ``<op>#i``), so a crash leaves a collection either fully seeded or
untouched, and a second seed writes nothing. The dataset digest is part of the
ID because a maxim's IRI is minted from its citation and Latin: a dataset
revision that corrects a transcription mints new IRIs under the same numbers,
and must seed as a new batch rather than collide with the earlier one.

Races. Two seeds racing on one corpus cannot both commit a maxim: the loser's
differently-signed batch is refused as an operation-ID replay mismatch
(``OperationIdConflict``), never appended twice. ``seed_kernel`` then re-reads
which maxims are present: when the winner stored all of them the loser reports
them ``already_present`` (the same outcome as seeding after the winner);
otherwise it raises ``KernelSeedError``. One batch per collection also keeps a
full seed to one projection catch-up per collection.

Signature. Each new kernel shard carries one ``extract`` ``AttestedSignature``
by the seeding admin over its canonical content hash (the SHACL suite warns on
an unsigned shard, PRD §10 decision #10), so the record says who vouched that
the text was copied from the cited edition.

No model is involved: ``extractor_model`` names the deterministic seed recipe
(``kernel-seed/<KERNEL_SEED_VERSION>``) and ``extraction_prompt_hash`` is the
SHA-256 of the dataset file the text came from, the nearest analogue of a
prompt for a field-for-field copy.

Field choices (KTD7, every value from the envelope's existing enums):

* ``layer="L0_primitive"`` — the kernel is the primitive layer every other
  layer composes from (PHILOSOPHY.md, "Axiomatic kernel layer").
* ``speech_act="statutory_text"`` — the regulae are enacted text: the Liber
  Sextus was promulgated by Boniface VIII, the Digest enacted by Justinian
  with the force of law. They are neither holdings nor treatise statements.
* ``epistemic_status=KERNEL_EPISTEMIC_STATUS`` (``"authority_only"``) and
  ``verification_method="textual_citation"`` — accepted on the authority of
  the collection, verified by citing its text, never proved here.
* ``predication_mode="per_se"`` — a regula states what belongs to a legal
  notion as such (*nemo potest ad impossibile obligari* holds of obligation
  universally), not an accidental fact about a party.
* ``fork="synthetic_a_posteriori"`` — the shard asserts that the collection
  enacts this text. That is a matter of historical fact, known from the
  record and not from the meaning of the words; calling it ``analytic`` would
  claim a conceptual analysis the seed does not perform (its logical form is
  ``"unanalysed"``), and ``synthetic_a_priori`` would claim knowledge
  independent of the record, contradicting ``authority_only``.
* ``bfo_category="continuant_dependent"`` — the BFO spine's documented
  category for ``statutory_text`` (``bfo.spine.DEFAULT_CATEGORY_BY_SPEECH_ACT``):
  an enacted text is a generically dependent continuant (an information
  artifact borne by its copies). No classifier rule types a Latin sentence's
  subject, so the documented speech-act category is the defensible value.
* ``triple`` = (shard IRI, ``fi:sense``, Latin literal, ``xsd:string``): the
  vocabulary has no "asserts this maxim" predicate and this unit adds no term.
  An unanalysed maxim's sense is given only by its words, which is what
  ``fi:sense`` ("Fregean sense of the shard's proposition") records.
* ``sense`` = the Latin text; ``reference`` = the citation (plus the Digest
  fragment's inscription); ``logical_form_imputed="unanalysed"``;
  ``confidence=1.0`` (the text is a verified substring of its source).
* ``source_uri`` = the canonical citation URI; ``source_span`` = the Latin.
* ``valid_time_start`` = the collection's promulgation date.

Projection. The storage projection types every shard ``fi:Shard`` and its
adapter version is not changed here, so kernel shards are typed
``fi:CommonAxiom`` only in the kernel chain export (``kernel.export``).
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import folio_insights
from folio_insights.kernel.catalog import (
    KernelCatalog,
    KernelMaxim,
    collection_spec,
    load_catalog,
)
from folio_insights.shards import AttestedSignature, SimpleAssertionShard, Triple
from folio_insights.vocab._constants import FI_PREFIX

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from folio_insights.storage.context import StorageConfig

# Cockpit decision folio-insights-2026-10-09-1148-kernel-epistemic-status, q1
# (answered by Chief, 2026-10-09; tier auto, provenance chief; Damien can
# overrule): the regulae are accepted on the authority of the Liber Sextus and
# the Digest, not proved, so kernel shards are seeded ``authority_only``. This
# is the ONE place the value is set.
KERNEL_EPISTEMIC_STATUS = "authority_only"

# Version of the deterministic seed recipe (the shard field mapping above).
# Bump it only with a reviewed change to that mapping.
KERNEL_SEED_VERSION = "1"
KERNEL_EXTRACTOR_MODEL = f"kernel-seed/{KERNEL_SEED_VERSION}"
KERNEL_PREDICATE = f"{FI_PREFIX}sense"
XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"
KERNEL_LOGICAL_FORM = "unanalysed"


class KernelSeedError(RuntimeError):
    """The kernel cannot be seeded into this corpus as asked."""


def _ranges(numbers: Iterable[int]) -> str:
    """``[1, 2, 3, 5, 7, 8]`` -> ``"1-3,5,7-8"`` (sorted, deduplicated)."""
    parts: list[str] = []
    ordered = sorted(set(numbers))
    i = 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and ordered[j + 1] == ordered[j] + 1:
            j += 1
        parts.append(str(ordered[i]) if i == j else f"{ordered[i]}-{ordered[j]}")
        i = j + 1
    return ",".join(parts)


DATASET_DIGEST_CHARS = 16


def seed_op_id(
    collection: str,
    maxims: Iterable[KernelMaxim],
    *,
    dataset_sha256: str | None = None,
) -> str:
    """The deterministic operation ID a collection's seed batch commits under:
    ``kernel-seed:<collection>:<dataset sha256[:16]>:<compact range list of maxim
    numbers>``. ``dataset_sha256`` defaults to the packaged dataset's digest."""
    numbers = [m.number for m in maxims]
    if not numbers:
        raise ValueError("a seed batch needs at least one maxim")
    digest = dataset_sha256 or load_catalog().dataset_sha256[collection_spec(collection).key]
    return f"kernel-seed:{collection}:{digest[:DATASET_DIGEST_CHARS]}:{_ranges(numbers)}"


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def kernel_shard(
    maxim: KernelMaxim,
    *,
    extractor_did: str,
    signing_key: Ed25519PrivateKey | None = None,
    signed_at: datetime | None = None,
    catalog: KernelCatalog | None = None,
) -> SimpleAssertionShard:
    """The kernel shard for ``maxim`` (field choices: module docstring).

    With ``signing_key`` (whose did:key must be ``extractor_did``) the shard
    carries one ``extract`` signature over its canonical content hash, signed
    at ``signed_at`` (default: now); without it the shard is unsigned.
    """
    catalog = catalog or load_catalog()
    spec = collection_spec(maxim.collection)
    recorded = _utc(maxim.provenance.retrieved_at)
    shard = SimpleAssertionShard(
        shard_iri=maxim.shard_iri,
        provenance_hash=maxim.provenance_hash,
        source_uri=maxim.citation_uri,
        source_span=maxim.latin,
        extracted_at=recorded,
        first_extractor_did=extractor_did,
        triple=Triple(
            subject=maxim.shard_iri,
            predicate=KERNEL_PREDICATE,
            object=maxim.latin,
            object_datatype=XSD_STRING,
        ),
        sense=maxim.latin,
        reference=maxim.reference,
        logical_form_imputed=KERNEL_LOGICAL_FORM,
        layer="L0_primitive",
        predication_mode="per_se",
        fork="synthetic_a_posteriori",
        epistemic_status=KERNEL_EPISTEMIC_STATUS,
        verification_method="textual_citation",
        framework_id=spec.framework.id,
        speech_act="statutory_text",
        extractor_version=folio_insights.__version__,
        extraction_prompt_hash=catalog.dataset_sha256[maxim.collection],
        extractor_model=KERNEL_EXTRACTOR_MODEL,
        confidence=1.0,
        bfo_category="continuant_dependent",
        valid_time_start=spec.valid_from,
    )
    if signing_key is None:
        return shard
    return shard.model_copy(
        update={"signatures": [
            extract_signature(shard, signing_key=signing_key, did=extractor_did, now=signed_at)
        ]}
    )


def extract_signature(
    shard: SimpleAssertionShard,
    *,
    signing_key: Ed25519PrivateKey,
    did: str,
    now: datetime | None = None,
) -> AttestedSignature:
    """An ``extract`` signature by ``did`` over ``shard``'s content hash."""
    from folio_insights.identity.signer import sign_attestation
    from folio_insights.revision.content_edit import canonical_content_hash

    if did != did_for_signing_key(signing_key):
        raise KernelSeedError(f"did {did!r} is not the did:key of the signing key")
    return sign_attestation(
        canonical_content_hash(shard),
        signing_key,
        did,
        "extract",
        signing_key_id=f"{did}#{did.removeprefix('did:key:')}",
        did_doc_snapshot_at=None,  # did:key cannot rotate; no snapshot needed
        now=now or datetime.now(UTC),
    )


@dataclass
class CollectionSeed:
    collection: str
    framework_id: str
    framework_registered: bool = False
    written: list[str] = field(default_factory=list)
    already_present: list[str] = field(default_factory=list)


@dataclass
class SeedReport:
    """What a ``seed_kernel`` run did, per collection."""

    corpus: str
    seeder_did: str
    collections: list[CollectionSeed]

    @property
    def written(self) -> int:
        return sum(len(c.written) for c in self.collections)

    @property
    def already_present(self) -> int:
        return sum(len(c.already_present) for c in self.collections)

    def as_dict(self) -> dict[str, Any]:
        return {
            "corpus": self.corpus,
            "seeder_did": self.seeder_did,
            "written": self.written,
            "already_present": self.already_present,
            "collections": [
                {
                    "collection": c.collection,
                    "framework_id": c.framework_id,
                    "framework_registered": c.framework_registered,
                    "written": len(c.written),
                    "already_present": len(c.already_present),
                }
                for c in self.collections
            ],
        }


def did_for_signing_key(signing_key: Ed25519PrivateKey) -> str:
    """The did:key of ``signing_key``'s public half."""
    from cryptography.hazmat.primitives import serialization

    from folio_insights.identity.keys import did_key_from_public

    raw = signing_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    return did_key_from_public(raw)


async def seed_kernel(
    root: Path | str,
    corpus: str,
    *,
    signing_key: Ed25519PrivateKey,
    did: str | None = None,
    collections: Iterable[str] = ("liber_sextus", "digest"),
    config: StorageConfig | None = None,
) -> SeedReport:
    """Seed the kernel collections into ``corpus`` under ``root``.

    ``signing_key`` is a corpus admin's key: it signs any framework
    registration the corpus still needs, and its DID (``did``, derived from the
    key when omitted; any other DID is refused) becomes each new kernel shard's
    ``first_extractor_did`` and signs its ``extract`` attestation.
    Refuses (``FrameworkRegistrationRefused``) when a registration is needed
    and the signer is not a corpus admin, and (``KernelSeedError``) when the
    corpus registers a collection's framework ID with a different definition,
    or when a collection's batch is refused as an operation-ID conflict while
    some of its maxims are still missing. A race loser whose maxims the winner
    stored reports them ``already_present``.
    """
    from folio_insights.frameworks.registry import (
        open_framework_checked_context,
        register_framework,
    )
    from folio_insights.storage.errors import OperationIdConflict

    derived = did_for_signing_key(signing_key)
    if did is None:
        did = derived
    elif did != derived:
        # Registrations and extract signatures verify offline only for the
        # signing key's own did:key.
        raise KernelSeedError(f"did {did!r} is not the did:key of the signing key")
    keys = list(dict.fromkeys(collections))
    specs = [collection_spec(key) for key in keys]
    catalog = load_catalog()
    report = SeedReport(corpus=corpus, seeder_did=did, collections=[])

    ctx, guard = await open_framework_checked_context(root, corpus, config=config)
    try:
        registered_any = False
        for spec in specs:
            entry = CollectionSeed(spec.key, spec.framework.id)
            report.collections.append(entry)
            existing = guard.registry.get(spec.framework.id)
            if existing is None:
                await register_framework(ctx, spec.framework, signing_key=signing_key, did=did)
                entry.framework_registered = True
                registered_any = True
            elif existing != spec.framework:
                raise KernelSeedError(
                    f"corpus {corpus!r} registers framework {spec.framework.id!r} with a "
                    "different definition than the kernel's; refusing to seed into it"
                )
        if registered_any:
            await guard.refresh(ctx)
        for entry in report.collections:
            missing: list[KernelMaxim] = []
            for maxim in catalog.collection(entry.collection):
                if await ctx.shards.get(maxim.shard_iri) is not None:
                    entry.already_present.append(maxim.shard_iri)
                else:
                    missing.append(maxim)
            if not missing:
                continue
            signed_at = datetime.now(UTC)
            shards = [
                kernel_shard(m, extractor_did=did, signing_key=signing_key,
                             signed_at=signed_at, catalog=catalog)
                for m in missing
            ]
            op_id = seed_op_id(entry.collection, missing,
                               dataset_sha256=catalog.dataset_sha256[entry.collection])
            try:
                await ctx.ingest_shards(shards, op_id=op_id)
            except OperationIdConflict as exc:
                # Another seed committed this batch first (a race): its maxims
                # are what this run would have written.
                still_missing = [m for m in missing
                                 if await ctx.shards.get(m.shard_iri) is None]
                if still_missing:
                    raise KernelSeedError(
                        f"seed batch {op_id!r} conflicts with an earlier operation, and "
                        f"{len(still_missing)} of {len(missing)} {entry.collection} maxims "
                        f"are still missing from corpus {corpus!r}: {exc}"
                    ) from exc
                entry.already_present.extend(m.shard_iri for m in missing)
                continue
            entry.written.extend(m.shard_iri for m in missing)
    finally:
        await ctx.close()
    return report


__all__ = [
    "KERNEL_EPISTEMIC_STATUS",
    "KERNEL_EXTRACTOR_MODEL",
    "KERNEL_LOGICAL_FORM",
    "KERNEL_PREDICATE",
    "KERNEL_SEED_VERSION",
    "DATASET_DIGEST_CHARS",
    "CollectionSeed",
    "KernelSeedError",
    "SeedReport",
    "did_for_signing_key",
    "extract_signature",
    "kernel_shard",
    "seed_kernel",
    "seed_op_id",
]
