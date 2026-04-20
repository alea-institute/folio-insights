# Feature Research: v2.0 shards-as-axioms

**Domain:** Federated, shard-based legal knowledge graph with DID-signed attestations, SPARQL endpoint, and polysemy-first review UI
**Researched:** 2026-04-20
**Confidence:** MEDIUM-HIGH — table stakes grounded in Wikidata/Solid/ActivityPub/YASGUI precedents; differentiators grounded in the PRD v2.0 (40+ resolved decisions) and PHILOSOPHY.md (scholastic distinguo thesis); novel UX patterns (polysemy fork, supersession timeline, contest-vs-supersede split) are LOW confidence on UX-specifics because no direct precedent exists — flagged for `/gsd-discuss-phase` per affected phase.

---

## Orientation

FOLIO Insights v2.0 sits at an unusual intersection. It inherits UX patterns from **five overlapping ecosystems**:

| Ecosystem | What we borrow | What we diverge on |
|---|---|---|
| **Wikidata / Wikibase** | Statement ranks (preferred/normal/deprecated), references-as-first-class, edit history, talk pages | No single "truth per item"; we have sense-forks (distinguo), not ranks; DID-signed attestations, not wiki accounts |
| **Solid / Linked Data Platform** | WebID-OIDC auth, content negotiation, personal-pod storage metaphor | We use DIDs (did:key/web/plc), not WebIDs; corpora are curated, not personal pods |
| **ActivityPub / Fediverse** | HTTP signatures on writes, federation metaphor, multi-server discovery | We sign shards themselves, not just HTTP requests — content-addressed attestations persist |
| **IETF RFC / W3C process** | Numbered proposals, open mailing-list discussion, rough-consensus resolution, append-only design log | Scoped to ontology-content decisions, not network protocols; `.planning/` pattern, not separate tracker |
| **YASGUI / SPARQL tooling** | Syntax highlighting, prefix autocomplete, result tables, endpoint selection | We pre-ship shard-type-aware templates and RDF-star queries; schema-aware autocomplete from our own endpoint |

Everything below is filtered through: **what v1.1 ships today** + **what the brief explicitly commits to** + **what the four consumer audiences expect** (practitioners, AI/RAG, developers, federated reviewers).

---

## Feature Landscape

### A. Shard Browsing & Deep-Link Pages

#### Table Stakes (Users Expect These)

| Feature | Why Expected | Complexity | v1 Dependency |
|---------|--------------|------------|---------------|
| **Dereferenceable shard URL** (`/shard/<hex16>` returns HTML to browsers, TTL/JSON-LD to SPARQL clients via `Accept:` header) | Linked Data norm since 2006; Wikidata, DBpedia, schema.org all do this; anything less reads as "not really linked data" | M | New — v1 has unit viewer, not per-shard permalinks |
| **15-field envelope inspector** (collapsible panels per field group: identity / triple / sense / framework / provenance / epistemic / dependencies / BFO / governance) | PRD §12 explicit requirement; all 15 fields visible or the philosophical discipline is invisible | M | New — v1 shows ~5 fields |
| **Provenance display** (source URI + pinpoint span + extractor DID + prompt hash, click-through to raw source text when available) | Legal users will not cite anything they cannot trace; academic linked-data norm since PROV-O | S | Extend — v1 has source + pinpoint; add DID + prompt hash |
| **Signature verification badge** ("✓ verified signature from did:web:alea.aleainstitute.ai" vs. "⚠ signature fails verification") | DID-signed content without a verification indicator is theater; Mastodon/GoToSocial set precedent | M | New |
| **Copy-as-citation button** (BibTeX / Bluebook / Hyperlink with shard IRI + content hash + as-of date) | Legal/academic audiences demand consistent citation format; permalinks must survive content edits per §21.7 | S | New |
| **Shard subtype badge** (S / D / C / G / H icons for the five types from §6.2) | PRD §12 explicit; users need to distinguish a hypothesis from an attested disputed proposition at a glance | S | New |
| **Status chips** (hypothesis / attested / contested / superseded / aporetic) | Without this, users treat all shards as equally settled — defeats the whole epistemic-honesty thesis | S | New |
| **Timestamp display** (extracted_at + transaction_time + valid_time_start/end with "as-of" indicator) | §21.9 supersession + §21.1 time-scoped shards require temporal context on every page | S | New |

#### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Dependency graph visualizer** (interactive DAG of upstream `depends_on_*` and downstream dependents; click to navigate; highlight kernel-derived chain) | PRD §12 explicit. Nothing else in the legal-KG space makes Spinozan explicit-dependency citation visible — directly instantiates the thesis | L | Cytoscape.js / D3 force-directed; cap at 3 hops default with "expand" affordance |
| **Tractarian tree breadcrumb** (sidebar showing `elaborates` ancestry: `1` → `1.2` → `1.2.3` with siblings at each level) | Wittgenstein-numbered IDs from PRD §21.4 only pay off if the tree is navigable | M | `elaborates` edges are first-class per §7.1; cache the transitive closure |
| **Sense/reference split panel** (Fregean `sense` = intensional gloss, scoped to framework; `reference` = FOLIO IRI with TBox preview) | PRD §5 Frege pattern; without this, polysemy forks look like duplicates | M | `skos:prefLabel` + scoped `skos:definition` |
| **"What does this sentence mean?" side-by-side** (source pinpoint on left, shard triple + logical_form_imputed on right) | Legal experts will verify extraction quality at a glance; bridges LLM-output to textual authority | M | v1 has pinpoint; add the imputed-form panel |
| **RDF-star annotation expander** (on-triple annotations: confidence, valid-time, extractor, reviewer signatures) | Per PRD §11 storage uses RDF-star; making it visible turns opaque metadata into a first-class UX surface | M | Requires Oxigraph RDF-star query |

#### Anti-Features

