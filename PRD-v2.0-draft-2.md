# FOLIO Insights v2.0 — Product Requirements Document

**Status:** Draft-2 for implementation (ten design questions resolved)
**Target branch:** `v2.0`
**Author:** Damien Riehl (philosophical grounding synthesized with Claude)
**Companion document:** `PHILOSOPHY.md` — *Shards as Axioms: Philosophical Foundations for FOLIO Insights*
**Last updated:** April 2026

**Design decisions locked in draft-2** (see §21 for history):

1. **One framework per jurisdiction, time-scoped at the shard level** — not per version-year
2. **Mini-BFO spine with documented mapping to full BFO** — not a hard import
3. **Crowdsourced promotion** — any reviewer with a citation dependency can promote a hypothesis
4. **Immutable IDs** — relationships mutate freely, IDs never deprecate
5. **LLM-provider agnostic** — Claude, OpenAI, Gemini, or local open-source models via `instructor`
6. **Provenance-hash IDs** — SHA-256 of (source_uri + source_span) as the ID basis
7. **Mutable content under immutable IDs** — content edits update in place with an append-only audit log
8. **Retraction cascade + contested state** — overruling propagates; reviewer disagreements enter contested governance
9. **Supersession is not retraction** — valid_time boundaries + `fi:supersededBy` preserve historical shards
10. **DID-signed attestations** — every reviewer action is cryptographically signed; downstream systems weigh as they see fit

---

## 0. How to Use This Document

Claude Code should treat this PRD as the authoritative specification for the v2.0 refactor. Every requirement carries a priority (**P0** must ship in v2.0; **P1** should ship; **P2** should follow in v2.1), an acceptance test, and a philosophical warrant that explains *why* the design chooses this shape. When the warrant and the requirement conflict, file an issue — don't silently pick. When the requirement and existing code conflict, the requirement wins, but preserve v1.0 behavior behind a feature flag (`FOLIO_INSIGHTS_V1_COMPAT=true`) until the migration completes.

Implementation order: **§6 (shard model) → §7 (vocabulary) → §8 (pipeline) → §9 (SHACL) → §10 (storage) → §11 (UI) → §12 (tests)**. Earlier sections block later ones; don't parallelize across section boundaries without checking dependency notes.

---

## 1. Purpose

FOLIO Insights v1.0 extracts **knowledge units** from legal sources, tags them against FOLIO concepts, discovers task hierarchies, and ships validated OWL. It works. It also flattens everything it finds into one atomic unit type, treats each unit as roughly self-sufficient, and leaves most of the hard epistemic questions — *which shards are definitional, which are factual, which are disputed, which are analogical, which jurisdiction governs, what does this depend on* — for the downstream consumer to answer. The ontology is strong; the shards are thin.

v2.0 thickens the shard. Each extracted unit becomes a **typed, framework-annotated, dependency-linked, cluster-validated** object. The pipeline keeps its four-stage shape, the bridge pattern stays, and the `folio-enrich` dependency stays. The data model, the SHACL shapes, the export vocabulary, and the review UI all evolve.

The single sentence version: **v1.0 atomized; v2.0 atomizes with context**.

---

## 2. Problem Statement

Three concrete failures motivate the refactor:

**Failure 1 — Polysemy collapses silently.** When a source uses "consideration" in the civil-law sense and another uses it in the common-law sense, v1.0 tags both against the same FOLIO concept and emits a contradiction flag. The flag reports symptoms; it doesn't resolve causes. Downstream consumers can't tell whether the conflict is doctrinal (a real disagreement), analogical (same word, related senses), or equivocal (same word, unrelated senses). The medieval scholastics solved this in the twelfth century with the *distinguo*; v1.0 does not.

**Failure 2 — Every unit carries the same epistemic weight.** A knowledge unit extracted from the *Restatement (Second) of Torts* and a knowledge unit extracted from a trial-lawyer's blog post emit identical triples. v1.0 ranks extraction confidence; it does not rank the *nature* of the claim. A statutory definition, an appellate holding, a Circuit split report, a commentator's proposal, and a practitioner's war story need different epistemic statuses, different revision rules, and different downstream trust behavior. They get none.

**Failure 3 — No shard knows what it depends on.** A knowledge unit states "Rule 702 requires the expert's testimony to rest on sufficient facts or data." Nothing in the shard records that this depends on (a) the current text of FRE 702, (b) *Daubert*'s reliability framework, (c) the 2023 amendment to 702's preponderance standard. If any of those change, nothing propagates. v1.0 stores the shard as a point; it should store it as the terminal node of a citation-backed derivation graph.

---

## 3. Scope

**In scope for v2.0.**