| Anti-Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Inline shard editing on the public page** | Feels "wiki-like"; lowers friction | Content edits require DID signature + audit log per §21.7; inline-edit without signing workflow bypasses the entire attestation model | Dedicated "Propose edit" → DID-signed review flow with diff preview |
| **"Vote up / vote down" on shards** | Reddit-familiar; engaging | §21.10 "downstream weighs" explicitly forbids system-imposed reputation; voting creates fake consensus that substitutes for citation | Signatures are the raw material; show count-of-signatures but no aggregate score |
| **Hide rejected objections / losing arguments** | Cleaner UI | Aquinas's Summa schema (§6.2 DisputedPropositionShard) exists precisely to preserve the losing argument; hiding them defeats the type | Collapse by default, always expandable, never removed |

---

### B. Polysemy Fork UI (distinguo workflow)

This has **no direct precedent**. Closest analogues: Wikidata disambiguation items, WordNet sense distinctions, legal dictionaries. The PRD's §8.P6 and §21.x decisions define the behavior but not the UX — deep `/gsd-discuss-phase` work needed before building.

#### Table Stakes

| Feature | Why Expected | Complexity | v1 Dependency |
|---------|--------------|------------|---------------|
| **Polysemy flag surfacing** ("⚠ Detected: 'consideration' used with conflicting axioms across 3 frameworks — [Review proposed distinguo]") | Without proactive detection-surfacing, the feature is invisible | M | New — detector lives in `src/polysemy/detector.py` |
| **Side-by-side sense panels** (candidate sense A vs. sense B vs. sense C with framework badge, example shards, conflicting axioms called out) | Users cannot judge a fork without seeing the conflict evidence | M | New |
| **Accept / reject / modify affordance** (per PRD §12: "reviewer can accept, reject, or modify the fork") | Three-way affordance is the brief's explicit requirement | M | New |
| **Evidence panel** (cluster-validator output showing which axioms conflict, in which frameworks, with citations) | Fork without evidence is fiat; evidence without UI is hidden in JSON | M | §8.P3 cluster validator required upstream |
| **DID-signed distinguo action** ("Sign and commit distinguo" button that walks through wallet/keyfile signature) | Per §3.1 `distinguo` is a `signedAction` type | M | New |

#### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Prime-analogate picker** (reviewer marks one sense as `fi:primeAnalogate`; dropdown with default = common-law sense per PRD §8.P6 example) | Aquinas's analogia entis made concrete; no other system has this | M | §7.1 `fi:primeAnalogate` required |
| **Proportional-relation editor** (free-text: "contract in civil law is to *cause* as contract in common law is to *consideration*") | PRD §7.1 `fi:proportionalRelation` explicit; reviewer states the analogy | S | New |
| **Distinction-kind selector** (realis / rationis / rationis_cum_fundamento_in_re / analogica per §7.1 `fi:distinctionKind`) | Scholastic vocabulary exposed; disciplines reviewer reasoning | S | New |
| **"What would this affect?" preview** (dependents that would fork; SHACL shapes that would re-validate; downstream RAG chunks that would re-chunk) | Forks cascade; preview prevents reviewer surprise | L | Requires dependency-graph traversal + SHACL dry-run |
| **Rollback fork affordance** (time-bounded "undo" on a just-committed distinguo before downstream consumers pick it up) | Fork mistakes are high-cost; cheap reversal in first 15min is humane | M | New |

#### Anti-Features

| Anti-Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Auto-apply distinguo when detector confidence > threshold** | Saves reviewer time | Per §16 Risk 2, aggressive auto-fork creates O(concepts × jurisdictions) class explosion; PRD mandates human review gate on every proposed fork | Detector proposes, reviewer disposes. Always. |
| **Generic "disambiguate" button** (dictionary-style sense listing without analogia metadata) | Feels familiar from WordNet | Loses the prime-analogate / proportional-relation discipline that makes the fork *legally* useful | Keep the analogia fields mandatory — fork schema forces reviewer to articulate the analogy |

---

### C. Supersession Timeline (valid-time history)

Precedents: bitemporal databases (Snodgrass, SQL:2011), Martin Fowler's bitemporal history articles, Zep's temporal KG. No direct precedent in **legal** contexts with DID-signed supersessions.

#### Table Stakes

| Feature | Why Expected | Complexity | v1 Dependency |
|---------|--------------|------------|---------------|
| **Horizontal timeline ribbon** (valid_time_start → valid_time_end per shard in a chain; clickable segments) | Any temporal history feature reads as broken without this visual | M | New |
| **"As-of" date picker** (slide or calendar; re-renders shard page to state-at-that-time) | PRD §9.5 / §20 `--as-of` CLI flag mandates UI equivalent | M | Requires temporal SPARQL per §8.P2 example |
| **Current-shard highlight** (visually distinct the shard currently in effect vs. superseded siblings) | Users reading "FRE 702" want to know which version applies now | S | New |
| **Supersession chain navigation** (prev ← current → next via `fi:supersedes` / `fi:supersededBy`) | Chain is the data structure; without nav, it's just a link list | S | §7.1 properties required |
| **"Why was this superseded?" panel** (rationale field from the supersession event + citation to amendment/new rule) | Legal users need the "why" not just the "what" | S | New |

#### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Diff view between versions** (old shard's sense + logical_form vs. new; side-by-side with syntax highlighting) | Amendments are often small; diff exposes the change surface | M | New |
| **Historical query chip** ("View FRE 702 as of 2022-12-31") links from any shard citing a pre-amendment rule | Legal research routinely requires as-of; chip makes it one-click | M | Requires valid-time-aware link generation |
| **Transaction-time vs. valid-time toggle** (two bitemporal axes per §8.P2) | Researchers need to distinguish "when did we learn it" from "when did it legally hold" | M | Complex; only for power users — gate behind advanced toggle |
| **Supersession ≠ retraction indicator** (visually distinct styling; tooltip explains §21.9) | The distinction is the philosophical crux; UI must teach it | S | Pure tooltip/copy work |

#### Anti-Features

| Anti-Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Delete superseded shards from the default view** | "Cleaner" listing | §21.9 explicitly keeps them queryable; historical reasoning requires them | Collapse-by-default with expand; never delete |
| **Auto-set `valid_time_end = now()` on supersession without a picker** | Faster workflow | Amendment effective dates often differ from calendar-today; auto-now creates subtle historical errors | Pre-fill with reasonable default (next day, start of next month); require explicit confirmation |

---

### D. Federated Contributor Workflows (DID-signed attestations)

Precedents: Wikidata account+rank model (rejected — no reputation per §21.10), Solid WebID-OIDC (adjacent), GitHub OAuth + signed commits (similar spirit), Mastodon HTTP signatures (authentication, not content). **Our combination is novel**: OAuth login + DID binding + per-action content signatures over content hashes.

#### Table Stakes

| Feature | Why Expected | Complexity | v1 Dependency |
|---------|--------------|------------|---------------|
| **OAuth login (GitHub / Google)** | Per brief "Auth: OAuth (GitHub/Google) + DID binding"; standard for any public contribution platform | M | New |
| **DID binding on first login** ("Link your did:key or did:web" onboarding step) | Login establishes account; binding establishes signing identity | M | New — requires DID resolution |
| **Signing prompt on every write** (modal: "Sign this [promote/demote/distinguo/contest/supersede/edit] with did:…") | Every §3.1 action is a `signedAction`; every write path needs the modal | L | New |
| **Key management UI** (generate did:key in browser with download option; register did:web by DNS/`.well-known`; register did:plc via AT Proto bridge) | No signing without keys; onboarding friction kills federation | L | New |
| **Role badge display** (extractor / reviewer / arbiter / corpus_admin — scoped per corpus) | Authorization surfaces so users know what they can do; §3.1.1 role tiers | S | New |
| **Contribution history per DID** (list of shards this DID has extracted/promoted/signed, across corpora) | Table stakes: every git-like system has "your commits"; federation demands the same | M | New — indexes signatures by DID |
| **Corpus-admin role-assertion flow** (signed `fi:RoleAssertion` to grant roles per §3.1.1) | Per PRD "roles are asserted by corpus-level `fi:RoleAssertion` records signed by the corpus admin DID" | M | New |
| **Verification indicator on every attestation** (signature valid / expired / DID doc unreachable) | Per §10 every signature must verify; broken signature is a data-integrity event | M | New |

#### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **"What will I be signing?" preview** (canonical content hash + human-readable diff shown before signature prompt) | Users blind-signing JSON is the ActivityPub failure mode; preview addresses it | M | Requires canonical-content-hash stability |
| **Hardware-key signing support** (Ledger / YubiKey / WebAuthn for did:key) | Institutional reviewers need HSM-backed keys; precedent from decentralized-ID ecosystem | L | Defer to post-MVP per §16 R5 risk |
| **Multi-signature attestations** (two+ reviewers co-sign a promotion for extra warrant) | Not in PRD — optional differentiator; supports institutional endorsement workflows | L | Future consideration — flag for v2.1 |
| **"Downstream weighs" dashboard** (shows reviewer signature counts without imposing weights; downstream builds their own trust model from this) | §21.10 operationalized — publishes the raw material without editorializing | M | New |

#### Anti-Features

| Anti-Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Centralized reputation score / badges** ("Expert reviewer: 450 shards, 98% accepted") | Stack Overflow-familiar; feels motivating | §21.10 explicitly rejects reputation; weights are downstream's job | Signature counts, framework breadth — raw data, no score |
| **Anonymous contributions** | Lowers friction | Entire attestation model requires identified DID signing; anonymity = no signature = no promotion-grade shard | Pseudonymous did:key (not tied to identity but still cryptographically accountable) is the middle path |
| **Auto-sign on account creation** (cache private key server-side for "convenience") | Reduces friction | Server-held keys defeat the point of decentralized identity; PRD §16 R5 audit would fail | Client-side signing always; offer encrypted-at-rest backup for key recovery |

---

### E. SPARQL Explorer UI

Precedents: **YASGUI / sib-swiss/sparql-editor**, Wikidata Query Service, TriplyDB, Virtuoso Conductor. These define the baseline table stakes.

#### Table Stakes

| Feature | Why Expected | Complexity | v1 Dependency |
|---------|--------------|------------|---------------|
| **Syntax highlighting + error markers** | YASGUI baseline since 2013; nothing ships without it | S (reuse YASGUI / yasqe.js) | New |
| **Prefix autocomplete** (FOLIO, fi:, PROV-O, SKOS, OWL pre-registered; prefix.cc fallback) | YASGUI baseline | S | Reuse YASGUI |
| **Schema-aware completion for classes & predicates** (from the Oxigraph endpoint, per sib-swiss/sparql-editor 2025) | Generic YASGUI is "unaware of query context" per its own 2025 paper — endpoint-aware is the table stakes now | M | New — requires `VoID`/`sh:NodeShape` metadata endpoint |
| **Results table + JSON/CSV/TSV export** | YASGUI baseline | S | Reuse |
| **Query history (local)** | YASGUI baseline | S | Reuse |
| **Endpoint selector** (read-only public endpoint vs. DID-gated write endpoint) | Two endpoints per brief — users need to choose | S | New |
| **Shareable query permalink** (URL encodes query for sharing; deep-link pattern per 2025 KG norms) | Standard feature; supports citation in papers | S | New |

#### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Pre-shipped query templates** (the 8 examples from PRD §20, plus templates for polysemy inspection, supersession chain traversal, contested-shard surfacing, framework filter, as-of historical query) | Biggest UX gap in every SPARQL UI — users don't know what to ask | M | PRD §20 gives the starter set |
| **RDF-star query helper** (UI toggle that generates `<<?s ?p ?o>> ?annotation ?value` syntax from a visual selector) | RDF-star is new and unfamiliar; Oxigraph supports it but YASGUI does not highlight star well | M | Requires YASGUI fork or custom editor |
| **Streaming results** (SvelteKit adapter-node per brief unlocks this; large result sets stream as they compute) | Brief explicitly cites this as a reason for adapter-node choice | M | Requires server-side streaming |
| **Visual graph result view** (CONSTRUCT queries render as navigable graph via Cytoscape.js; click node → open shard page) | Distinguishes a knowledge-graph tool from a generic SPARQL client | M | New |
| **"Explain this query" panel** (LLM-generated natural-language description; optional) | Helps RAG/AI consumers understand what a query does; aligns with consumer audience 2 | M | Defer if extraction LLM budget tight |
| **Save query to corpus** (DID-signed saved query; becomes a citable `fi:SavedQuery` shard) | Novel — operationalizes the "every query is a possible research artifact" notion | L | Stretch |