- A typed shard model replacing the flat `KnowledgeUnit` schema
- A 15-field provenance-and-context envelope on every shard
- Five shard subtypes matching the extraction patterns the corpus actually exhibits
- New FOLIO vocabulary terms for analogical relations, distinctions, axiom-dependencies, Tractarian elaboration, and supersession
- RDF-star serialization as the default (RDF 1.2 / SPARQL-star / Turtle-star)
- Named graphs keyed on source document + framework + jurisdiction
- A TBox/ABox split at the storage layer, with OWL 2 EL as the TBox default profile
- Family-resemblance handling for polysemous classes (prototype clusters + embeddings, already partially present via `sentence-transformers`)
- Cluster-level validation alongside the existing unit-level confidence gate
- Web-of-belief retraction propagation with configurable resolution policies
- A meaning-postulate / empirical-assertion split in SHACL shapes
- A BFO-aligned top-level classification on every shard subject (mini-BFO, decision #2)
- **Immutable shard IRIs** with mutable relationships and mutable content under append-only audit (decisions #4, #7)
- **Provenance-hash IRI minting** (SHA-256 over source_uri + source_span; decision #6)
- **DID-signed reviewer attestations** at every governance action (decision #10)
- **Crowdsourced promotion** of hypotheses with citation requirement (decision #3)
- **Contested-state** as first-class when reviewers disagree (decision #8)
- **Supersession as distinct from retraction** — old shards remain queryable via valid-time (decision #9)
- **LLM-provider agnostic** extraction — any provider `instructor` supports (decision #5)
- Review-UI changes exposing the new metadata, polysemy forks, distinction-based reconciliation, dependency graphs, contest governance, and supersession chains

**Out of scope for v2.0 (deferred to v2.1+).**

- Full OWL 2 DL reasoner integration (v2.0 ships EL-only reasoning; DL lives in `--expressive` flag)
- SWRL or SHACL-AF advanced rule modules
- A complete BFO import (v2.0 adds a FOLIO-aligned BFO-compatible spine, not the full ontology)
- Multi-jurisdiction reasoning over conflict-of-laws rules at query time
- A public SPARQL endpoint; v2.0 ships local graph stores only
- Replacing folio-enrich's EntityRuler/LLM/semantic paths; v2.0 wraps them, not rewrites them

**Explicit non-goals** (carried from v1.0, reaffirmed for v2.0): no user-facing legal-advice UI, no merit evaluation, no generative rewriting, no real-time operation, no non-English source-text support.

---

## 3.1 Governance Model

v2.0's crowdsourced promotion (decision #3), contested-state (decision #8), and DID-signed attestations (decision #10) demand a governance model. The model is minimal by design: FOLIO Insights tracks *who asserted what* cryptographically and leaves substantive trust decisions to downstream consumers.

### 3.1.1 Reviewer roles

The system recognizes four role tiers. Roles are asserted by corpus-level `fi:RoleAssertion` records signed by the corpus admin DID:

| Role | Capabilities | Typical DID form |
|---|---|---|
| `extractor` | Mint `SimpleAssertionShard` and `HypothesisShard`; edit content on own extractions; sign attestations | `did:key` or `did:web` (can be an LLM service) |
| `reviewer` | Everything `extractor` can do, plus: promote hypotheses (with citation), demote (with evidence), edit content on any shard, propose distinguo forks, mark contested, set reconciliation strategies | `did:web` (institutional) or `did:key` (individual) |
| `arbiter` | Everything `reviewer` can do, plus: resolve contested states, approve supersession chains, override retraction cascades | `did:web` (institutional) |
| `corpus_admin` | Everything `arbiter` can do, plus: issue role assertions, fork the corpus, set retraction policies | `did:web` (institutional) |

Roles are corpus-scoped. A reviewer on the advocacy corpus is not automatically a reviewer on the IP corpus. Role changes are themselves DID-signed and append to the corpus governance log.

### 3.1.2 Promotion (hypothesis → attested)

Any reviewer may promote a `HypothesisShard` provided:

1. The promotion adds at least one `depends_on_precedents` or `depends_on_definitions` IRI (the citation requirement from decision #3)
2. The reviewer's DID holds `reviewer` role or higher
3. The resulting shard validates against SHACL

Promotion changes `epistemic_status` from `"hypothesis"` to one of `{per_se_nota_quoad_nos, demonstrable, authority_only}` according to the cited grounding. The act appends an `AttestedSignature` with `action="promote"`.

### 3.1.3 Demotion and contest (decision #8)

**Demotion** is promotion in reverse. Any reviewer who can show the citation supporting a promotion has been overruled, superseded, withdrawn, or was factually mis-cited may demote the shard back to `"hypothesis"` with a fresh TTL. Demotion is rare; the default response to invalidation is *supersession* (§6.4; decision #9), not demotion.

**Contest** is the alternative when reviewers disagree. A reviewer sets `contested=true` and adds their position to `contest_votes: {did → position}`. Other reviewers add their votes. The shard is still queryable but now bears `epistemic_status="contested"`, alerting downstream consumers. Resolution paths:

1. **Arbiter resolution** — an arbiter reviews the contest log, picks a position (or proposes a distinguo fork), signs `action="resolve_contest"`, and clears the contested flag
2. **Distinguo resolution** — reviewers agree the disagreement is semantic; the shard forks into framework-scoped children via `fi:distinguishes`
3. **Acceptance as aporetic** — the contest persists; the arbiter marks the shard `epistemic_status="aporetic"`, recording honestly that no grounding currently settles the question

### 3.1.4 Retraction cascade interaction

When a shard in the dependency graph is overruled (its citation is no longer good law), the retraction cascade (§P3) fires. For shards inheriting from the overruled shard:

- If `prefer_latest` policy applies and a superseding shard is available → dependents re-derive automatically
- If no supersession is available → dependents flip to `aporetic` and enter arbiter review
- If any reviewer disputes the cascade → affected shards enter `contested` state

This is the "retraction cascade + contested state" combination from decision #8.

### 3.1.5 Governance log

Every role change, promotion, demotion, contest, resolution, and supersession appends to a per-corpus governance log exported as a PROV-O graph at `<corpus>/governance.ttl`. The log is append-only. Any party can verify the chain by re-executing the signatures against their content hashes.

**Acceptance tests for §3.1:**

```
tests/governance/test_role_assertion_signed.py
tests/governance/test_promotion_requires_citation.py
tests/governance/test_demotion_creates_fresh_ttl.py
tests/governance/test_contested_state_records_votes.py
tests/governance/test_arbiter_can_resolve_contest.py
tests/governance/test_governance_log_is_append_only.py
tests/governance/test_governance_log_exports_as_provo.py
```

---

## 4. Core Architectural Thesis: Moderate Atomism

v2.0 commits to **moderate atomism**: the shard is the unit of representation, storage, addressing, citation, and versioning. It is never the unit of verification, meaning, or grounding. Meaning-level, verification-level, and grounding-level operations work on **clusters** — groups of shards sharing a source document, a doctrinal neighborhood, a jurisdictional scope, or a task-tree parent.

This commitment translates to seven operational principles, detailed in §8. Each principle points at a specific v1.0 shortcut and specifies its replacement. Each principle carries a concrete test.

The warrant, in one paragraph: every historical attempt to build a purely atomistic knowledge-representation system (Russell's *Principia*, Wittgenstein's *Tractatus*, Carnap's *Aufbau*) failed at roughly the same point — the atoms turned out not to be independent, not to be primitive, and not to be meaningful outside the web. The systems that survived (Aquinas's *Summa*, Spinoza's *Ethics*, Berners-Lee's Semantic Web) atomized for engineering convenience while preserving typed relationships, explicit dependencies, and revision machinery. v2.0 joins that second lineage.

---

## 5. Philosophical Foundations (Reference)

Read `PHILOSOPHY.md` for the full treatment. The patterns v2.0 imports from the tradition:

| Source | Pattern | v2.0 Implementation |
|---|---|---|
| Aristotle — *Posterior Analytics* | Axioms / postulates / definitions trichotomy | Three shard-kind tiers |
| Aristotle — categories | Per se vs. per accidens predication | `predication_mode` field |
| Aquinas — *Summa* article schema | Question / objection / sed contra / respondeo / reply | `DisputedPropositionShard` type |
| Aquinas — analogia entis | Analogical predication with prime analogate | `folio:analogousTo` with sub-properties |
| Abelard / Gratian — *Sic et Non* | Reconciliation of conflicting authorities | `ConflictingAuthoritiesShard` type |
| Scholastic glossators | Layered commentary on base texts | `GlossShard` type with typed subtypes |
| Ramon Llull — *Ars Magna* | Combinatorial generation of candidate axioms | `HypothesisShard` type (requires promotion) |
| Spinoza — *Ethics* | Explicit dependency citation on every proposition | `prov:wasDerivedFrom` + typed sub-properties (mandatory) |
| Leibniz — *characteristica universalis* | Stable URIs for primitive concepts | Preserve FOLIO IRI scheme; extend with v2.0 namespace |
| Frege — sense and reference | Intensional definition distinct from referent | `sense` / `reference` split on every shard |
| Frege — context principle | Never extract terms in isolation | Propositional-context field required |
| Wittgenstein — *Tractatus* | Numbered hierarchical identifiers | `elaborates` tree edges + decimal-path IDs |
| Wittgenstein (later) — family resemblance | Prototype + similarity for fuzzy concepts | Prototype-cluster model for polysemous classes |
| Carnap — meaning postulates | Framework-relative analytic truths | `:MeaningPostulate` axiom tier separate from empirical |
| Carnap — internal/external questions | Framework choice ≠ framework-internal fact | Framework ID on every shard |
| Quine — web of belief | Holism of confirmation; revisability | Dependency graph with propagating retraction |
| Sellars — Myth of the Given | No raw data; all observation theory-laden | Extractor + prompt + framework on every shard |
| Barry Smith — BFO | Continuant / occurrent primary split | `bfo_category` field at ingest |

---

## 6. The New Shard Model **[P0]**

### 6.1 The 15-field shard envelope

Every shard in v2.0 carries the following fields. Missing fields fail validation; empty fields must be explicit null with a documented reason.

```python
# src/folio_insights/models/shard.py

import hashlib
from typing import Literal, Optional
from datetime import datetime
from pydantic import BaseModel, Field

class Triple(BaseModel):
    """Fregean function-argument triple. The engineering primitive."""
    subject: str  # IRI
    predicate: str  # IRI
    object: str  # IRI or literal
    object_datatype: Optional[str] = None  # for literals

class AttestedSignature(BaseModel):
    """DID-signed reviewer attestation. Every reviewer action is cryptographically signed;
    downstream systems weigh signatures as they see fit (decision #10)."""
    did: str                         # e.g., "did:web:damienriehl.com", "did:key:z6Mk..."
    action: Literal[
        "extract",                   # first extraction
        "promote",                   # hypothesis → attested
        "demote",                    # attested → hypothesis (rare; see §8 P3)
        "content_edit",              # mutable content was edited
        "reparent",                  # relationships changed (parent/source swap)
        "distinguo",                 # proposed or confirmed a sense-fork
        "reconcile",                 # set reconciliation_strategy
        "contest",                   # marked contested
        "resolve_contest",           # governance-resolved a contested state
        "supersede",                 # asserted a superseding shard
    ]
    signed_at: datetime
    signature: str                   # base58-encoded ed25519 signature over canonical content
    over_content_hash: str           # SHA-256 of the content snapshot this signature covers

class ContentEdit(BaseModel):
    """Append-only audit record for content edits under an immutable ID (decision #7)."""
    edited_at: datetime
    editor_did: str
    field_path: str                  # e.g., "sense", "logical_form_imputed"
    old_value: str
    new_value: str
    rationale: str
    signature: AttestedSignature     # signed attestation of the edit

class Shard(BaseModel):
    """The 15-field envelope. Mandatory on every shard.

    IMMUTABLE across a shard's lifetime: shard_iri, extracted_at, source_uri, source_span,
    triple.subject+predicate (object may shift if relationships change per decision #4),
    provenance_hash, first_extractor_did.

    MUTABLE with append-only audit log: sense, logical_form_imputed, layer, shard_type,
    predication_mode, fork, epistemic_status, verification_method, depends_on_*,
    speech_act, bfo_category, reconciliation fields, valid_time_*, signatures.
    """

    # ========== IMMUTABLE IDENTITY (decisions #4, #6) ==========

    # Canonical shard IRI, computed at creation as:
    #   sha256(source_uri + "\n" + source_span)[:16] prefixed with namespace
    # Format: https://folio-insights.aleainstitute.ai/shard/<hex16>
    # Never changes. Never deprecated. Relationships mutate; identity does not.
    shard_iri: str = Field(pattern=r"^https://folio-insights\.aleainstitute\.ai/shard/[a-f0-9]{16}$")

    # Provenance hash — SHA-256 of (source_uri + "\n" + source_span), full 64 hex chars
    # The shard_iri embeds the first 16 chars; provenance_hash is the full verification hash.
    provenance_hash: str = Field(pattern=r"^[a-f0-9]{64}$")

    # When this shard's IRI was first minted. Never changes.
    extracted_at: datetime

    # The DID that first extracted this shard. Never changes.
    first_extractor_did: str

    # ========== THE 15-FIELD ENVELOPE ==========

    # 1. Fregean triple — the engineering primitive
    # subject + predicate are immutable; object may be updated under decision #4 (re-parenting)
    triple: Triple

    # 2. Tractarian elaboration — logical position in dependency tree
    # REPLACED decimal-path scheme. Under immutable IDs, position is expressed as a
    # first-class relationship (fi:elaborates), not encoded in the ID. A shard's
    # Tractarian position is the (potentially multi-parent) set of fi:elaborates edges
    # it asserts, recoverable by graph traversal. A human-readable breadcrumb may be
    # computed on demand for UI display but is never authoritative.
    elaborates: list[str] = Field(default_factory=list)  # IRIs of shards this elaborates

    # 3. Sense / reference pair
    sense: str                       # intensional definition, scoped by framework + time
    reference: str                   # canonical IRI (FOLIO or v2.0-minted)

    # 4. Propositional context of extraction (Frege context principle)
    source_span: str                 # verbatim source text (immutable — part of ID basis)
    source_uri: str                  # document IRI with pinpoint (immutable — part of ID basis)
    logical_form_imputed: str        # the logical form the extractor assigned

    # 5. Layer tag (Carnapian constitution layer)
    layer: Literal["L0_primitive", "L1_definitional", "L2_composed", "L3_jurisdictional"]

    # 6. Type tag
    shard_type: Literal[
        "simple_assertion",
        "disputed_proposition",
        "conflicting_authorities",
        "gloss",
        "hypothesis",
    ]

    # 7. Predication mode (Aristotle)
    predication_mode: Literal["per_se", "per_accidens"]

    # 8. Hume-fork tag
    fork: Literal["analytic", "synthetic_a_posteriori", "synthetic_a_priori"]

    # 9. Epistemic status (Aquinas) — extended for crowdsourced governance (decisions #3, #8)
    epistemic_status: Literal[
        "per_se_nota_quoad_se",      # self-evident in itself (kernel)
        "per_se_nota_quoad_nos",     # self-evident to practitioners
        "demonstrable",              # provable from kernel
        "authority_only",            # accepted only on cited authority
        "aporetic",                  # survived refutation, lacks positive grounding
        "hypothesis",                # not yet promoted (HypothesisShard only)
        "contested",                 # reviewers disagree; see governance §3.1
        "superseded",                # replaced by newer shard; still queryable (decision #9)
    ]

    # 10. Verification method (Vienna Circle protocol)
    verification_method: Literal[
        "textual_citation",          # pinpointed to statute/case/treatise
        "definitional_derivation",   # follows from definitions alone
        "inferential_chain",         # derived via demonstrable chain
        "extractor_assertion",       # LLM/ruler output, not yet verified
        "reviewer_attested",         # human reviewer affirmed
    ]

    # 11. Explicit dependencies (Spinoza + Quine)
    depends_on_axioms: list[str] = Field(default_factory=list)       # IRIs
    depends_on_definitions: list[str] = Field(default_factory=list)  # IRIs
    depends_on_precedents: list[str] = Field(default_factory=list)   # IRIs (case/statute IRIs)
    depends_on_shards: list[str] = Field(default_factory=list)       # other shard IRIs

    # 12. Framework identifier (Carnap) — jurisdiction-scoped (decision #1)
    # Frameworks are NOT versioned by year. Time-scoping happens at the shard level
    # via valid_time_start / valid_time_end. Example: "us.federal.frcp" (not "...2024")
    framework_id: str

    # 13. Language-game / speech-act context (Wittgenstein II)
    speech_act: Literal[
        "holding",
        "dictum",
        "statutory_text",
        "statutory_definition",
        "regulatory_text",
        "pleading_argument",
        "contract_term",
        "treatise_statement",
        "restatement_black_letter",
        "practitioner_advice",
        "administrative_interpretation",
    ]

    # 14. Provenance metadata (Sellars + Neurath) — now DID-anchored (decision #10)
    extractor_version: str           # folio-insights version
    extraction_prompt_hash: str      # SHA-256 of the prompt used
    extractor_model: str             # e.g., "claude-opus-4-7", "gpt-5", "llama-4-70b" (decision #5)
    signatures: list[AttestedSignature] = Field(default_factory=list)  # append-only
    content_edits: list[ContentEdit] = Field(default_factory=list)     # append-only audit log
    confidence: float = Field(ge=0.0, le=1.0)

    # 15. BFO top-level classification (Barry Smith) — mini-BFO (decision #2)
    # Values align with fi:miniBFO vocabulary; full-BFO mapping lives in bfo_mapping.ttl
    bfo_category: Literal[
        "continuant_independent",    # parties, courts, documents, jurisdictions
        "continuant_dependent",      # rights, obligations, roles
        "occurrent_process",         # proceedings, negotiations
        "occurrent_event",           # filings, holdings-as-events, breaches
    ]

    # ========== TIME-SCOPING AND SUPERSESSION (decisions #1, #9) ==========

    # Legal-time (valid-time) semantics: when the proposition holds in the world
    valid_time_start: Optional[datetime] = None  # e.g., effective date of a statute
    valid_time_end: Optional[datetime] = None    # e.g., repeal or supersession date

    # Transaction-time: when this assertion entered the graph (first write)
    transaction_time: datetime

    # Supersession chain — decision #9: supersession is NOT retraction.
    # Old shards remain queryable; valid_time_end on the old shard + this link carry the story.
    supersedes: Optional[str] = None             # IRI of shard this replaces
    superseded_by: Optional[str] = None          # IRI of shard that replaces this (set later)

    # Contested state — decision #8: reviewer disagreement is first-class
    contested: bool = False
    contest_votes: dict[str, str] = Field(default_factory=dict)  # did → position

    # ========== DEPRECATED FIELDS (migration helpers only) ==========

    # These existed in draft-1 and migrate to the new scheme:
    # - tractarian_id (decimal path)  → replaced by `elaborates` edges (decision #4)
    # - reviewer_chain (flat list)    → replaced by `signatures` (decision #10)
    # - asserter (single field)       → replaced by `first_extractor_did` + `signatures`
    # Migration tooling in §14 populates new fields from old on v1→v2 upgrade.


def mint_shard_iri(source_uri: str, source_span: str) -> tuple[str, str]:
    """Provenance-hash ID minting (decision #6).

    Returns (shard_iri, provenance_hash). ID is deterministic — re-extracting
    the same span from the same source produces the same ID, enabling natural
    deduplication across extraction runs.
    """
    h = hashlib.sha256(f"{source_uri}\n{source_span}".encode("utf-8")).hexdigest()
    iri = f"https://folio-insights.aleainstitute.ai/shard/{h[:16]}"
    return iri, h
```

**Acceptance tests for §6.1:**

```
tests/models/test_shard_envelope.py::test_all_fifteen_fields_required
tests/models/test_shard_envelope.py::test_shard_serializes_to_rdf_star
tests/models/test_shard_envelope.py::test_mint_shard_iri_is_deterministic
tests/models/test_shard_envelope.py::test_shard_iri_never_changes_across_edits
tests/models/test_shard_envelope.py::test_content_edits_are_append_only
tests/models/test_shard_envelope.py::test_signatures_verify_against_content_hash
tests/models/test_shard_envelope.py::test_supersession_preserves_old_shard
tests/models/test_shard_envelope.py::test_contested_state_records_votes
```

Every shard loaded from a v1.0 corpus migrates by: retaining its triple (1); computing `shard_iri` + `provenance_hash` from (`source_uri`, `source_span`) via `mint_shard_iri` (decision #6 — deterministic, so re-running migration is idempotent); converting the old `tractarian_id` into `elaborates` edges by parsing the decimal path into parent links (decision #4 — IDs don't migrate; relationships migrate); copying existing confidence into (14); converting `reviewer_chain` entries into `AttestedSignature` entries if DIDs are available, else leaving them as deprecated annotations flagged for attestation upgrade; defaulting (5)=`L3_jurisdictional`, (6)=`simple_assertion`, (7)=`per_accidens`, (8)=`synthetic_a_posteriori`, (9)=`authority_only`, (10)=`extractor_assertion`, (15)=inferred from FOLIO parent class via the mini-BFO mapping table. Framework IDs strip any trailing year from v1-style identifiers (decision #1). Missing fields get default values flagged with `migration:v1_default=true` annotations so reviewers can upgrade incrementally.

### 6.2 Five shard subtypes

Each subtype extends the envelope with type-specific fields. All subtypes share the 15-field base.

#### 6.2.1 `SimpleAssertionShard`

A bare Fregean triple with full provenance. The protocol-layer default. Most v1.0 knowledge units migrate to this type.

```python
class SimpleAssertionShard(Shard):
    shard_type: Literal["simple_assertion"] = "simple_assertion"
    # no additional fields; the envelope carries everything
```

#### 6.2.2 `DisputedPropositionShard` **[P0]**

The Summa-article schema. Use this for any proposition the corpus reveals as genuinely contested — circuit splits, Restatement majority/minority, treatise-vs-treatise disagreement.

```python
class Objection(BaseModel):
    cites: str       # IRI of cited authority
    argues: str      # the objection proposition
    strength: float  # 0..1

class Reply(BaseModel):
    objection_index: int
    replies_via: str      # "distinguo", "authority_supersession", "scope_limitation", "factual_distinction"
    argument: str

class DisputedPropositionShard(Shard):
    shard_type: Literal["disputed_proposition"] = "disputed_proposition"
    utrum: str                           # well-formed binary question
    objections: list[Objection]
    sed_contra: Objection                # the brief authoritative counter-cite
    respondeo: str                       # determinative answer
    uses_distinctions: list[str] = []    # IRIs of distinction shards invoked
    replies: list[Reply]
```

#### 6.2.3 `ConflictingAuthoritiesShard` **[P0]**

The sic-et-non structure. Use this for circuit splits, UCC-vs-common-law divergences, jurisdictional disagreements where *both sides* carry weight.

```python
class AuthorityPosition(BaseModel):
    authority_iri: str
    position: str
    jurisdiction: str
    weight: Literal["binding", "persuasive", "minority", "majority"]

class ConflictingAuthoritiesShard(Shard):
    shard_type: Literal["conflicting_authorities"] = "conflicting_authorities"
    sic: list[AuthorityPosition]
    non: list[AuthorityPosition]
    reconciliation_strategy: Literal[
        "sense_distinction",          # different senses of a term (invoke folio:distinguishes)
        "contextual_limitation",      # each rule applies in its context
        "voice_attribution",          # one side is dicta, majority, etc.
        "textual_correction",         # textual-variant resolution
        "retraction_later",           # later authority supersedes
        "subsequent_overruling",      # explicit overrule
        "jurisdictional_scoping",     # each rule governs its jurisdiction
        "unreconciled",               # genuinely open
    ]
    reconciliation_note: str
```

#### 6.2.4 `GlossShard` **[P0]**

Layered commentary on a base shard. Commentary from treatises, law review articles, practitioner notes. Each gloss carries a type.

```python
class GlossShard(Shard):
    shard_type: Literal["gloss"] = "gloss"
    glosses: str                           # shard IRI being annotated
    gloss_kind: Literal[
        "clarificatoria",   # clarifies the base
        "extensiva",        # extends reach
        "restrictiva",      # narrows scope
        "dissentiens",      # disagrees
        "historica",        # historical development note
    ]
    gloss_text: str
```

#### 6.2.5 `HypothesisShard` **[P1]**

A machine-generated or inductively-projected candidate shard that has not yet earned attested status. Llullian generator output lives here until a reviewer with at least one citation dependency promotes it (decision #3 — crowdsourced promotion).

```python
class HypothesisShard(Shard):
    shard_type: Literal["hypothesis"] = "hypothesis"
    generation_method: Literal[
        "combinatorial",      # enumerated from primitive predicates
        "inductive",          # generalized from instance cluster
        "analogical",         # projected from sibling concept
    ]
    promotion_requirements: list[str]  # what grounding would promote this
    ttl_days: int = 90                  # auto-expire if not promoted
```

**Acceptance test for §6.2:**

```
tests/models/test_shard_subtypes.py  # covers all five types
tests/models/test_disputed_proposition_round_trip.py
tests/models/test_conflicting_authorities_reconciliation.py
tests/models/test_gloss_references_valid_shard.py
tests/models/test_hypothesis_expires_after_ttl.py
```

### 6.3 Shard IRI scheme (decisions #4, #6)

v2.0 mints shard IRIs under the `https://folio-insights.aleainstitute.ai/shard/` namespace using a **provenance hash**:

```
https://folio-insights.aleainstitute.ai/shard/<hex16>
https://folio-insights.aleainstitute.ai/shard/a3f9c2d1e4b5f678
```

The 16 hex characters are the first 16 chars of SHA-256 over `source_uri + "\n" + source_span`. The full 64-char hash lives in the `provenance_hash` field for verification. Collisions at 16 chars are astronomically unlikely in any realistic corpus (birthday bound ~2³² shards before a 50% collision risk); the migration tool runs a collision check and escalates to 20 hex chars per corpus if a collision is ever detected.

**Identity invariants (decision #4 — immutable IDs, mutable relationships):**

- The `shard_iri` never changes for the lifetime of the shard.
- The `shard_iri` is never deprecated; superseded shards retain their IRIs and stay queryable (decision #9).
- Re-extracting the same (source, span) pair produces the same IRI — natural deduplication.
- Re-parenting a shard (changing its `elaborates` edges, its `depends_on_*` edges, or even the `object` of its triple) changes relationships only; the IRI holds.
- Content edits (to `sense`, `logical_form_imputed`, `epistemic_status`, etc.) update in place with an append-only `content_edits` audit log; the IRI holds.

**Tractarian position under immutable IDs.** Draft-1 encoded tree position in the ID (`advocacy:rule702:1.2.3`). Decision #4 moves position into a first-class graph edge: the `elaborates` field lists IRIs of parent shards. A shard can elaborate multiple parents (matching FOLIO's multi-parent design); its position in any given view is a graph query, not a lexical parse. UI layers can compute a human-readable breadcrumb (`Rule 702 › Reliability › Preponderance`) on demand for display; that breadcrumb is never authoritative and never stored in the ID.

**Why provenance-hash IDs beat UUIDs, counters, and content hashes** for legal-KR at scale:

- Deterministic — no coordination needed across extraction runs
- Source-anchored — the ID *points back to its origin* at the bit level
- Dedup-native — identical extractions collapse automatically
- Audit-friendly — any claim "this shard came from span X of document Y" is hash-verifiable
- Orthogonal to content — content can change freely without breaking identity (which a content-hash scheme would forbid)

### 6.4 Content versioning under immutable IDs (decision #7)

Content is mutable. The ID is not. This asymmetry demands a discipline.

**Write path for content edits.**

```python
# src/folio_insights/revision/content_edit.py

async def edit_shard_content(
    shard_iri: str,
    field_path: str,        # dotted path, e.g., "sense" or "respondeo"
    new_value: str,
    editor_did: str,
    rationale: str,
    signing_key: Ed25519PrivateKey,
) -> ContentEdit:
    """Apply a content edit to a shard. Appends to the audit log; never mutates history.

    Raises if:
      - field_path names an immutable field (shard_iri, provenance_hash, source_uri,
        source_span, extracted_at, first_extractor_did, triple.subject, triple.predicate)
      - editor_did lacks permission for this field (see §3.1 governance)
      - the new value fails SHACL validation after application
    """
    shard = await store.get(shard_iri)
    old_value = get_field(shard, field_path)

    # Compute content hash over canonical serialization BEFORE the edit
    pre_hash = canonical_content_hash(shard)

    edit = ContentEdit(
        edited_at=utcnow(),
        editor_did=editor_did,
        field_path=field_path,
        old_value=old_value,
        new_value=new_value,
        rationale=rationale,
        signature=sign_attestation(
            did=editor_did,
            action="content_edit",
            over_content_hash=pre_hash,
            signing_key=signing_key,
        ),
    )

    # Apply edit in place; append to audit log
    set_field(shard, field_path, new_value)
    shard.content_edits.append(edit)

    # Re-validate
    validate_shard(shard)
    await store.put(shard)
    return edit
```

**Immutable fields (hard enforcement at the storage layer):**

- `shard_iri`
- `provenance_hash`
- `extracted_at`
- `first_extractor_did`
- `source_uri`
- `source_span`
- `triple.subject` (identity-defining)
- `triple.predicate` (identity-defining)
- All entries in `content_edits` (append-only)
- All entries in `signatures` (append-only)

**Mutable fields** (edit via `edit_shard_content`, audit log grows):

- `triple.object` (re-parenting is a core use case — decision #4)
- `sense`, `logical_form_imputed`
- All envelope fields 5–11, 13, 15 (layer, type, mode, fork, epistemic_status, verification_method, dependencies, speech_act, bfo_category)
- `elaborates`
- `valid_time_start`, `valid_time_end`
- `supersedes`, `superseded_by`
- `contested`, `contest_votes`
- `confidence` (may re-score as reviewers attest)

**Reading historical content.** Any prior state of a shard is reconstructible by replaying `content_edits` in reverse from the current state. A convenience API returns the shard as-of any transaction time:

```python
async def get_shard_at(shard_iri: str, as_of: datetime) -> Shard:
    """Reconstruct historical shard state by replaying content_edits in reverse."""
```

**Acceptance tests for §6.4:**

```
tests/revision/test_content_edits_append_only.py
tests/revision/test_immutable_fields_reject_edits.py
tests/revision/test_historical_reconstruction.py
tests/revision/test_edit_signature_verifies.py
```

### 6.5 DID-signed attestations (decision #10)

Every reviewer action — extraction, promotion, demotion, content edit, re-parenting, distinguo, reconciliation, contest, supersession — is cryptographically signed by the reviewer's Decentralized Identifier (DID). Downstream systems inspect signatures and weigh them by whatever trust model they choose; FOLIO Insights itself imposes no reputation hierarchy beyond a small set of governance roles defined in §3.1.

**Supported DID methods (v2.0-beta):**

- `did:key` — self-sovereign, no registry, good for individual reviewers
- `did:web` — domain-anchored, good for institutional reviewers (e.g., `did:web:alea.aleainstitute.ai`)
- `did:plc` — AT Protocol, good for high-churn federated networks

**Signature payload** — canonical content hash:

Given a `Shard`, the canonical content hash is SHA-256 over a deterministic JSON serialization: keys sorted lexicographically, all datetimes in RFC 3339 UTC, all IRIs normalized to NFC. The hash excludes the `signatures` and `content_edits` lists themselves (signatures cover content, not the signature list). This gives every attestation a stable target.

```python
def canonical_content_hash(shard: Shard) -> str:
    """SHA-256 over canonical JSON serialization, excluding signatures and content_edits."""
    payload = shard.model_dump(exclude={"signatures", "content_edits"})
    canonical = json.dumps(payload, sort_keys=True, default=canonical_datetime)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

**What the signature proves.** An `AttestedSignature` over `content_hash H` with `action A` by `did D` at `signed_at T` proves: *D asserted A about the shard whose content hashed to H at time T*. It does not prove D is a lawyer, a judge, or an expert — trust is a downstream question.

**Signature verification in SHACL.**

```turtle
fi:SignedActionShape a sh:NodeShape ;
    sh:targetClass fi:AttestedSignature ;
    sh:property [
        sh:path fi:signature ;
        sh:minCount 1 ;
        sh:sparql [
            sh:message "Signature must verify against the DID's public key over over_content_hash." ;
            sh:select """
                SELECT ?this WHERE {
                    ?this fi:did ?did ; fi:signature ?sig ; fi:overContentHash ?hash .
                    FILTER NOT EXISTS { ?this fi:verified true }
                }
            """ ;
        ] ;
    ] .
```

Verification is performed at ingest and cached in a `fi:verified true` annotation; failed verifications block the shard's storage write.

**Acceptance tests for §6.5:**

```
tests/attestation/test_did_key_sign_verify.py
tests/attestation/test_did_web_sign_verify.py
tests/attestation/test_canonical_content_hash_stable.py
tests/attestation/test_unverified_signature_blocks_storage.py
```

---

## 7. New FOLIO Vocabulary **[P0]**

v2.0 adds a namespaced vocabulary under `https://folio-insights.aleainstitute.ai/vocab/`. The terms extend rather than replace the FOLIO ontology. The v2.0 vocabulary declares alignment with FOLIO via `owl:imports` and adds new properties and classes below.

### 7.1 New properties

```turtle
@prefix fi: <https://folio-insights.aleainstitute.ai/vocab/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

# Analogical predication (Aquinas's analogia entis)
fi:analogousTo a owl:ObjectProperty ;
    rdfs:label "analogous to" ;
    rdfs:comment "Two classes share an analogical (not univocal, not equivocal) relation. Requires sub-properties fi:primeAnalogate and fi:proportionalRelation." .

fi:primeAnalogate a owl:ObjectProperty ;
    rdfs:subPropertyOf fi:analogousTo ;
    rdfs:comment "The focal sense of an analogical term; other senses relate proportionally to this one." .

fi:proportionalRelation a owl:DatatypeProperty ;
    rdfs:comment "Describes the proportion relating two analogical senses." .

# Distinction (scholastic distinguo)
fi:distinguishes a owl:ObjectProperty ;
    rdfs:label "distinguishes" ;
    rdfs:comment "Distinguishes two senses of a polysemous term, forking the term into sense-specific classes." .

fi:distinctionKind a owl:DatatypeProperty ;
    rdfs:comment "Values: realis, rationis, rationis_cum_fundamento_in_re, analogica" .

# Subalternation (Aristotle / Aquinas)
fi:subalternatedTo a owl:ObjectProperty ;
    rdfs:label "subalternated to" ;
    rdfs:comment "An ontology module's axioms derive from a higher module's theorems. Regulations subalternate to statutes; statutes to constitutions." .

# Tractarian elaboration
fi:elaborates a owl:ObjectProperty ;
    rdfs:label "elaborates" ;
    rdfs:comment "A shard elaborates its parent in the Tractarian numbered tree." ,
                 "If shard N.M.P elaborates shard N.M, then N.M.P constitutes further detail of N.M." .

# Explicit dependencies (Spinoza)
fi:dependsOnAxiom a owl:ObjectProperty ;
    rdfs:subPropertyOf <http://www.w3.org/ns/prov#wasDerivedFrom> .

fi:dependsOnDefinition a owl:ObjectProperty ;
    rdfs:subPropertyOf <http://www.w3.org/ns/prov#wasDerivedFrom> .

fi:dependsOnPrecedent a owl:ObjectProperty ;
    rdfs:subPropertyOf <http://www.w3.org/ns/prov#wasDerivedFrom> .

fi:derivedFromKernel a owl:ObjectProperty ;
    rdfs:comment "The shard traces back (transitively) to the FOLIO Insights axiom kernel." .

# Closure marker (Russellian explicit totality)
fi:closedUnder a owl:AnnotationProperty ;
    rdfs:comment "Explicit totality marker. Names the scope under which closed-world semantics applies." .

# Framework identifier (Carnap)
fi:framework a owl:ObjectProperty ;
    rdfs:comment "The meaning-postulate framework under which the shard's sense is fixed." .

# Epistemic status (Aquinas)
fi:epistemicStatus a owl:DatatypeProperty ;
    rdfs:comment "Values: per_se_nota_quoad_se, per_se_nota_quoad_nos, demonstrable, authority_only, aporetic, hypothesis, contested, superseded." .

# Predication mode (Aristotle)
fi:predicationMode a owl:DatatypeProperty ;
    rdfs:comment "Values: per_se, per_accidens." .

# Supersession (decision #9) — NOT retraction; old shard remains queryable
fi:supersedes a owl:ObjectProperty ;
    rdfs:label "supersedes" ;
    rdfs:comment "This shard replaces the target shard prospectively. The target's valid_time_end should align with this shard's valid_time_start. The target remains queryable for historical reasoning." .

fi:supersededBy a owl:ObjectProperty ;
    owl:inverseOf fi:supersedes ;
    rdfs:label "superseded by" .

# Valid-time (legal time) properties — time-scoping at the shard level (decision #1)
fi:validTimeStart a owl:DatatypeProperty ;
    rdfs:range <http://www.w3.org/2001/XMLSchema#dateTime> ;
    rdfs:comment "When the proposition begins to hold in the legal world (effective date)." .

fi:validTimeEnd a owl:DatatypeProperty ;
    rdfs:range <http://www.w3.org/2001/XMLSchema#dateTime> ;
    rdfs:comment "When the proposition ceases to hold in the legal world (repeal, supersession, or expiry)." .

fi:transactionTime a owl:DatatypeProperty ;
    rdfs:range <http://www.w3.org/2001/XMLSchema#dateTime> ;
    rdfs:comment "When the assertion entered the graph (immutable)." .

# Contest (decision #8) — reviewer disagreement as first-class
fi:contested a owl:DatatypeProperty ;
    rdfs:range <http://www.w3.org/2001/XMLSchema#boolean> .

fi:contestVote a owl:ObjectProperty ;
    rdfs:comment "Links a shard to a ContestVote blank node carrying reviewer DID and position." .

# DID-signed attestations (decision #10)
fi:AttestedSignature a owl:Class ;
    rdfs:comment "Cryptographic attestation of a reviewer action over a specific content hash." .

fi:did a owl:DatatypeProperty ;
    rdfs:comment "Decentralized Identifier of the signer; supports did:key, did:web, did:plc." .

fi:signature a owl:DatatypeProperty ;
    rdfs:comment "Base58-encoded ed25519 signature over the canonical content hash." .

fi:overContentHash a owl:DatatypeProperty ;
    rdfs:comment "The SHA-256 content hash the signature covers." .

fi:signedAction a owl:DatatypeProperty ;
    rdfs:comment "One of: extract, promote, demote, content_edit, reparent, distinguo, reconcile, contest, resolve_contest, supersede." .

# Governance roles (decision #3, §3.1)
fi:RoleAssertion a owl:Class ;
    rdfs:comment "A corpus-admin-signed assertion granting a role to a DID within a corpus scope." .

fi:hasRole a owl:DatatypeProperty ;
    rdfs:comment "Values: extractor, reviewer, arbiter, corpus_admin." .

# Content edit audit (decision #7)
fi:ContentEdit a owl:Class ;
    rdfs:comment "Append-only record of a mutation to a mutable shard field." .

fi:editedField a owl:DatatypeProperty .
fi:oldValue a owl:DatatypeProperty .
fi:newValue a owl:DatatypeProperty .
fi:editRationale a owl:DatatypeProperty .

# Provenance hash (decision #6)
fi:provenanceHash a owl:DatatypeProperty ;
    rdfs:comment "Full SHA-256 hash of source_uri + '\n' + source_span; the first 16 hex chars form the shard IRI suffix." .
```

### 7.2 New classes

```turtle
# Axiom tiers
fi:CommonAxiom a owl:Class ;
    rdfs:comment "Aristotelian koinon: applies across all legal domains (LNC, identity)." .

fi:Postulate a owl:Class ;
    rdfs:comment "Aristotelian aitema: jurisdiction-specific existence claim." .

fi:Definition a owl:Class ;
    rdfs:comment "Aristotelian horos: essence-specification for a concept." .

fi:MeaningPostulate a owl:Class ;
    rdfs:subClassOf fi:Definition ;
    rdfs:comment "Carnapian framework-relative analytic axiom. Not empirical." .

# Framework
fi:Framework a owl:Class ;
    rdfs:comment "A meaning-postulate framework (jurisdiction, practice area, time-scope)." .

# BFO-aligned mini-spine (decision #2 — mini-BFO with documented mapping to full BFO)
# The v2.0 spine is intentionally a small subset, self-contained, no hard import of bfo-2.0.owl.
# A companion file `bfo_mapping.ttl` documents the correspondence to full BFO 2020 classes
# (e.g., fi:Continuant owl:equivalentClass bfo:BFO_0000002 "continuant").

fi:Continuant a owl:Class ;
    rdfs:comment "Mini-BFO continuant. Maps to bfo:BFO_0000002 in bfo_mapping.ttl." .

fi:IndependentContinuant a owl:Class ;
    rdfs:subClassOf fi:Continuant ;
    rdfs:comment "Entities that do not depend on another entity for existence. Maps to bfo:BFO_0000004." .

fi:DependentContinuant a owl:Class ;
    rdfs:subClassOf fi:Continuant ;
    rdfs:comment "Entities requiring a bearer (rights, roles, obligations). Maps to bfo:BFO_0000020 (specifically dependent continuant)." .

fi:Role a owl:Class ;
    rdfs:subClassOf fi:DependentContinuant ;
    rdfs:comment "Realizable dependent continuant. Maps to bfo:BFO_0000023." .

fi:Occurrent a owl:Class ;
    rdfs:comment "Entities that unfold in time. Maps to bfo:BFO_0000003." .

fi:Process a owl:Class ;
    rdfs:subClassOf fi:Occurrent ;
    rdfs:comment "Extended temporal occurrent (proceedings, negotiations). Maps to bfo:BFO_0000015." .

fi:Event a owl:Class ;
    rdfs:subClassOf fi:Occurrent ;
    rdfs:comment "Point-like temporal occurrent (filings, holdings-as-events). Mini-BFO treats this as a process-boundary; full BFO models it as process_boundary (bfo:BFO_0000035) in bfo_mapping.ttl." .

# Governance classes (§3.1)
fi:Framework a owl:Class ;
    rdfs:comment "A meaning-postulate framework (jurisdiction + body; time-scoping is per-shard per decision #1)." .

fi:GovernanceLog a owl:Class ;
    rdfs:comment "Append-only log of role assertions, promotions, demotions, contests, resolutions, and supersessions for a corpus." .
```

**Acceptance tests for §7:**

- `folio-insights export --include-vocab` emits the new vocabulary as a separate TTL file alongside the corpus OWL.
- `folio-insights export --include-bfo-mapping` emits `bfo_mapping.ttl` with the documented mapping from mini-BFO to full BFO 2020 (decision #2).
- `pyshacl` validates that every `fi:analogousTo` assertion carries a `fi:primeAnalogate` sub-assertion.
- Every shard's `framework_id` resolves to a `fi:Framework` individual.
- Every `fi:supersedes` edge implies the superseded shard has a `fi:validTimeEnd` matching the new shard's `fi:validTimeStart` (decision #9).
- Every `fi:AttestedSignature` instance verifies against the named DID's published key over the referenced content hash (decision #10).

---

## 8. The Seven Design Principles as Implementation Requirements **[P0]**

### P1 — Atomize for tractability; validate at the cluster level

**What v1.0 does:** Unit-level confidence gate (5-stage scoring), unit-level SHACL validation.

**What v2.0 adds:** A `ShardCluster` abstraction and cluster-level validation pass. Clusters form along four axes: source document, Tractarian subtree, doctrinal neighborhood (shared FOLIO concept ancestor), jurisdictional scope.

**Implementation:**

```
src/folio_insights/validation/cluster_validator.py
    - ClusterBuilder: groups shards by each axis
    - ConsistencyChecker: uses OWL reasoner to detect cross-shard contradictions within clusters
    - CoverageChecker: flags gaps (e.g., a task tree leaf with no authority shards)
    - CrossReferenceChecker: shards citing each other must share a compatible framework
```

**Acceptance test:** `pytest tests/validation/test_cluster_consistency.py` — given a corpus with a planted contradiction across two shards from different sources, the cluster validator flags the pair and proposes reconciliation strategies. Unit-level validation passes both shards individually.

### P2 — Every shard records its framework

**What v1.0 does:** Records source document and extraction prompt version.

**What v2.0 adds:** Mandatory `framework_id`, `signatures` (DID-anchored, decision #10), `extraction_prompt_hash`, `speech_act`, `valid_time_start`/`valid_time_end` (decision #1). Frameworks get first-class identifiers and `fi:Framework` instances with `fi:framework` links on every shard.

**Time-scoping (decision #1).** Frameworks are *not* versioned by year. A single framework `us.federal.frcp` represents the Federal Rules of Civil Procedure as a living body; individual shards carry `valid_time_start` and `valid_time_end` to express when their content held. This matches how lawyers think: "Rule 702 as amended in 2023" is Rule 702 *during* a time-window, not a separate rule. Supersession chains (§6.4, decision #9) link the shards across time within the framework; the framework itself stays singular.

Historical queries use temporal SPARQL with valid-time bounds:

```sparql
# What was FRE 702 at valid-time T?
SELECT ?shard ?sense WHERE {
  ?shard fi:framework <fi-framework:us.federal.frcp> ;
         fi:reference <frcp:rule702> ;
         fi:sense ?sense ;
         fi:validTimeStart ?vs .
  OPTIONAL { ?shard fi:validTimeEnd ?ve }
  FILTER(?vs <= $T && (!BOUND(?ve) || $T < ?ve))
}
```

**Implementation:**

```
src/folio_insights/models/framework.py
    - Framework: pydantic model with id, label, jurisdiction, parent_framework
      (NO time_scope field — time lives on the shard)
    - FrameworkRegistry: CRUD + resolution + SKOS concept scheme export
src/folio_insights/pipeline/ingest/framework_detector.py
    - Detects framework from source-document metadata, corpus-level config, LLM-inferred scope
    - Infers valid_time_start/end from statutory effective dates, amendment notes,
      case decision dates, Restatement publication years
```

Framework IDs follow the pattern `<jurisdiction>.<body>` — `us.federal.frcp`, `us.delaware.dgcl`, `uk.england.common_law`, `us.restatement_2d.contracts`. Time-scoping lives on the shard, not in the ID. The registry ships with a starter set; new frameworks get minted per corpus and are DID-signed by the corpus admin.

**Acceptance test:** Loading a v1.0 corpus without frameworks surfaces a migration warning and assigns each shard a `framework_id` based on source-document jurisdiction metadata, stripping any year suffix from v1-style IDs. Shards extracted from a statute with known amendment dates get appropriate `valid_time_start`/`valid_time_end` windows. Every new extraction records the detected framework or fails the confidence gate.

### P3 — No shard is unrevisable; model the web explicitly

**What v1.0 does:** Ships OWL, treats it as authoritative until the next run.

**What v2.0 adds:** A dependency graph over shards, a **three-part revision protocol** separating retraction, supersession, and contest; and `ExtractionHypothesis` as a first-class alternative-extraction container.

**Three kinds of revision (decisions #8, #9).** v2.0 distinguishes three categorically different responses to changed authority:

| Response | When to use | Effect on old shard | Effect on dependents |
|---|---|---|---|
| **Supersession** | New rule replaces old prospectively; old rule still accurately described the past state (e.g., FRE 702 pre/post-2023) | `valid_time_end` set; `superseded_by` points to replacement; remains queryable | Historical queries return old shard; current queries return new |
| **Retraction** | The shard was wrong — bad extraction, mis-citation, overruled by binding authority | `epistemic_status="aporetic"` or actual deletion (with tombstone) | Cascade fires per policy; dependents re-derive, flip aporetic, or enter review |
| **Contest** | Reviewers disagree about whether the shard is correct | `contested=true`; `contest_votes` populated | Dependents see the contested flag; downstream systems weigh accordingly |

**Implementation:**

```
src/folio_insights/revision/
    dependency_graph.py   — builds the DAG from shard.depends_on_* fields
    retraction.py         — propagates retractions according to policy
    supersession.py       — mints successor shards; sets valid_time boundaries;
                            cascade preserves old shards as historical
    contest.py            — manages contest_votes; arbiter-resolution workflow
    policies.py           — configurable: prefer_latest, prefer_authority,
                            prefer_most_specific_jurisdiction
    hypothesis.py         — ExtractionHypothesis model; competing extractions coexist
```

**Retraction protocol:**

1. User or automated process retracts shard S (e.g., the cited case is overruled).
2. System finds all shards `{D1, D2, ...}` where `S ∈ D.depends_on_*`.
3. For each dependent, apply policy: re-derive if possible; mark `aporetic` if not; escalate to reviewer if conflict.
4. If any reviewer disputes the cascade (decision #8), affected shards enter `contested` state instead.
5. Log the propagation cascade to the governance log (§3.1.5).

**Supersession protocol (decision #9):**

1. User asserts new shard N with `N.supersedes = S.shard_iri`.
2. System sets `S.valid_time_end = N.valid_time_start` (default: now; configurable).
3. System sets `S.epistemic_status = "superseded"` and `S.superseded_by = N.shard_iri`.
4. S remains queryable; historical queries with `valid_time <= S.valid_time_end` return S.
5. No cascade fires — supersession is not retraction. Dependents of S that need updating are identified for reviewer attention but not automatically retracted.
6. Log to governance log.

**Contest protocol (decision #8):**

1. Reviewer asserts `contested=true` on shard S with their position.
2. `contest_votes[reviewer_did] = position` is appended.
3. S remains queryable with `epistemic_status="contested"`.
4. Resolution via arbiter action (signed `resolve_contest`), distinguo fork, or acceptance as aporetic.

**Acceptance tests:**

- Retracting a case shard triggers re-evaluation of every rule-shard citing it. With `prefer_latest` policy and a superseding statute present, dependents re-derive automatically. Without a supersession, dependents flip to `aporetic` and enter review.
- Superseding FRE 702-pre-2023 with FRE 702-post-2023 does *not* retract the old shard; both remain queryable; historical queries return the correct shard for their time window.
- A reviewer contests a shard that another reviewer just promoted; the shard enters contested state; an arbiter resolves it by distinguo fork; the contest log records the full exchange with signatures.

### P4 — Separate TBox from ABox; constrain TBox to OWL 2 EL by default

**What v1.0 does:** Exports a single OWL file mixing definitions and assertions.

**What v2.0 adds:** Separate named graphs for TBox (terminology) and ABox (assertions). TBox defaults to OWL 2 EL profile; SROIQ features require `--expressive` flag and emit a warning.

**Implementation:**

```
src/folio_insights/services/owl_serializer.py
    - emit_tbox(graph: Graph, profile: Literal["EL", "DL"]) — ELK reasoner for EL
    - emit_abox(graph: Graph)
    - emit_combined(tbox: Graph, abox: Graph) — default export still unifies
src/folio_insights/services/reasoner.py
    - ELKAdapter (default)
    - HermiTAdapter (for --expressive)
```

Add profile validation using `owlapi` bindings or a pure-Python EL profile checker. Any TBox assertion violating EL bounds (e.g., inverse-functional properties, number restrictions beyond 0/1) fails with a clear error pointing to the offending axiom and the specific EL constraint it violates.

**Acceptance test:** Exporting a corpus whose TBox contains `owl:inverseFunctionalProperty` without `--expressive` fails with a clear error pointing to the offending axiom. With `--expressive`, it exports and uses HermiT.

### P5 — Embrace OWA; mark CWA islands explicitly

**What v1.0 does:** Default OWA; some dashboards silently treat absence as false.

**What v2.0 adds:** A `fi:closedUnder` annotation on scopes requiring closed-world semantics. A query-time closed-world layer that runs only on marked scopes. Every dashboard counter declares its world assumption in UI tooltips.

**Implementation:**

```
src/folio_insights/query/closed_world.py
    - ClosedWorldScope: scope IRI + list of classes/properties treated as closed
    - ClosedWorldQuery: runs SPARQL with NAF (negation as failure) only within scope
```

**Acceptance test:** A SPARQL query for "all parties to a contract" runs under CWA only if the contract's scope carries `fi:closedUnder`; otherwise returns a query that explicitly notes it may be incomplete.

### P6 — Family-resemblance handling for polysemous legal concepts

**What v1.0 does:** Sentence-transformers for semantic tagging; treats all concepts as OWL classes.

**What v2.0 adds:** A three-tier structure for polysemous concepts:

1. A **SKOS concept grouping** that spans jurisdictions
2. **Jurisdiction-specific OWL classes** under the grouping with local TBox axioms
3. A **prototype cluster** of paradigm instances with embedding vectors

Polysemy detection triggers distinction-fork: when the cluster validator detects same-IRI shards with incompatible axioms across frameworks, the system proposes forking the IRI into framework-scoped children linked by `fi:distinguishes`.

**Implementation:**

```
src/folio_insights/polysemy/
    detector.py         — flags same-concept shards with framework-conflicting axioms
    distinguo.py        — proposes sense-forks with evidence
    prototype_cluster.py — stores paradigm instances + embedding centroid per class
    similarity_query.py  — fuzzy retrieval separate from OWL subsumption
```

**Separation invariant:** Subsumption queries go through the reasoner. Similarity queries go through the prototype cluster. The API must not let the caller confuse them.

**Acceptance test:** A corpus containing "consideration" in common-law and civil-law contexts gets forked into `fi:Consideration_CommonLaw` and `fi:Consideration_CivilLaw` under a shared `skos:Concept`, with `fi:analogousTo` linking them and `fi:primeAnalogate` pointing to the common-law sense (configurable).

### P7 — BFO-aligned top-level split

**What v1.0 does:** Uses FOLIO's top-level categories.

**What v2.0 adds:** A BFO-aligned spine (§7.2) maps FOLIO top-level categories to continuant/occurrent. Every shard subject gets typed at ingest; the ingest pipeline rejects shards whose subject cannot be BFO-typed.

**Implementation:**

```
src/folio_insights/bfo/
    spine.py           — FOLIO → BFO mapping table, hand-curated
    classifier.py      — rule-based classifier; falls back to LLM for unmapped cases
```

**Acceptance test:** Every `KnowledgeUnit` → `Shard` migration succeeds with a BFO category assigned. Corpus-level report: distribution of continuant-independent / continuant-dependent / process / event shards per source.

---

## 9. Pipeline Changes **[P0]**

The v1.0 four-stage pipeline retains its shape. Each stage acquires shard-model awareness.

```
┌──────────┐    ┌─────────────┐    ┌──────────────┐    ┌──────────────┐
│ Stage 1  │ -> │ Stage 2     │ -> │ Stage 3      │ -> │ Stage 4      │
│ Ingest + │    │ Task +      │    │ OWL Mapping  │    │ Validation + │
│ Shard    │    │ Polysemy    │    │ + Shard      │    │ Export       │
│ Extract  │    │ Discovery   │    │ Serialization│    │              │
└──────────┘    └─────────────┘    └──────────────┘    └──────────────┘
     │                │                   │                   │
     v                v                   v                   v
 Typed shards    Task tree +         Named-graph OWL    Validated OWL,
 (5 subtypes)    polysemy forks +    (TBox + ABox)      TTL-star, JSON-LD,
 with full       cluster            with RDF-star       HTML, Markdown,
 envelope        consistency        annotations         + audit report
```

### 9.1 Stage 1 changes

- Replace `KnowledgeUnit` with `Shard` + subtype routing
- Add framework detector (§P2)
- Add BFO classifier (§P7)
- Add predication-mode + Hume-fork + epistemic-status inference (LLM-assisted, confidence-gated)
- Emit `SimpleAssertionShard` for routine extractions; escalate to `DisputedPropositionShard` / `ConflictingAuthoritiesShard` when disagreement markers appear in source text (patterns: "some courts hold... others...", "but see", "contra", "circuit split")
- Preserve v1.0's four-path FOLIO tagging; add sense/reference split at tag time

### 9.2 Stage 2 changes

- Task discovery runs unchanged against the SimpleAssertionShard subset
- Add polysemy detector pass (§P6): cluster same-IRI shards by framework; flag framework-conflicting axioms; propose distinguo forks
- Add cluster-level validator (§P1): runs ELK reasoner per cluster; reports inconsistencies with cluster context
- NLI contradiction detection (v1.0 feature) becomes one input to `ConflictingAuthoritiesShard` generation

### 9.3 Stage 3 changes

- Named graph per source document (v1.0 emits flat graph; v2.0 emits multi-graph dataset)
- TBox emitted to `<corpus>/tbox.ttl`; ABox per source to `<corpus>/abox/<doc_id>.ttl`
- RDF-star emission for per-shard metadata (confidence, extractor_version, valid_time)
- Dependency edges emitted as `prov:wasDerivedFrom` + typed sub-properties
- v2.0 vocabulary emitted as `<corpus>/vocab.ttl`

### 9.4 Stage 4 changes

- SHACL shapes for every shard subtype (§10)
- OWL 2 EL profile check on TBox (warn-only mode for migration; strict mode for new corpora)
- Cluster validation report (§P1)
- Retraction-propagation audit report for any shards retracted since last export (§P3)
- Export formats updated: HTML browser renders shard subtype badges, distinction forks, dependency graphs; Markdown export includes shard-type-aware formatting

### 9.5 CLI changes

Existing commands retain their interfaces. New flags:

```
folio-insights extract <dir> --corpus <name> \
    --framework-detect=auto|manual|none \
    --bfo-classify=strict|permissive \
    --shard-subtype-routing=auto|force-simple \
    --llm-provider=anthropic|openai|google|ollama|... \
    --llm-model=<model_id> \
    --signing-key=<path>       # DID signing key for attestations (decision #10)

folio-insights discover <corpus> \
    --polysemy-detect=true \
    --distinguo-threshold=0.6 \
    --cluster-validate=true

folio-insights export <corpus> \
    --named-graphs=true \
    --rdf-star=true \
    --tbox-profile=EL|DL \
    --expressive  # same as --tbox-profile=DL; emits warning
    --include-bfo-mapping  # emits bfo_mapping.ttl (decision #2)
    --as-of=<timestamp>    # historical export at valid-time T (decision #9)

# New commands
folio-insights retract <shard-iri> --policy=prefer_latest
folio-insights promote <hypothesis-shard-iri> --grounding=<citation-iri>
folio-insights distinguo <iri> --into=<framework1>,<framework2>,...
folio-insights framework register <id> --jurisdiction=<j>                     # NO time_scope per decision #1

# DID and attestation commands (decision #10)
folio-insights did generate --method=key                # emits a new did:key + signing key
folio-insights did register <did> --role=reviewer --corpus=<corpus>  # corpus_admin only
folio-insights sign <shard-iri> --action=<action>       # attest an action on a shard
folio-insights verify <corpus>                          # verify every signature in the corpus

# Content edit commands (decision #7)
folio-insights edit <shard-iri> --field=<path> --value=<new> --rationale=<text>
folio-insights history <shard-iri>                      # replay content_edits audit log
folio-insights at <shard-iri> --as-of=<timestamp>       # reconstruct historical content

# Supersession and contest commands (decisions #8, #9)
folio-insights supersede <old-iri> --with=<new-iri> --effective=<timestamp>
folio-insights contest <shard-iri> --position=<text>
folio-insights resolve-contest <shard-iri> --resolution=<arbiter_decision>
folio-insights demote <shard-iri> --evidence=<citation-iri>
```

**LLM-provider agnostic extraction (decision #5).** v2.0 runs extraction through `instructor` against any supported provider. Provider selection is per-corpus config and per-command flag via `--llm-provider` and `--llm-model` flags on the `extract` command. Credentials come from provider-specific env vars (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `OLLAMA_HOST`, etc.). The `extractor_model` field records which model was used for any given extraction, enabling cross-provider comparison studies at the shard level.

**Historical export (`--as-of`, decision #9).** Running `folio-insights export <corpus> --as-of=2020-06-01T00:00:00Z` produces an export as the corpus *would have looked* at that valid-time: shards whose `valid_time_start > T` or `valid_time_end ≤ T` are excluded; superseded shards remain if they were still in effect at T. This enables historical-doctrine queries without manual filtering.

---

## 10. SHACL Shapes **[P0]**

v2.0 adds shape-per-subtype SHACL modules under `src/folio_insights/shapes/`.

Baseline: every shard must validate against `shared/envelope.shacl.ttl`. Each subtype adds its own shape file.

```turtle
# shared/envelope.shacl.ttl
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix fi: <https://folio-insights.aleainstitute.ai/vocab/> .

fi:ShardEnvelopeShape a sh:NodeShape ;
    sh:targetClass fi:Shard ;
    # IRI format (provenance-hash, decision #6)
    sh:property [
        sh:path fi:shardIri ;
        sh:minCount 1 ; sh:maxCount 1 ;
        sh:pattern "^https://folio-insights\\.aleainstitute\\.ai/shard/[a-f0-9]{16}$" ;
    ] ;
    sh:property [
        sh:path fi:provenanceHash ;
        sh:minCount 1 ; sh:maxCount 1 ;
        sh:pattern "^[a-f0-9]{64}$" ;
    ] ;
    # Framework (decision #1 — no year suffix; time lives on shard)
    sh:property [
        sh:path fi:framework ;
        sh:minCount 1 ;
        sh:class fi:Framework ;
    ] ;
    # BFO category (mini-BFO, decision #2)
    sh:property [
        sh:path fi:bfoCategory ;
        sh:minCount 1 ;
        sh:in ( "continuant_independent" "continuant_dependent"
                "occurrent_process" "occurrent_event" ) ;
    ] ;
    # Attested signatures (decision #10) — at least one for any asserted shard
    sh:property [
        sh:path fi:signatures ;
        sh:minCount 1 ;
        sh:message "Every shard must carry at least one AttestedSignature." ;
    ] ;
    # First extractor DID (immutable)
    sh:property [
        sh:path fi:firstExtractorDid ;
        sh:minCount 1 ; sh:maxCount 1 ;
        sh:pattern "^did:(key|web|plc):.+" ;
    ] ;
    # ... all 15 fields
    .
```

Minimum shape suite for v2.0:

- `shared/envelope.shacl.ttl` — 15-field base (above)
- `shapes/simple_assertion.shacl.ttl`
- `shapes/disputed_proposition.shacl.ttl` — enforces objection + sed_contra + respondeo + replies
- `shapes/conflicting_authorities.shacl.ttl` — enforces sic + non + reconciliation_strategy
- `shapes/gloss.shacl.ttl` — enforces valid `glosses` target shard exists
- `shapes/hypothesis.shacl.ttl` — enforces ttl_days and promotion_requirements
- `shapes/framework.shacl.ttl` — validates framework registry entries (no time_scope; decision #1)
- `shapes/analogical.shacl.ttl` — enforces primeAnalogate + proportionalRelation when analogousTo asserted
- `shapes/dependencies.shacl.ttl` — enforces at least one depends_on_* when epistemic_status=demonstrable
- **`shapes/supersession.shacl.ttl`** — enforces that `fi:supersedes` edges have matching valid_time boundaries; superseded shard has `epistemic_status="superseded"` and `superseded_by` pointing back (decision #9)
- **`shapes/attestation.shacl.ttl`** — enforces every `fi:AttestedSignature` has a DID, action, content hash, and signature; verification cached as `fi:verified` annotation (decision #10)
- **`shapes/governance.shacl.ttl`** — enforces role assertions are signed by corpus_admin; promotion requires reviewer+ role; demotion requires reviewer+ role; arbiter actions require arbiter+ role (§3.1, decision #3)
- **`shapes/content_edit.shacl.ttl`** — enforces `content_edits` is append-only (no deletions, no reorders); each entry has a verified signature; `field_path` names a mutable field (decision #7)
- **`shapes/contest.shacl.ttl`** — when `contested=true`, `contest_votes` must have at least 2 entries; when `epistemic_status="contested"`, `contested` must be true (decision #8)
- **`shapes/immutable_fields.shacl.ttl`** — enforces that immutable fields (shard_iri, provenance_hash, extracted_at, first_extractor_did, source_uri, source_span, triple.subject, triple.predicate) have exactly one value and cannot be edited (decision #4)

**Acceptance tests:** `pyshacl` runs all shapes against a v2.0 export corpus and passes. Any deliberate violation in `tests/fixtures/invalid_shards/` produces the expected violation message. The new fixtures include: supersession without valid_time alignment; signature verification failure; content edit on immutable field; contested state with only one vote; promotion without reviewer role; arbiter action with reviewer DID.

---

## 11. Storage Layer **[P1]**

v1.0 stores extracted units in SQLite + JSON artifacts. v2.0 extends with:

- **Shard store**: SQLite (keep v1.0 for compatibility) + optional backing triplestore for queries
- **Graph store**: default to `rdflib`-on-SQLite; optional adapter for Oxigraph (Rust, fast, RDF-star native) or Jena Fuseki
- **Vector store**: `sentence-transformers` embeddings in a local FAISS index (v1.0 already uses this for semantic ruler; v2.0 extends for prototype clusters)

```
src/folio_insights/storage/
    shard_store.py        — SQLite (primary)
    graph_store/
        base.py           — Protocol
        rdflib_adapter.py — default
        oxigraph_adapter.py  # optional
        fuseki_adapter.py    # optional
    vector_store/
        base.py
        faiss_adapter.py  — default (local)
```

Storage selection via env var: `FOLIO_INSIGHTS_GRAPH_STORE=rdflib|oxigraph|fuseki`. Default stays `rdflib` for compatibility. Oxigraph recommended for corpora > 100K shards.

**Acceptance test:** Round-trip a 10K-shard corpus through each adapter; diff the resulting graphs — they must be isomorphic modulo blank-node labels.

---

## 12. Review UI Changes **[P1]**

The v1.0 viewer (SvelteKit + FastAPI) already has the five-pane workflow. v2.0 adds:

- **Shard subtype badges** in the unit list (S, D, C, G, H for the five types)
- **Metadata inspector** showing all 15 envelope fields, expandable per shard
- **Dependency graph visualizer** — interactive graph of shard ancestors and descendants; click a shard to navigate
- **Polysemy fork UI** — when the polysemy detector flags a concept, the UI surfaces a proposed distinguo with evidence; reviewer can accept, reject, or modify the fork
- **Conflict reconciliation UI** — for ConflictingAuthoritiesShard, reviewer picks reconciliation strategy from dropdown; system records and propagates
- **Retraction UI** — reviewer retracts a shard; UI shows cascade preview before committing
- **Framework filter** — filter the entire corpus by framework; cross-framework comparison view

New routes:

```
GET  /api/shards/{iri}                         — full shard with metadata
GET  /api/shards/{iri}/dependencies            — upstream + downstream graph
POST /api/shards/{iri}/retract                 — with policy param
POST /api/shards/{iri}/promote                 — hypothesis → attested
POST /api/distinguo                            — propose or confirm a sense-fork
GET  /api/frameworks                           — framework registry
GET  /api/clusters/{scope}/{scope_id}/validate — cluster validation report
```

**Acceptance test:** Playwright e2e tests covering (a) reviewer retraction cascade, (b) polysemy fork acceptance, (c) conflict reconciliation, (d) framework-filtered browsing.

---

## 13. Testing Plan **[P0]**

The v1.0 test suite passes 197 tests. v2.0 adds:

- **Model tests** (~40 new): each shard subtype, envelope validators, provenance-hash IRI minting (decision #6), immutability invariants (decision #4), elaborates-edge traversal
- **SHACL tests** (~45 new): one test per shape, plus cross-shape validation suites; includes new shapes for supersession, attestation, governance, content_edit, contest, immutable_fields
- **Pipeline tests** (~50 new): framework detection, BFO classification, polysemy detection, cluster validation, distinguo fork generation
- **Revision tests** (~35 new): retraction propagation under each policy; supersession with valid-time boundaries (decision #9); contested state workflow (decision #8); hypothesis promotion with citation requirement (decision #3); demotion with evidence; dependency graph correctness
- **Attestation tests** (~20 new): DID-key sign/verify, DID-web sign/verify, canonical content hash stability, unverified signature blocks storage, signature over correct content hash (decision #10)
- **Governance tests** (~15 new): role assertion signed by corpus_admin; promotion requires reviewer+ role; demotion requires reviewer+ role; arbiter can resolve contest; governance log is append-only; governance log exports as PROV-O (§3.1)
- **Content edit tests** (~15 new): content edits append-only; immutable fields reject edits; historical reconstruction via edit replay; edit signature verifies (decision #7)
- **Round-trip tests** (~15 new): storage adapters, named graph preservation, RDF-star round-trip, v1.0 → v2.0 migration, provenance-hash ID idempotence, signature round-trip
- **Philosophical-fidelity tests** (~15 new): test that the design patterns land as claimed — a `DisputedPropositionShard` cannot validate without objections; a `ConflictingAuthoritiesShard` cannot validate without reconciliation_strategy; a demonstrable shard cannot validate without at least one `depends_on_*`; a contested shard cannot have epistemic_status other than `contested`; a superseded shard must have valid_time_end matching its successor's valid_time_start; every attested action must have a verifying signature
- **LLM-provider tests** (~10 new): extraction through Anthropic, OpenAI, Google, and a local Ollama endpoint produces equivalent shard shape (content will differ per model quality; schema must not) — decision #5

Total target: ~425 tests at v2.0 GA. The full suite must pass on every PR to `v2.0` branch.

Regression: the v1.0 test suite must continue to pass under the `FOLIO_INSIGHTS_V1_COMPAT=true` flag through the v2.0-beta period. Drop the compat flag at v2.0-final.

---

## 14. Migration Strategy **[P0]**

### 14.1 In-repo migration

v1.0 corpora migrate in place. A new `folio-insights migrate` command:

```
folio-insights migrate <corpus> \
    --from-version=1.0 \
    --to-version=2.0 \
    --dry-run             # default; writes plan to stdout
    --apply               # actually migrate
    --rollback            # revert to v1.0 snapshot
```

The migration:

1. Snapshots the v1.0 corpus to `<corpus>/.v1.0-snapshot/` (reversible via `--rollback`)
2. Mints v2.0 `shard_iri` for each v1.0 KnowledgeUnit via `mint_shard_iri(source_uri, source_span)` — deterministic, idempotent (decision #6)
3. Converts v1.0 `tractarian_id` decimal paths into `elaborates` edges (parses `advocacy:rule702:1.2.3` → `elaborates` edge to shard with `1.2`) — decision #4
4. Populates `provenance_hash` (full 64-char SHA-256)
5. Sets `first_extractor_did` from corpus config (defaults to `did:web:alea.aleainstitute.ai`)
6. Converts v1.0 `reviewer_chain` entries into `AttestedSignature` entries where DIDs are available; leaves stringly-named reviewers as `migration:v1_reviewer` annotations flagged for signature upgrade (decision #10)
7. Loads each KnowledgeUnit → SimpleAssertionShard with field defaults from §6.1
8. Runs framework detector against each shard's source document; strips any year suffix from v1-style IDs (`us.federal.frcp.2024` → `us.federal.frcp`); infers `valid_time_start`/`valid_time_end` from document metadata (decision #1)
9. Runs BFO classifier with `permissive` mode (unknowns get `continuant_independent` + a flag for review); emits `bfo_mapping.ttl` mapping to full BFO 2020 (decision #2)
10. Creates an initial `fi:GovernanceLog` for the corpus with the migration event signed by the admin DID
11. Re-runs cluster validator to surface newly-detected cross-shard issues
12. Prints migration report: N shards migrated, M frameworks detected, K unclassifiable subjects, Q cross-cluster conflicts needing review, R reviewers needing DID upgrade

**Idempotence guarantee.** Re-running `migrate --apply` against an already-migrated corpus is a no-op — the deterministic ID scheme (decision #6) ensures shards re-compute to the same IRIs; the content-edit audit log (decision #7) records any delta from the prior migration pass as an edit, not a replacement. This makes migration safely resumable after partial failure.

### 14.2 Downstream consumers

Consumers of v1.0 exports get a compatibility mode. The v2.0 exporter emits a `--compat=v1` flag that suppresses new vocabulary terms, collapses named graphs, and drops RDF-star annotations. This gives downstream RAG pipelines and SPARQL endpoints a grace period.

Announcement cadence:
- **v2.0-alpha** (week 0): breaking schema changes behind `FOLIO_INSIGHTS_V2_ALPHA=true`
- **v2.0-beta** (week 4): default to v2.0; compat flag available
- **v2.0-rc** (week 8): compat flag deprecated with warnings
- **v2.0-final** (week 12): compat flag removed

---

## 15. Documentation Requirements **[P1]**

New docs to write or update:

- `README.md` — update v1.0 → v2.0 positioning; add "philosophy in one paragraph" section
- `PHILOSOPHY.md` — the companion philosophical-foundations doc (ships with v2.0)
- `docs/architecture/SHARD_MODEL.md` — the 15-field envelope, the five subtypes, the provenance-hash IRI scheme (decision #6), immutability invariants (decision #4)
- `docs/architecture/VOCABULARY.md` — the new FOLIO Insights vocabulary
- `docs/architecture/FRAMEWORKS.md` — how to register frameworks, the starter set, why frameworks are NOT versioned by year (decision #1)
- `docs/architecture/BFO_MAPPING.md` — the mini-BFO spine and its mapping to full BFO 2020 (decision #2)
- `docs/architecture/REVISION.md` — the three-part protocol: retraction, supersession, contest (decisions #8, #9)
- `docs/architecture/GOVERNANCE.md` — roles, promotion/demotion, contest resolution, the governance log (§3.1, decisions #3, #8)
- `docs/architecture/ATTESTATION.md` — DID methods, canonical content hash, signature verification (decision #10)
- `docs/architecture/CONTENT_EDITS.md` — mutable/immutable fields, edit workflow, historical reconstruction (decision #7)
- `docs/guides/MIGRATION_V1_TO_V2.md` — step-by-step for existing corpus owners, including DID upgrade path
- `docs/guides/POLYSEMY_HANDLING.md` — when to distinguo, when to tolerate
- `docs/guides/CLUSTER_VALIDATION.md` — how to read cluster reports and respond
- `docs/guides/LLM_PROVIDER_CONFIG.md` — configuring Anthropic, OpenAI, Google, and local models (decision #5)
- `docs/guides/HISTORICAL_QUERIES.md` — using `--as-of` and valid-time bounds for historical doctrine research (decision #9)
- Update `.planning/research/ARCHITECTURE.md` — record the v2.0 architectural shift with full rationale

---

## 16. Risks and Mitigations

**Risk 1: Metadata bloat slows ingestion.** 15 fields per shard multiplies the extraction-LLM cost.

*Mitigation:* Lazy-fill non-critical fields. Require envelope fields 1, 2, 3, 4, 12, 14, 15 at extraction time; infer fields 5–11, 13 asynchronously in a follow-up pass. Benchmark against the v1.0 advocacy corpus and target < 30% extraction-time regression.

**Risk 2: Polysemy forks explode the class hierarchy.** Aggressive distinguo generates O(concepts × jurisdictions) classes.

*Mitigation:* Set `distinguo_threshold` conservatively (0.6 default). Require cluster-validator evidence (framework-conflicting axioms) before proposing a fork. Human review gates every proposed fork before commit.

**Risk 3: Named graphs complicate downstream queries.** Tools that consume v1.0's single-graph output break on v2.0's multi-graph dataset.

*Mitigation:* Emit both forms by default. `<corpus>/combined.ttl` stays as the single-graph v1.0-compatible file. `<corpus>/abox/*.ttl` and `<corpus>/tbox.ttl` add the v2.0 multi-graph view.

**Risk 4: BFO classification fails on abstract legal concepts.** "A right" — continuant-dependent. "A holding" — occurrent-event or continuant-dependent? Disagreement exists.

*Mitigation:* Ship the starter mapping table with explicit disclaimer; flag ambiguous cases for review; make mapping overridable per corpus. A holding-as-speech-act is an occurrent; a holding-as-binding-rule is a continuant-dependent. The `speech_act` field helps disambiguate.

**Risk 5: Philosophical warrant gets abandoned under schedule pressure.** "We'll do the framework split later" means we never will.

*Mitigation:* Every PR merging to `v2.0` branch must trace its changes to a warrant in this PRD or explicitly cite why it diverges. PRs with missing warrants get blocked.

---

## 17. Success Criteria

v2.0 ships when:

1. **All P0 requirements land** with acceptance tests passing
2. **The v1.0 advocacy corpus migrates cleanly** — no data loss, no semantic regressions, cluster validator finds at most 10% additional conflicts (real ones that v1.0 missed)
3. **Extraction performance stays within 30%** of v1.0 on the same corpus
4. **The review-UI reviewer-time-per-shard stays within 50%** of v1.0 (envelope inspection and polysemy forks cost some time; worth it)
5. **One new corpus ingested end-to-end** using v2.0 features from scratch — validates that v2.0 handles a greenfield extraction, not just migration
6. **PHILOSOPHY.md ships alongside v2.0** as documentation of the grounding

---

## 18. Appendix A — Example Shards

All three examples reflect the v2.0 envelope per decisions #1–#10: provenance-hash IRIs, framework IDs without year suffix, DID-signed attestations, and valid-time scoping.

### A.1 A SimpleAssertionShard

```json
{
  "shard_type": "simple_assertion",
  "shard_iri": "https://folio-insights.aleainstitute.ai/shard/a3f9c2d1e4b5f678",
  "provenance_hash": "a3f9c2d1e4b5f678...full64chars...",
  "extracted_at": "2026-04-19T14:23:11Z",
  "first_extractor_did": "did:web:alea.aleainstitute.ai",
  "triple": {
    "subject": "https://folio.aleainstitute.ai/Contract",
    "predicate": "https://folio-insights.aleainstitute.ai/vocab/hasElement",
    "object": "https://folio.aleainstitute.ai/Consideration"
  },
  "elaborates": [
    "https://folio-insights.aleainstitute.ai/shard/b8e1c5a2d3f9e456"
  ],
  "sense": "Consideration as bargained-for exchange under the Restatement (Second) of Contracts § 71.",
  "reference": "https://folio.aleainstitute.ai/Consideration",
  "source_span": "§ 17. Requirement of a Bargain... the formation of a contract requires a bargain in which there is a manifestation of mutual assent to the exchange and a consideration.",
  "source_uri": "https://www.ali.org/publications/show/contracts/#ch2",
  "logical_form_imputed": "∀c:Contract . ∃x:Consideration . hasElement(c, x)",
  "layer": "L1_definitional",
  "shard_type": "simple_assertion",
  "predication_mode": "per_se",
  "fork": "analytic",
  "epistemic_status": "per_se_nota_quoad_nos",
  "verification_method": "textual_citation",
  "depends_on_definitions": [
    "https://folio.aleainstitute.ai/Contract",
    "https://folio.aleainstitute.ai/Consideration"
  ],
  "depends_on_precedents": [],
  "depends_on_axioms": [],
  "depends_on_shards": [
    "https://folio-insights.aleainstitute.ai/shard/b8e1c5a2d3f9e456"
  ],
  "framework_id": "us.restatement_2d.contracts",
  "speech_act": "restatement_black_letter",
  "extractor_version": "folio-insights-2.0.0-beta.3",
  "extraction_prompt_hash": "sha256:7f2c1e...",
  "extractor_model": "claude-opus-4-7",
  "signatures": [
    {
      "did": "did:web:alea.aleainstitute.ai",
      "action": "extract",
      "signed_at": "2026-04-19T14:23:11Z",
      "signature": "z5wK8Jf...base58...",
      "over_content_hash": "e7a2b9c1d4f8..."
    },
    {
      "did": "did:web:damienriehl.com",
      "action": "reviewer_attested",
      "signed_at": "2026-04-20T09:15:44Z",
      "signature": "z3xP9Qm...base58...",
      "over_content_hash": "e7a2b9c1d4f8..."
    }
  ],
  "content_edits": [],
  "confidence": 0.94,
  "bfo_category": "continuant_dependent",
  "valid_time_start": "1981-05-17T00:00:00Z",
  "valid_time_end": null,
  "transaction_time": "2026-04-19T14:23:11Z",
  "supersedes": null,
  "superseded_by": null,
  "contested": false,
  "contest_votes": {}
}
```

**Notes on A.1:**

- `shard_iri` is the 16-hex-char provenance-hash ID (decision #6)
- `elaborates` is now a graph edge, not encoded in the ID (decision #4)
- `framework_id` omits the `.1981` year suffix (decision #1); `valid_time_start` carries the effective date instead
- `signatures` replaces `reviewer_chain`; both extraction and reviewer attestation are cryptographically signed (decision #10)
- `extractor_model` records which LLM produced this (decision #5)
- `content_edits` is empty — the shard has never been edited; if edited, entries would append here (decision #7)

### A.2 A ConflictingAuthoritiesShard (circuit split with valid-time)

```json
{
  "shard_type": "conflicting_authorities",
  "shard_iri": "https://folio-insights.aleainstitute.ai/shard/c4b8d2e1a9f3506a",
  "provenance_hash": "c4b8d2e1a9f3506a...full64chars...",
  "extracted_at": "2026-04-19T15:02:33Z",
  "first_extractor_did": "did:web:alea.aleainstitute.ai",
  "triple": {
    "subject": "https://folio.aleainstitute.ai/ExpertTestimony",
    "predicate": "https://folio-insights.aleainstitute.ai/vocab/governedBy",
    "object": "https://folio.aleainstitute.ai/Rule702ReliabilityStandard"
  },
  "elaborates": [
    "https://folio-insights.aleainstitute.ai/shard/d1e5f7a2b9c8302f"
  ],
  "sense": "Application of FRE 702's reliability standard — circuits diverged on preponderance-of-evidence threshold before the 2023 amendment clarified it.",
  "reference": "https://folio.aleainstitute.ai/ExpertTestimony",
  "source_span": "Rule 702. Testimony by Expert Witnesses. A witness who is qualified as an expert by knowledge, skill, experience, training, or education may testify in the form of an opinion or otherwise if the proponent demonstrates to the court that it is more likely than not that...",
  "source_uri": "https://www.law.cornell.edu/rules/fre/rule_702",
  "logical_form_imputed": "∀t:ExpertTestimony . admissible(t) ↔ satisfiesReliability(t, ...)",
  "layer": "L3_jurisdictional",
  "predication_mode": "per_accidens",
  "fork": "synthetic_a_posteriori",
  "epistemic_status": "authority_only",
  "verification_method": "textual_citation",
  "depends_on_precedents": [
    "https://folio.aleainstitute.ai/case/Daubert_v_Merrell_Dow",
    "https://folio.aleainstitute.ai/case/Sardis_v_Overhead_Door",
    "https://folio.aleainstitute.ai/case/In_re_Paoli_RR_Yard"
  ],
  "framework_id": "us.federal.frcp",
  "speech_act": "holding",
  "sic": [
    {
      "authority_iri": "https://folio.aleainstitute.ai/case/Sardis_v_Overhead_Door",
      "position": "Gatekeeping requires preponderance on every reliability factor.",
      "jurisdiction": "us.federal.ca4",
      "weight": "binding"
    }
  ],
  "non": [
    {
      "authority_iri": "https://folio.aleainstitute.ai/case/In_re_Paoli_RR_Yard",
      "position": "Gatekeeping is a lower threshold for admission; weight goes to the jury.",
      "jurisdiction": "us.federal.ca3",
      "weight": "binding"
    }
  ],
  "reconciliation_strategy": "jurisdictional_scoping",
  "reconciliation_note": "Each circuit's rule governed within its jurisdiction. The 2023 FRE 702 amendment adopted the Fourth Circuit position.",
  "extractor_version": "folio-insights-2.0.0-beta.3",
  "extraction_prompt_hash": "sha256:9a3b2f...",
  "extractor_model": "claude-opus-4-7",
  "signatures": [
    {
      "did": "did:web:alea.aleainstitute.ai",
      "action": "extract",
      "signed_at": "2026-04-19T15:02:33Z",
      "signature": "z7kR4Lp...base58...",
      "over_content_hash": "f3d1e8a5b2c9..."
    }
  ],
  "content_edits": [],
  "confidence": 0.88,
  "bfo_category": "continuant_dependent",
  "valid_time_start": "1993-06-28T00:00:00Z",
  "valid_time_end": "2023-12-01T00:00:00Z",
  "transaction_time": "2026-04-19T15:02:33Z",
  "supersedes": null,
  "superseded_by": "https://folio-insights.aleainstitute.ai/shard/e7c3a5b1d9f40812",
  "contested": false,
  "contest_votes": {}
}
```

**Notes on A.2:**

- `framework_id` = `us.federal.frcp` (no year suffix — decision #1)
- The circuit split had a valid-time window: June 1993 (Daubert) through December 2023 (FRE 702 amendment)
- `superseded_by` points to the post-2023 shard. The split itself is now *historical* but still queryable (decision #9); a query with `--as-of=2020-06-01` returns this shard as the governing rule at that time
- The post-2023 successor shard has `supersedes` = this IRI and `valid_time_start` = `2023-12-01T00:00:00Z` — matching this shard's `valid_time_end` exactly (SHACL-enforced)

### A.3 A DisputedPropositionShard (doctrinal question, contested state)

```json
{
  "shard_type": "disputed_proposition",
  "shard_iri": "https://folio-insights.aleainstitute.ai/shard/f2a9b3c1e5d74068",
  "provenance_hash": "f2a9b3c1e5d74068...full64chars...",
  "extracted_at": "2026-04-19T16:45:02Z",
  "first_extractor_did": "did:web:alea.aleainstitute.ai",
  "triple": {
    "subject": "https://folio.aleainstitute.ai/AttorneyClientPrivilege",
    "predicate": "https://folio-insights.aleainstitute.ai/vocab/appliesTo",
    "object": "https://folio.aleainstitute.ai/AIAssistedCommunications"
  },
  "elaborates": [
    "https://folio-insights.aleainstitute.ai/shard/a1b2c3d4e5f60789"
  ],
  "sense": "Whether attorney-client privilege attaches to communications routed through third-party AI services.",
  "reference": "https://folio.aleainstitute.ai/AttorneyClientPrivilege",
  "source_span": "The question whether attorney-client privilege attaches to communications routed through third-party AI services has divided courts. Some apply the Kovel doctrine...",
  "source_uri": "https://folio.aleainstitute.ai/commentary/ai_privilege_2026",
  "logical_form_imputed": "privileged(c) ↔ ∃a:Attorney . directs(a, ai) ∧ necessary(ai, c) ∧ confidentialityControls(ai)",
  "layer": "L3_jurisdictional",
  "predication_mode": "per_accidens",
  "fork": "synthetic_a_posteriori",
  "epistemic_status": "contested",
  "verification_method": "inferential_chain",
  "depends_on_precedents": [
    "https://folio.aleainstitute.ai/case/US_v_Kovel",
    "https://folio.aleainstitute.ai/case/Heppner_AI_Privilege"
  ],
  "framework_id": "us.federal.evidence",
  "speech_act": "treatise_statement",
  "utrum": "Whether attorney-client privilege attaches to communications routed through third-party AI services.",
  "objections": [
    {
      "cites": "https://folio.aleainstitute.ai/doctrine/third_party_doctrine",
      "argues": "Communications shared with a third-party provider waive privilege.",
      "strength": 0.7
    },
    {
      "cites": "https://folio.aleainstitute.ai/doctrine/subject_matter_waiver",
      "argues": "Disclosure to non-attorneys waives subject-matter privilege.",
      "strength": 0.5
    }
  ],
  "sed_contra": {
    "cites": "https://folio.aleainstitute.ai/case/Heppner_AI_Privilege",
    "argues": "AI services acting under attorney direction qualify as agents under the Kovel doctrine; privilege persists.",
    "strength": 0.8
  },
  "respondeo": "Privilege attaches when the AI service acts as an attorney's agent under conditions analogous to Kovel (direction, necessity, confidentiality controls). Without those controls, waiver occurs.",
  "uses_distinctions": [
    "https://folio-insights.aleainstitute.ai/shard/7a8b9c1d2e3f4506"
  ],
  "replies": [
    {
      "objection_index": 0,
      "replies_via": "distinguo",
      "argument": "The third-party doctrine distinguishes agents from independent third parties; AI services can be agents."
    },
    {
      "objection_index": 1,
      "replies_via": "scope_limitation",
      "argument": "Subject-matter waiver applies only to intentional disclosure, not to processing by agents under confidentiality controls."
    }
  ],
  "extractor_version": "folio-insights-2.0.0-beta.3",
  "extraction_prompt_hash": "sha256:4c8e1a...",
  "extractor_model": "claude-opus-4-7",
  "signatures": [
    {
      "did": "did:web:alea.aleainstitute.ai",
      "action": "extract",
      "signed_at": "2026-04-19T16:45:02Z",
      "signature": "z9mN2Kq...base58...",
      "over_content_hash": "b4e7f2c8a1d5..."
    },
    {
      "did": "did:web:damienriehl.com",
      "action": "contest",
      "signed_at": "2026-04-21T11:30:18Z",
      "signature": "z5xT7Wp...base58...",
      "over_content_hash": "b4e7f2c8a1d5..."
    },
    {
      "did": "did:web:some-other-reviewer.example",
      "action": "contest",
      "signed_at": "2026-04-22T08:14:29Z",
      "signature": "z8kL3Jn...base58...",
      "over_content_hash": "b4e7f2c8a1d5..."
    }
  ],
  "content_edits": [],
  "confidence": 0.71,
  "bfo_category": "continuant_dependent",
  "valid_time_start": "2024-01-01T00:00:00Z",
  "valid_time_end": null,
  "transaction_time": "2026-04-19T16:45:02Z",
  "contested": true,
  "contest_votes": {
    "did:web:damienriehl.com": "The respondeo overstates Kovel's reach; newer decisions distinguish AI services from human agents.",
    "did:web:some-other-reviewer.example": "The respondeo correctly applies Kovel; the objection arguments are weaker than stated."
  }
}
```

**Notes on A.3:**

- `epistemic_status = "contested"` because reviewers disagree (decision #8)
- `contested: true` and `contest_votes` record the disagreement with signed attestations
- Two reviewer DIDs have signed `action: "contest"`, each stating their position
- An `arbiter` DID can later resolve this by signing `action: "resolve_contest"` with a determinative position or by forking the shard via distinguo
- Valid-time starts 2024 (a recent doctrinal question); no end yet — the issue remains live

---

## 19. Appendix B — Pipeline Code Sketch

```python
# src/folio_insights/pipeline/stage1_ingest.py

from folio_insights.models import (
    SimpleAssertionShard, DisputedPropositionShard,
    ConflictingAuthoritiesShard, GlossShard
)
from folio_insights.framework import FrameworkDetector
from folio_insights.bfo import BFOClassifier
from folio_insights.polysemy import PolysemyDetector
from folio_insights.shapes import validate_shard

async def extract_shards(doc_path: Path, corpus: str) -> list[Shard]:
    """Stage 1: ingest + shard extraction."""
    doc = load_document(doc_path)
    framework = await framework_detector.detect(doc)

    # Existing v1.0 pipeline: boundary detection + LLM extraction + FOLIO tagging
    raw_units = await v1_extraction_pipeline(doc)

    shards = []
    for unit in raw_units:
        # Route to subtype based on source-text markers
        if has_disagreement_markers(unit.source_span):
            shard = await build_conflicting_authorities_shard(unit, framework)
        elif has_disputed_question_markers(unit.source_span):
            shard = await build_disputed_proposition_shard(unit, framework)
        elif is_commentary_on_base(unit):
            shard = await build_gloss_shard(unit, framework)
        else:
            shard = await build_simple_assertion_shard(unit, framework)

        # Classify BFO category
        shard.bfo_category = await bfo_classifier.classify(shard.triple.subject)

        # Infer per_se / per_accidens, Hume fork, epistemic status
        shard = await enrich_epistemic_metadata(shard)

        # Validate envelope
        validate_shard(shard)  # raises on SHACL violation

        shards.append(shard)

    return shards
```

---

## 20. Appendix C — SPARQL Query Examples

**Find all disputed propositions in the contracts framework with unresolved objections:**

```sparql
PREFIX fi: <https://folio-insights.aleainstitute.ai/vocab/>

SELECT ?shard ?utrum WHERE {
  GRAPH ?g {
    ?shard a fi:DisputedPropositionShard ;
           fi:utrum ?utrum ;
           fi:framework <https://.../framework/us.federal.frcp> ;
           fi:epistemicStatus "aporetic" .
  }
}
```

**Find every shard that would be affected by retracting a specific statute:**

```sparql
PREFIX fi: <https://folio-insights.aleainstitute.ai/vocab/>
PREFIX prov: <http://www.w3.org/ns/prov#>

SELECT ?dependent ?depth WHERE {
  ?dependent (fi:dependsOnPrecedent|fi:dependsOnAxiom|fi:dependsOnDefinition|prov:wasDerivedFrom)+ <https://.../fre/702> .
}
```

**Find all analogical pairs across common-law and civil-law frameworks:**

```sparql
PREFIX fi: <https://folio-insights.aleainstitute.ai/vocab/>

SELECT ?classA ?classB ?proportion WHERE {
  ?classA fi:analogousTo ?classB ;
          fi:framework ?fwA .
  ?classB fi:framework ?fwB .
  ?classA fi:proportionalRelation ?proportion .
  FILTER(?fwA != ?fwB)
}
```

---

## 21. Resolved Design Questions

All ten design questions are resolved. This section records each question, the resolution, and the tradeoffs considered so future contributors understand the reasoning. New questions that arise during implementation should be appended as §21.11, §21.12, etc., preserving this record as an append-only design log.

### 21.1 Framework granularity — **RESOLVED: one framework with time-scoped shards**

**Question:** Should `us.federal.frcp.2024` and `us.federal.frcp.2023` be separate frameworks, or one framework with time-scoped shards?

**Resolution:** One framework per jurisdiction + body (e.g., `us.federal.frcp`). Time-scoping lives on the shard via `valid_time_start` / `valid_time_end` properties (decision #1).

**Rationale.** Lawyers reason about "Rule 702 as amended in 2023" as *Rule 702 during a window*, not as a separate rule. Modeling each amendment year as a new framework would explode the framework registry and force every reference across time to traverse `subalternatedTo` chains. Time-scoping at the shard level matches legal intuition, keeps the framework identifier stable across amendments, and enables clean `--as-of` historical queries.

**Tradeoff accepted.** Shards must carry their own time bounds; historical SPARQL queries require explicit `valid_time` filters. This added query complexity is worth it for the modeling clarity.

### 21.2 BFO spine scope — **RESOLVED: mini-BFO with documented mapping to full BFO**

**Question:** Ship a FOLIO Insights-curated mini-BFO (fast, self-contained), or import `bfo-2.0.owl` as a hard dependency (canonical, heavier)?

**Resolution:** Mini-BFO spine under the `fi:` namespace (§7.2), with a companion `bfo_mapping.ttl` file documenting the correspondence to full BFO 2020 classes (decision #2). Users who need full BFO integration import `bfo_mapping.ttl` alongside the main export.

**Rationale.** A hard BFO import would add several thousand classes and force every downstream consumer to carry the full BFO ontology. The mini-BFO spine covers the 95% case (continuant/occurrent split, roles, processes, events) with seven classes. The mapping file keeps canonical alignment available without imposing it.

**Tradeoff accepted.** Sophisticated BFO users must load the mapping file; corpus validation against full BFO is an optional pass rather than automatic.

### 21.3 Hypothesis promotion authority — **RESOLVED: crowdsourced with citation requirement**

**Question:** Who can promote a `HypothesisShard` to attested? Corpus-admin only, or any reviewer with a citation?

**Resolution:** Any reviewer with `reviewer` role or higher can promote, provided they add at least one `depends_on_precedents` or `depends_on_definitions` IRI to the shard (decision #3). The promotion is DID-signed (decision #10) and appended to the governance log (§3.1.5).

**Rationale.** Crowdsourced attestation matches the federated spirit of FOLIO Insights and lets the ontology grow faster. The citation requirement prevents ungrounded promotion; the DID signature provides accountability without imposing a central gatekeeper. Bad promotions surface through retraction cascade, contest, or arbiter demotion (§3.1).

**Tradeoff accepted.** The system tolerates temporary bad promotions in exchange for throughput. Downstream consumers inspect signatures and weigh by their own trust model.

### 21.4 Shard ID stability — **RESOLVED: immutable IDs, mutable relationships and content**

**Question:** If a reviewer re-parents a shard, its decimal-path ID changes. Do we preserve the old IRI with `owl:sameAs`, mint a new IRI and deprecate the old, or allow mutable IDs?

**Resolution:** IDs are never changed and never deprecated. Re-parenting updates the `elaborates` edge; content edits update fields through the append-only `content_edits` audit log; supersession links old and new via `fi:supersedes` without retracting either (decisions #4, #7, #9). The ID itself is derived from a **provenance hash** of `source_uri + source_span` (decision #6), which is deterministic, source-anchored, and never semantic (so it never goes stale).

**Rationale.** Deprecation costs are high — every downstream reference (papers, briefs, RAG pipelines, SPARQL endpoints) breaks when an IRI is withdrawn. Immutable IDs eliminate that entire class of churn. Moving Tractarian position into a first-class graph edge (`elaborates`) keeps the hierarchy representable without baking it into the ID. The append-only audit log preserves history without mutating identity. Provenance-hash IDs are deterministic (re-extracting the same span produces the same ID) and verifiable (any party can recompute and check).

**Tradeoff accepted.** Queries that care about position must traverse `elaborates`; they cannot parse it from the IRI.

### 21.5 LLM model for v2.0 extraction — **RESOLVED: LLM-provider agnostic**

**Question:** v1.0 uses Claude Opus via `instructor`. v2.0's richer metadata demands stronger reasoning. Claude Opus 4.7 (current), with fallback to Sonnet 4.6 for cheaper epistemic-metadata inference? Benchmark before alpha.

**Resolution:** Provider-agnostic. Extraction runs through `instructor` against any supported provider — Claude, OpenAI, Gemini, or local open-source models via Ollama or equivalent (decision #5). Provider selection is per-corpus config and per-command flag. The `extractor_model` field on every shard records which model was used.

**Rationale.** Different corpora have different budget, quality, jurisdiction, and privacy constraints. A sensitive corpus may need local inference; a high-throughput corpus may want a cheaper model; a high-quality legal-reasoning corpus may want the strongest frontier model. Hardcoding a single provider limits FOLIO Insights' reach. Recording the model on every shard enables cross-provider comparison studies.

**Tradeoff accepted.** Extraction quality varies by provider; prompt templates need provider-specific tuning; tests must cover multiple providers.

### 21.6 Shard ID minting scheme — **RESOLVED: provenance hash**

**Question:** Which ID-generation scheme — UUID v4, content hash, sequential counter, or provenance hash?

**Resolution:** Provenance hash — SHA-256 of `source_uri + "\n" + source_span`, first 16 hex chars as the IRI suffix, full 64 chars stored in `provenance_hash` for verification (decision #6).

**Rationale.** Provenance-hash IDs are deterministic (re-runs idempotent), source-anchored (the ID points at its origin), dedup-native (identical extractions collapse), audit-friendly (any party can recompute and verify), and orthogonal to content (content can change freely without breaking identity — a content-hash scheme would forbid this).

**Tradeoff accepted.** Hash collisions at 16 hex chars become non-trivial above ~2³² shards per corpus. The migration tool runs a collision check and escalates to 20 hex chars per corpus if a collision is ever detected.

### 21.7 Content versioning under immutable IDs — **RESOLVED: mutable content with append-only audit log**

**Question:** Content edits happen under immutable IDs. How do we track them — mutable in place, new shard per edit, or same ID with version property?

**Resolution:** Content is mutable in place; every edit appends to the `content_edits` log with a DID-signed `ContentEdit` record (decision #7). Immutable fields (shard_iri, provenance_hash, extracted_at, source_uri, source_span, triple.subject, triple.predicate, append-only lists themselves) are enforced by SHACL and by the storage layer. Historical reconstruction replays the log.

**Rationale.** Mutable-in-place matches the deprecation-avoidance posture of decision #4: the ID, the source anchor, and the basic triple shape remain stable for any downstream citation; refinements to `sense`, `logical_form_imputed`, `epistemic_status`, and similar interpretive fields happen without ID churn. The audit log gives full historical replay. Minting a new shard per content edit would explode the shard count and force consumers to walk supersession chains even for trivial clarifications.

**Tradeoff accepted.** The "current" shard content differs from its original content; consumers wanting the exact-as-extracted state must call `get_shard_at(iri, extracted_at)`.

### 21.8 Demotion and contest mechanics — **RESOLVED: retraction cascade + contested state**

**Question:** Crowdsourced promotion implies crowdsourced demotion. When reviewers disagree, what happens?

**Resolution:** Overruling triggers a retraction cascade (§P3) — dependents re-derive under policy, flip to `aporetic` if no alternative grounding exists, or escalate to review. Reviewer disagreements enter a `contested` state (§3.1.3, decision #8) — the shard stays queryable with `epistemic_status="contested"` and a `contest_votes` dictionary recording each reviewer's position. Resolution happens via arbiter action, distinguo fork, or acceptance as `aporetic`.

**Rationale.** Retraction cascade handles the case where authority has changed (overruling, withdrawal, mis-citation). Contested state handles the different case where authority is unchanged but reviewers read it differently. Conflating the two forces every disagreement into a cascade (over-aggressive) or forces every overruling into a contest (under-aggressive). Separating them lets each mechanism do its own work.

**Tradeoff accepted.** Reviewers must pick the right mechanism (retract vs contest); UI prompts clarify the choice at action time.

### 21.9 Supersession vs retraction — **RESOLVED: distinct mechanisms**

**Question:** When FRE 702 changed in 2023, the 2022 version didn't become wrong — it stopped applying prospectively. How do we represent this without invalidating every shard citing pre-2023 Rule 702?

**Resolution:** Supersession is NOT retraction (decision #9). Superseding a shard sets its `valid_time_end` to the successor's `valid_time_start`, marks `epistemic_status="superseded"`, and links `superseded_by` / `supersedes`. Both shards remain queryable; historical queries with `valid_time <= old.valid_time_end` return the old shard. No cascade fires. Retraction is reserved for cases where the shard was actually wrong.

**Rationale.** Historical legal reasoning requires the old rule to stay available. A case filed in 2021 under the pre-2023 Rule 702 is correctly decided by the pre-2023 rule; retracting that rule would render the case's analysis broken. Valid-time semantics plus a supersession link preserve both the old and new rules in their proper temporal scope.

**Tradeoff accepted.** Queries that want "the current rule" must filter by `valid_time_end IS NULL OR valid_time_end > now()`. The `--as-of` CLI flag and helper SPARQL templates make this convenient (§9.5, §20).

### 21.10 Reviewer attestation and trust — **RESOLVED: DID-signed, downstream-weighted**

**Question:** Does every reviewer's attestation carry equal weight, or do some count more?

**Resolution:** Every reviewer action is cryptographically signed by the reviewer's DID (decision #10). FOLIO Insights itself imposes a minimal role model (extractor / reviewer / arbiter / corpus_admin — §3.1.1) sufficient for governance-action authorization but does not impose a reputation hierarchy. Downstream systems inspect signatures and weigh them by whatever trust model they choose.

**Rationale.** A central reputation system would require FOLIO Insights to take opinions about which reviewers matter, which is out of scope and politically fraught (what weight does a pro se litigant's attestation carry vs. a tenured law professor's?). DID signatures provide verifiable provenance; downstream consumers apply their own trust calculus. The minimal role model handles authorization (only reviewers can promote; only arbiters can resolve contests) without imposing weight semantics.

**Tradeoff accepted.** Downstream consumers must implement their own trust models if they want weighted aggregation. The signatures are the raw material; weighting is out of scope.

### Future questions

Contributors should append new design questions as §21.11, §21.12, ... following the same format: question, resolution, rationale, tradeoff. The resolved-questions log is append-only — later resolutions that supersede earlier ones link via `supersedes` notes but never rewrite history.

---

## 22. References

- Companion philosophical-foundations document: `PHILOSOPHY.md` in this repo
- FOLIO ontology: https://github.com/alea-institute/FOLIO
- folio-enrich: https://github.com/alea-institute/folio-enrich (sibling dependency via bridge)
- folio-mapper: https://github.com/alea-institute/folio-mapper (sibling dependency via bridge)
- OWL 2 EL Profile: https://www.w3.org/TR/owl2-profiles/#OWL_2_EL
- RDF 1.2 / RDF-star: https://www.w3.org/TR/rdf12-concepts/
- SHACL: https://www.w3.org/TR/shacl/
- BFO 2.0 (ISO/IEC 21838-2:2021): https://basic-formal-ontology.org/
- PROV-O: https://www.w3.org/TR/prov-o/
- SKOS Reference: https://www.w3.org/TR/skos-reference/
- Decentralized Identifiers (DIDs) v1.0: https://www.w3.org/TR/did-core/
- did:key method: https://w3c-ccg.github.io/did-method-key/
- did:web method: https://w3c-ccg.github.io/did-method-web/
- `instructor` (LLM-provider-agnostic structured outputs): https://python.useinstructor.com/

---

**End of PRD v2.0-draft-2**

*Draft-2 incorporates all ten design decisions (§21.1–§21.10). When Claude Code executes this, it should commit work in this order: §6 → §7 → §10 → §8 → §9 → §11 → §13. Each section commit should reference the warrant in §5 and the acceptance test. File `PHILOSOPHY.md` alongside this PRD in the repo root before starting implementation; it is the rationale every later decision will point back to. New design questions that arise during implementation should be appended as §21.11, §21.12, etc., preserving the resolved-questions log as an append-only record.*