#### Anti-Features

| Anti-Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Unrestricted `UPDATE`/`INSERT`/`DELETE`** via the public endpoint | SPARQL-complete | Writes MUST flow through the DID-signed attestation pipeline, not bare SPARQL UPDATE; bypasses audit log, governance log, SHACL | Read-only SPARQL on the public endpoint; writes via the REST API that requires signatures |
| **SPARQL federation (`SERVICE`) to arbitrary endpoints by default** | "Federated" sounds like federation | Opens SSRF, performance, and trust attack vectors; PRD §16 R5 flags security | Allow-list of trusted endpoints (Wikidata, DBpedia, FOLIO canonical) |

---

### F. Governance, RFC Process, and Community Artifacts

Precedents: **IETF RFC** process, **Python PEPs**, **Rust RFCs**, **W3C recommendations track**, Wikidata project pages. Brief commits to `.planning/` pattern + append-only design log (§21.x pattern already established).

#### Table Stakes

| Feature | Why Expected | Complexity | v1 Dependency |
|---------|--------------|------------|---------------|
| **`GOVERNANCE.md`** (role tiers, scope of corpus-admin power, how roles change, escalation path) | Every federated OSS project has this; §3.1 mandates | S | New |
| **`CONTRIBUTING.md`** (how to propose a shard, how to propose a vocabulary change, how to propose an RFC, DID binding steps) | OSS norm | S | New |
| **`CODE_OF_CONDUCT.md`** (Contributor Covenant or similar) | OSS norm since 2015 | S | New — adopt Contributor Covenant 2.1 |
| **RFC process** (numbered `.planning/rfcs/NNNN-title.md`, with status lifecycle: draft → discussion → accepted/rejected → implemented; follows IETF Internet-Draft model) | §3.1 + §15 mandate; append-only like §21.x resolved-questions log | M | New |
| **Governance log browser UI** (PROV-O-formatted `<corpus>/governance.ttl` rendered as scrollable, filterable timeline: role assertions, promotions, contests, resolutions) | §3.1.5 requires the log exist; without a browsable UI it's a `grep` target | M | PROV-O export per §3.1.5 |
| **Append-only design-question log viewer** (§21.x pattern: question → resolution → rationale → tradeoff, sortable by phase/decision number) | §21 "future questions should be appended" — preserve as queryable artifact | S | New |

#### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **RFC comment threads with DID-signed positions** (lightweight; stored as PROV-O) | Operationalizes "open federated community" — positions stay on-platform, not scattered across GitHub issues | M | Reuse signature infra |
| **Warrant trace-back UI** (every shard links to the PRD `§N` warrants and `§21.X` decisions it implements per "Warrants Discipline" in brief) | Honor-system commit `Warrant:` line becomes a navigable graph; novel among KG platforms | M | Warrant metadata on shards |
| **Corpus-fork visualization** (per §3.1.1 corpus_admin can fork; show fork genealogy) | Lets downstream consumers see divergence across federated corpora | L | Defer to v2.1 if time-constrained |

#### Anti-Features

| Anti-Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Voting / quorum requirements on RFCs** | "Democratic" feel | §21.10 "downstream weighs" + governance quorum=None; voting imposes weight we explicitly refused | Rough consensus with maintainer call; IETF model |
| **Separate issue tracker bolted on (JIRA, Linear)** | Familiar | `.planning/` + MEMORY + commit warrants are the pattern; splitting defeats the "everything in git" principle | Keep planning in-tree; GitHub issues only for bug reports, not design |
| **Auto-merge RFCs after N days of silence** | Reduces maintainer load | Silence ≠ consensus; IETF explicitly rejects this | Maintainer must explicitly "accept/reject/defer"; stale RFCs auto-close with "no consensus reached" |

---

### G. Public SPARQL Endpoint with Write Gating

Precedents: **Wikidata Query Service** (read-only, public), **DBpedia** (read-only), **Virtuoso with WebID-TLS** (adjacent), **Solid resource auth** (adjacent). Our pattern: read-only public endpoint + DID-gated write **via REST API that wraps SPARQL UPDATE**, not via raw UPDATE.

#### Table Stakes

| Feature | Why Expected | Complexity | v1 Dependency |
|---------|--------------|------------|---------------|
| **Public read-only SPARQL endpoint** at stable URL | Any KG "publication" without a SPARQL endpoint is not really published | M | Oxigraph exposes SPARQL natively; wire through FastAPI |
| **Query timeout (e.g., 30s)** | DoS protection; Wikidata has 60s, DBpedia 90s — 30s is reasonable MVP | S | Oxigraph supports |
| **Rate limiting** (IP + DID) | Table stakes for public endpoints | S | Arq + Redis already in stack |
| **Result size cap** (e.g., 10K rows) | DoS + performance protection | S | Oxigraph / FastAPI-level |
| **Content negotiation** (SPARQL JSON / SPARQL XML / CSV / TSV / Turtle for CONSTRUCT) | W3C SPARQL 1.1 conformance | S | Oxigraph supports |
| **CORS headers** | Browser-based SPARQL tools require this; Wikidata does it right | S | FastAPI CORS middleware |
| **Endpoint discovery metadata** (VoID description, schema dump, SPARQL service description) | Machine consumers need to introspect the endpoint | M | New |

#### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Write API (not SPARQL UPDATE)** with DID-signed payloads | Writes flow through validation → SHACL → signature verification → governance log → Oxigraph, not around it | L | New — core v2.0 feature |
| **Named-graph scoping on read queries** (query one corpus, query the TBox, query the governance log separately) | Per brief "named graphs + RDF-star"; UI presets for common graph scopes | M | Oxigraph supports |
| **Historical query support** (`--as-of` CLI flag + endpoint parameter: `?as-of=2023-01-01`) | §21.9 supersession + §21.1 time-scoping shine through | M | Requires valid-time-aware query rewriting |
| **SHACL validation endpoint** (POST a candidate shard → get validation report back before committing) | Operational support for writers; prevents "fire off write, get 400, retry" cycles | M | pyshacl in stack |
| **Cluster validator endpoint** (POST a set of shard IRIs → get cluster-consistency report) | §8.P1 cluster validation exposed as API | M | Per §8 P1 |

#### Anti-Features

| Anti-Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **GraphQL endpoint alongside SPARQL** | Developer-friendly for some audiences | Adds surface area; GraphQL schema on top of RDF is an active research area and will bite us; not in brief | Defer; revisit post-v2.0 if consumer demand emerges |
| **Live WebSocket subscriptions to graph changes** | "Real-time" always requested | Batch pipeline per PROJECT.md Out-of-Scope ("Real-time / interactive processing"); federation model is not event-driven | Poll the governance log; exposed as append-only PROV-O feed |

---

### H. Review Workflow (contest vs. supersede; retraction cascade)

Precedents: **Wikidata deprecation** (deprecated rank with reason-for-deprecation qualifier), **git revert** (adjacent), **legal appellate overruling** (domain analog). Nothing precisely matches §21.8's three-way split.

#### Table Stakes

| Feature | Why Expected | Complexity | v1 Dependency |
|---------|--------------|------------|---------------|
| **Disambiguation prompt on every "disagreement" action** ("Is this authority *wrong* (retract), *replaced* (supersede), or *read differently* (contest)?") | §21.8: "UI prompts clarify the choice at action time"; otherwise users conflate the three | M | New |
| **Retraction cascade preview** (shows dependents that will be affected, grouped by resolution policy: auto-re-derive / aporetic / review-needed) | PRD §12 explicit; per §8.P3 retraction propagates — preview prevents surprise | L | §8.P3 dependency graph required |
| **Contest workflow** (post position + citation → contest_votes populated → other reviewers add positions → arbiter resolves) | §3.1.3 explicit three-resolution paths (arbiter / distinguo / aporetic) | M | New |
| **Supersession wizard** (pick successor → set valid_time_end → confirm cascade-free semantics → sign) | §21.9 mechanics must be explicit or reviewers will misuse it | M | New |
| **Reconciliation strategy dropdown** (for `ConflictingAuthoritiesShard`: sense_distinction / contextual_limitation / voice_attribution / textual_correction / retraction_later / subsequent_overruling / jurisdictional_scoping / unreconciled) | PRD §12 explicit; from §6.2 subtype contract | S | Enumerated in shard schema |
| **Aporetic-state marker** ("no grounding currently settles this question") | §3.1.3 third resolution path; epistemically honest state | S | New |

#### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Cascade simulation** (dry-run retraction; see exact change set before committing) | Git-like; prevents accidental corpus damage | L | Requires transactional Oxigraph op + rollback |
| **Contest vote visualization** (position bars showing which DIDs hold which positions, without aggregating into a score per §21.10) | Shows disagreement shape without resolving it | M | Vote data lives in shard |
| **Distinguo-from-contest affordance** ("this contest is actually polysemy — let's fork") | §3.1.3 resolution path #2; one-click escalation from contest to fork | M | Wires contest-UI → distinguo-UI |

#### Anti-Features

| Anti-Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Majority-vote contest resolution** | "Democratic" | §21.10 + §21.8 — contest is not a poll; resolution is arbiter OR distinguo OR aporetic | Keep the three PRD-specified paths; no aggregation |
| **Unified "delete" button** across retract / supersede / contest | Simpler mental model | Conflates three categorically different operations; §21.8 spent ink separating them | Keep them separate with the disambiguation prompt |

---

### I. Extraction Pipeline (LLM-agnostic refactor)

v1.1 already has the pipeline; v2.0 refactors around `instructor` and adds 15-field envelope extraction. Feature surface is mostly internal.

#### Table Stakes

| Feature | Why Expected | Complexity | v1 Dependency |
|---------|--------------|------------|---------------|
| **Provider selector** (per-corpus config + per-command flag; `--llm-provider=claude/openai/gemini/ollama`) | §21.5 mandates provider-agnostic | M | v1 is Claude-locked; refactor via `instructor` |
| **Provider-recorded on every shard** (`extractor_model` field) | §21.5 explicit | S | New field |
| **Prompt-hash recorded** (`extraction_prompt_hash` per P2) | §8.P2 explicit | S | Hash the prompt template on load |
| **CI matrix across providers** (Anthropic + OpenAI + Ollama validated per brief) | §13 testing plan ~10 LLM-provider tests | M | CI setup |

#### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Per-field confidence scoring across the 15-field envelope** (not just overall unit confidence from v1) | Gives reviewers field-level targeting for human review | M | Extends v1 5-stage scoring |
| **Lazy-fill follow-up pass** (per §16 R1: fields 1, 2, 3, 4, 12, 14, 15 at extraction; 5–11, 13 async) | Mitigation strategy in the brief; must be designed not retrofitted | M | Arq follow-up jobs |
| **Framework detector** (§8.P2: detects from source metadata + corpus config + LLM inference) | Novel — maps source doc → `fi:Framework` | M | New service |
| **BFO classifier with `permissive` mode** (§14 migration + §8.P7) | Novel; mini-BFO spine classification at ingest | M | New service |
| **Polysemy detector** (§8.P6: flags same-IRI shards with framework-conflicting axioms) | Triggers distinguo workflow; core novel service | L | Requires cluster validator output |

#### Anti-Features

| Anti-Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **LLM-as-truth** (accept any extracted shard without validation) | Faster | §8 + §13 + §10 all demand SHACL + cluster validation + counterexample gating | Keep the gate; expose confidence + require DID signature for promotion |
| **Re-extract from scratch on pipeline change** | "Simpler" than versioning | Breaks immutable shard IRIs (§21.4) + provenance-hash IDs (§21.6) | Re-extract lands as content edits on existing IRIs; audit log captures the delta |

---

### J. Corpus & Storage Management

#### Table Stakes

| Feature | Why Expected | Complexity | v1 Dependency |
|---------|--------------|------------|---------------|
| **Per-corpus configuration** (framework registry, retention policies, reviewer role assignments, SHACL enforcement mode per brief) | Brief: "SHACL enforcement: per-corpus configurable" | M | New |
| **Named-graph organization** (corpus=named-graph; TBox graph; ABox graph; governance log graph) | §11 storage spec | M | Oxigraph native |
| **Nightly TTL dump + git commit** (brief backup policy) | Brief explicit | S | New — scheduled Arq job |
| **Export formats** (combined.ttl + abox/*.ttl + tbox.ttl + JSON-LD frames + SPARQL CONSTRUCT + N-Quads + Neo4j per brief) | Brief explicit | M | Extend v1 export |
| **PII redaction on ingest** (brief explicit) | Brief explicit | M | New |
| **Opt-in private corpora (encrypted at rest)** (brief explicit) | Brief explicit | L | New |

#### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Corpus fork** (§3.1.1 corpus_admin capability; creates derivative corpus with supersession links to origin) | Enables true federation; no equivalent in Wikidata | L | Defer to v2.1 per brief? Flag for discussion |
| **Cross-corpus query** (SPARQL across named graphs; diff two corpora on same concept) | Powerful analyst tool | M | Oxigraph native |

#### Anti-Features

| Anti-Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Auto-sync between corpora** | Keeps forks "in sync" | Federation means intentional divergence; auto-sync erases the reason to fork | Explicit pull request between corpora; signed supersessions |
| **Shared global namespace for all shards across corpora** | "Unified" KG feel | Shard IRIs are per-corpus per §21.6 provenance-hash scheme; global namespace breaks provenance anchoring | Keep per-corpus; expose cross-corpus links via `owl:sameAs` or `fi:analogousTo` when warranted |

---

## Feature Dependencies

```
Shard envelope (§6.1)                   [PHASE 2 — foundation]
    └─required by──> Shard subtypes (§6.2)
                         └──> All five shard types, each with own validation
    └─required by──> Provenance-hash IRI (§6.3)
                         └──> Dereferenceable shard URL
                         └──> Deep-link permalink
    └─required by──> Content versioning (§6.4)
                         └──> Content edits UI
                         └──> Historical reconstruction
    └─required by──> DID-signed attestations (§6.5)
                         └──> All signing UX
                         └──> Signature verification badge
                         └──> DID binding onboarding

Governance model (§3.1)                 [PHASE 7 — blocks write UX]
    └──> Role-assertion flow
    └──> Promotion / demotion / contest / supersession workflows
    └──> Governance log viewer

FOLIO v2 vocab + BFO (§7)               [PHASE 8 — blocks ingest]
    └──> BFO classifier
    └──> Framework registry
    └──> Analogia predicates (distinguo UI needs these)

Seven design principles (§8.P1–P7)      [PHASE 9 — blocks UI work]
    └──> P1 Cluster validator (required by polysemy detector)
    └──> P2 Framework detector (required by framework filter)
    └──> P3 Dependency graph (required by cascade preview, graph visualizer)
    └──> P6 Polysemy detector (required by distinguo UI)
    └──> P7 BFO classifier (required by BFO badges)

Pipeline refactor (§9)                  [PHASE 10]
    └──> Multi-provider extraction
    └──> Per-field confidence
    └──> Lazy-fill follow-up

SHACL hybrid (§10)                      [PHASE 11]
    └──> Write-time validation
    └──> Validation API endpoint

Storage layer (§11)                     [PHASE 13]
    └──required by──> SPARQL endpoint
                         └──> SPARQL explorer UI
    └──required by──> Named-graph scoping
    └──required by──> RDF-star annotations in UI

UI design contract (pre-§12)            [PHASE 14 — BLOCKS ALL §12 WORK]
    └──> Shard page
    └──> Polysemy fork UI
    └──> Supersession timeline
    └──> Contest/supersede/retract wizards

Review UI (§12)                         [PHASE 15]
    └──depends on──> PHASE 14 design system
    └──depends on──> PHASE 9 services
    └──depends on──> PHASE 13 storage

Public SPARQL endpoint                  [PHASE 16]
    └──depends on──> PHASE 13 storage + named graphs
    └──depends on──> PHASE 6 DID signatures (for write API)

Community artifacts (§15)               [PHASE 18]
    └──enhances──> Federation adoption
    └──depends on──> PHASE 7 governance model resolved

Security audit (§16 R5)                 [PHASE 19 — BLOCKS RELEASE]
    └──audits──> DID signing (§6.5)
    └──audits──> OAuth (auth)
    └──audits──> Crypto primitives
```

### Dependency Notes

- **Governance model (§3.1) → all write UX:** No signed action UI without role model + signing infrastructure. Phase 7 is on the critical path for everything in §12.
- **Cluster validator (P1) → polysemy detector (P6):** Detection relies on cluster-level consistency checks surfacing framework-conflicting axioms.
- **Dependency graph (P3) → retraction cascade preview + graph visualizer:** No cascade UX without DAG construction.
- **UI design contract (Phase 14) blocks all §12 work:** Brief explicitly calls out "fresh bold 'shards-as-axioms' aesthetic"; doing UI-per-feature without a design system produces pastiche.
- **Security audit (Phase 19) blocks release:** Non-negotiable per §16 R5; crypto + OAuth + DID signing all require audit.

---

## MVP Definition

### Launch With (v2.0 GA)

Everything P0 in brief + key P1 per brief §17 success criteria. This *is* the MVP — v2.0 is itself "MVP for shards-as-axioms."

**Must-ship for GA:**

- [ ] **All 5 shard subtypes with envelope validation** (§6.1, §6.2) — the data model is the product
- [ ] **Provenance-hash IRIs + content versioning + DID-signed attestations** (§6.3–§6.5) — federation floor
- [ ] **Governance model with 4 role tiers + PROV-O log** (§3.1) — without governance, federation is aspirational
- [ ] **FOLIO v2 vocabulary + mini-BFO spine** (§7) — can't validate or classify without it
- [ ] **All 7 design principles with acceptance tests** (§8) — the thesis shipped
- [ ] **LLM-provider-agnostic pipeline** (§9) — §21.5 decision shipped
- [ ] **SHACL hybrid validation** (§10) — write-time correctness
- [ ] **Oxigraph + named graphs + RDF-star storage** (§11) — query infrastructure
- [ ] **Review UI with deep-link shard pages, polysemy forks, supersession timeline, SPARQL explorer, contest/supersede/retract wizards** (§12) — human interface
- [ ] **Public SPARQL read endpoint + DID-gated write API** (post-§12 P1) — machine interface
- [ ] **Community artifacts: CONTRIBUTING, CODE_OF_CONDUCT, GOVERNANCE, RFC process** (§15) — federation-ready
- [ ] **Pre-release security audit pass** (§16 R5) — non-negotiable
- [ ] **WCAG 2.1 AA compliance** (brief quality bar) — accessibility is a blocking gate
- [ ] **P95 SPARQL <500ms at 1M triples** (brief quality bar) — performance gate
- [ ] **Benchmark corpora ingested: v1 advocacy + FRE + Restatement of Contracts** (brief)

### Add After GA (v2.1 candidates — some already flagged in brief)

- [ ] **Hardware-key signing support** (HSM / Ledger / YubiKey) — institutional reviewers
- [ ] **Multi-signature attestations** — co-signed promotions
- [ ] **Corpus fork visualization** — federation genealogy
- [ ] **Full post-release security audit** (brief schedules this)
- [ ] **Cascade simulation / dry-run retraction** — analyst power tool
- [ ] **"Explain this query" LLM helper** — AI-consumer UX

### Future Consideration (defer, revisit with signal)

- [ ] **GraphQL endpoint** — no brief commitment; revisit if consumer demand emerges
- [ ] **Live subscriptions to graph changes** — batch pipeline architecture per PROJECT.md Out-of-Scope
- [ ] **Inline rank/voting affordances** — explicitly anti-feature per §21.10
- [ ] **Mobile-first apps** — desktop research-tool audience; no signal for mobile
- [ ] **Federated SPARQL (`SERVICE`) with untrusted endpoints** — security risk without trust allow-list

---

## Feature Prioritization Matrix

Priority keyed to the phase structure in the brief (phases 0–20).

| Feature | User Value | Implementation Cost | Priority | Target Phase |
|---------|------------|---------------------|----------|--------------|
| **15-field shard envelope** | HIGH | MEDIUM | P1 | Phase 2 |
| **5 shard subtypes** | HIGH | MEDIUM | P1 | Phase 3 |
| **Provenance-hash IRI + dereferenceable URL** | HIGH | LOW | P1 | Phase 4 |
| **Content versioning + audit log** | HIGH | MEDIUM | P1 | Phase 5 |
| **DID-signed attestations (core)** | HIGH | HIGH | P1 | Phase 6 |
| **Governance model + role tiers + PROV-O log** | HIGH | HIGH | P1 | Phase 7 |
| **FOLIO v2 vocab + mini-BFO spine** | HIGH | MEDIUM | P1 | Phase 8 |
| **Cluster validator** | HIGH | HIGH | P1 | Phase 9 |
| **Polysemy detector** | HIGH | HIGH | P1 | Phase 9 |
| **Framework detector + registry** | HIGH | MEDIUM | P1 | Phase 9 |
| **BFO classifier** | MEDIUM | MEDIUM | P1 | Phase 9 |
| **LLM-provider-agnostic pipeline** | HIGH | MEDIUM | P1 | Phase 10 |
| **Lazy-fill follow-up (risk mitigation)** | MEDIUM | MEDIUM | P2 | Phase 10 |
| **SHACL hybrid (Pydantic-gen + hand-written)** | HIGH | HIGH | P1 | Phase 11 |
| **Oxigraph + named graphs + RDF-star** | HIGH | MEDIUM | P1 | Phase 13 |
| **UI design system (bold aesthetic)** | HIGH | HIGH | P1 | Phase 14 |
| **Shard deep-link page with 15-field inspector** | HIGH | MEDIUM | P1 | Phase 15 |
| **Dependency graph visualizer** | MEDIUM | HIGH | P2 | Phase 15 |
| **Polysemy fork UI (accept/reject/modify)** | HIGH | HIGH | P1 | Phase 15 |
| **Supersession timeline + as-of picker** | HIGH | MEDIUM | P1 | Phase 15 |
| **Contest / supersede / retract wizards (with disambiguation prompt)** | HIGH | MEDIUM | P1 | Phase 15 |
| **Retraction cascade preview** | HIGH | HIGH | P1 | Phase 15 |
| **Governance log timeline viewer** | MEDIUM | MEDIUM | P2 | Phase 15 |
| **Warrant trace-back UI** | MEDIUM | LOW | P2 | Phase 15 |
| **SPARQL explorer (YASGUI-based, schema-aware)** | HIGH | MEDIUM | P1 | Phase 15–16 |
| **Pre-shipped SPARQL templates** | HIGH | LOW | P1 | Phase 16 |
| **Public SPARQL read endpoint** | HIGH | MEDIUM | P1 | Phase 16 |
| **DID-gated write API** | HIGH | HIGH | P1 | Phase 16 |
| **SHACL validation endpoint** | MEDIUM | LOW | P2 | Phase 16 |
| **CONTRIBUTING / CoC / GOVERNANCE / RFC process** | HIGH | LOW | P1 | Phase 18 |
| **Security audit pass** | HIGH | HIGH | P1 (blocking) | Phase 19 |
| **Hardware-key signing** | MEDIUM | HIGH | P3 | Post-GA |
| **Multi-signature attestations** | MEDIUM | HIGH | P3 | Post-GA |
| **Corpus fork + genealogy viz** | MEDIUM | HIGH | P3 | Post-GA |
| **Cross-corpus query presets** | MEDIUM | LOW | P2 | Phase 16 |
| **Streaming SPARQL results** | MEDIUM | MEDIUM | P2 | Phase 16 |
| **Visual graph result view** | MEDIUM | MEDIUM | P2 | Phase 16 |

**Priority key:**
- **P1:** Must have for v2.0 GA
- **P2:** Should have; ship in v2.0 if phase budget allows, else early v2.1
- **P3:** Nice to have; post-GA

---

## Competitor Feature Analysis

| Feature | Wikidata | Solid | ActivityPub/Fediverse | **FOLIO Insights v2.0** |
|---------|----------|-------|-----------------------|-------------------------|
| **Identity** | Wiki account | WebID (HTTP URI) | ActivityPub actor w/ key | OAuth + DID (did:key / did:web / did:plc) binding |
| **Content auth** | No per-statement auth (just page history) | ACL lists per resource | HTTP signatures on requests (not persisted on content) | Per-action DID signatures over content hashes (persisted) |
| **Disagreement model** | Rank (preferred/normal/deprecated) + talk pages | Out of scope (storage layer) | Block/defederate (coarse) | Contest (first-class) + supersession + retraction — three distinct mechanisms |
| **Polysemy** | Disambiguation pages; senses as separate items | N/A | N/A | `fi:distinguishes` forks with analogia predicates (prime analogate + proportional relation) |
| **Time-scoping** | Point-in-time + qualifiers (start date / end date) | N/A | N/A | Bitemporal: `valid_time_start/end` + `transaction_time` per shard; `--as-of` queries |
| **Reputation** | Edit count / barnstars (community-driven) | N/A | Block-list reputation (per-instance) | Explicitly none (§21.10 downstream weighs); signature counts surfaced, no aggregate score |
| **SPARQL UI** | Wikidata Query Service (YASGUI-based) | N/A | N/A | YASGUI-based + schema-aware from endpoint + RDF-star helpers + pre-shipped legal-KG templates |
| **Governance** | Policy pages, ArbCom, RfA/RfA-style | BYO (per pod) | Per-instance admin | 4-tier DID-scoped roles + PROV-O log + RFC process + warrant-trace |
| **Federation** | Single canonical graph (federated only to Wikipedia sister projects) | Pod-to-pod via WebID + ACL | Instance-to-instance via inbox/outbox | Corpus-to-corpus via supersession links + corpus forks + DID-signed cross-graph citations |
| **Write gating on public API** | MediaWiki API w/ account | WebID + WAC | HTTP-signed inbox delivery | REST write API w/ DID-signed payloads; SPARQL UPDATE disabled on public endpoint |

**Our approach positions v2.0 as:**
- More epistemically honest than Wikidata (contested/aporetic states; bitemporal; no reputation theater)
- More content-authoritative than ActivityPub (signatures on content, not just requests)
- More domain-specific than Solid (legal-KG-shaped, not personal-pod)
- Novel in: polysemy forks with analogia predicates; Scholastic/Spinozan philosophical warrant as first-class UX

---

## Sources

Research drew on:

- **Internal:** PRD-v2.0-draft-2.md (§3.1, §6, §7, §8, §12, §15, §16, §21), PHILOSOPHY.md, .planning/v2.0-MILESTONE-BRIEF.md, .planning/PROJECT.md
- **Wikidata statement ranks:** [Help:Ranking](https://www.wikidata.org/wiki/Help:Ranking), [Help:Deprecation](https://www.wikidata.org/wiki/Help:Deprecation), [T198907 Visually distinguish deprecated statements](https://phabricator.wikimedia.org/T198907)
- **SPARQL editor UX:** [sib-swiss/sparql-editor](https://github.com/sib-swiss/sparql-editor), [Triply YASGUI docs](https://docs.triply.cc/yasgui/), ["A User-Friendly SPARQL Query Editor Powered by Lightweight Metadata" (2025)](https://arxiv.org/html/2503.02688v1)
- **DID UX:** [Decentralized Identity & Wallets Explained (2025)](https://thetechinfluencer.com/decentralized-identity-wallet-integration/), [W3C DID Core v1.0](https://www.w3.org/TR/did-core/)
- **Solid / federation:** [Solid Project](https://solid.mit.edu/), [Solid Protocol specification](http://emansour.com/research/lusail/solid_protocols.pdf), [Solid, WebID and OpenID Connect](https://kaspars.net/blog/solid-webid-oidc)
- **ActivityPub content signing:** [ActivityPub and HTTP Signatures](https://swicg.github.io/activitypub-http-signature/), [GoToSocial HTTP Signatures docs](https://docs.gotosocial.org/en/latest/federation/http_signatures/)
- **PROV-O and provenance UI:** [W3C Best Practices Pragmatic Provenance](https://www.w3.org/2011/gld/wiki/228_Best_Practices_Pragmatic_Provenance), [Prov Viewer (Springer)](https://link.springer.com/chapter/10.1007/978-3-319-40593-3_6)
- **IETF RFC process:** [IETF RFCs](https://www.ietf.org/process/rfcs/), [IETF Process documents](https://www.ietf.org/process/), [Internet Standards Process draft](https://datatracker.ietf.org/doc/html/draft-ietf-procon-2026bis-06)
- **Knowledge graph deep-links / content negotiation:** [The year of the Knowledge Graph (2025)](https://www.semanticarts.com/the-year-of-the-knowledge-graph-2025/), [ArcGIS Knowledge 12.0 (Q4 2025)](https://www.esri.com/arcgis-blog/products/arcgis-knowledge/announcements/whats-new-in-arcgis-knowledge-12-0-q4-2025)
- **Bitemporal / supersession UX:** [Bitemporal History — Martin Fowler](https://martinfowler.com/articles/bitemporal-history.html), [Building a Bitemporal Knowledge Graph for LLM Agent Memory](https://explore.n1n.ai/blog/building-bitemporal-knowledge-graph-llm-agent-memory-longmemeval-2026-04-11), [Bitemporal Property Graphs (Springer 2026)](https://link.springer.com/chapter/10.1007/978-3-032-05281-0_15)

---

*Feature research for: FOLIO Insights v2.0 shards-as-axioms*
*Researched: 2026-04-20*
