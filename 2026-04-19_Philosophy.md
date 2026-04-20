# Shards as Axioms: Philosophical Foundations for FOLIO Insights

Twenty-five centuries of work on atomic truth decomposition converge on a single engineering lesson for FOLIO Insights: **the shard is the right unit of representation, citation, and addressing — but never the unit of verification, meaning, or grounding.** Every system that treated atomic propositions as metaphysically self-sufficient (Tractatus, Principia, Aufbau) collapsed; every system that atomized for operational purposes while handling composition, revision, and context explicitly (the Summa, Spinoza's Ethics, the Semantic Web) survived and produced usable infrastructure. FOLIO Insights sits at the far end of this tradition as a **moderate atomism** built on OWL/SKOS: Fregean triples as the engineering primitive, scholastic distinction-machinery for polysemy, Spinozan explicit-dependency citation for each derivation, Carnapian framework-relative meaning postulates, and Quinean/Sellarsian discipline about the revisability and theory-ladenness of every shard. What follows organizes the inheritance thinker-by-thinker with the five extraction points — atomic unit, composition mechanism, primitives, critiques, and concrete design patterns — and closes with a synthesis of the atomism/holism tension as it applies specifically to a legal ontology with FOLIO's OWL+SKOS+multi-parent+polysemy shape.

---

## Part I. Classical Foundations: Socrates, Plato, Aristotle

### Socrates and the elenchus

**Atomic unit.** The *real definition* (*horismos*) of a universal — a single *logos* specifying the essence (*ousia*) common to all F-things. Merely extensional enumerations ("piety is prosecuting wrongdoers") are rejected; Socrates demands a definition that (i) applies to all and only Fs, (ii) explains *why* any instance is an instance, and (iii) functions as a *paradeigma* against which cases can be judged.

**Composition.** Inferential linkage among accepted propositions under mutual-consistency pressure, driven by the *ti esti* question and the Priority of Definition thesis: knowledge of F requires a *logos* of F, not merely correct sorting.

**Critique.** Elenchus alone produces no positive content (Vlastos's "problem of the elenchus": inconsistency of p with {q,r} does not select which to reject); almost every early dialogue terminates in **aporia**. The "Socratic Fallacy" (Geach): one need not know the definition to have knowledge. Meno's paradox: one cannot search for what one does not already grasp.

**Design patterns.**
- **Counterexample-driven shard validation.** Every definitional shard (`folio:Fraud ≡ ...`) is gated on passage of curated counterexample suites encoded as SHACL shapes — explicit positives, explicit negatives, and paradigm borderline cases. Promotion from draft to asserted status requires surviving elenctic testing.
- **The *ti esti* gate for class promotion.** Before a term becomes an `owl:Class` in FOLIO, require a real-definition shard (necessary and sufficient conditions, `owl:equivalentClass`), not merely a SKOS label set. Label-only entries remain at the `skos:Concept` tier.
- **Aporia as a first-class state.** Shards that have survived refutation but lack positive grounding carry `status:aporetic`. This is epistemically honest and prevents downstream reasoners from treating unsettled doctrine as settled.
- **Paradigm anchoring.** Each defined class carries a small set of stipulated clear cases (Euthyphro 6e sense); any revision that excludes a paradigm triggers human review.

### Plato: Forms, diairesis, the divided line

**Atomic unit.** The **Form** (*eidos*) — a self-identical, necessarily and purely F, uniquely causal abstract universal. Particulars *participate* (*methexis*); Forms inter-mix (*koinōnia*, Sophist 251–259: Being, Same, Different, Motion, Rest).

**Composition.** Three mechanisms: participation links particulars to Forms; communion links Forms to each other; **collection and division** (*synagōgē* and *diairesis*) organizes Forms into a recursive bifurcating tree terminating in an *infima species*. The definition *is* the path: the Sophist's angler is defined by the ordered chain "acquisitive, by capture, by hunting, aquatic, fishing, by striking, by hook, upward-striking." Dialectic ascends from hypotheses to an **unhypothetical first principle** (the Good, Republic 509b–511b) and descends "through Forms to Forms."

**Primitives.** The Form of the Good as *archē*; mathematical first principles (point, unit) are *not* genuine archai — they are hypotheses (Republic's divided line distinguishes *dianoia* — hypothetical-deductive — from *noēsis* — foundational).

**Critique.** The **Third Man Argument** (Parmenides 132a–b): One-over-Many + Self-Predication + Non-Identity yields infinite regress. **Arbitrariness of diairesis**: no algorithm selects the right bifurcation; the Sophist itself produces seven divergent definitions of the sophist. Bad cuts (Statesman 262a–263e: "human vs. non-human herd") use differentiae irrelevant to the target kind.

**Design patterns.**
- **Diairesis as enforced recursive binary classification with rejection rationale.** Each new `owl:Class` materializes *both* branches of its disjunction via `owl:disjointUnionOf`. Each branch declares its **differentia** (a property restriction / SHACL shape) and records a **rejection rationale** for the non-chosen branch. This converts taxonomic authoring from silent choice into auditable argument — directly addressing the TBox-change-review problem FOLIO will face at scale.
- **Cut-at-the-joints validation.** Differentiae must be *per se* relevant to the target genus — anticipating Aristotle. Encode relevance as a required `folio:differentia` annotation that must refer to a property already declared on the parent class.
- **Path-as-definition.** A leaf class's canonical definition is the ordered sequence of differentiae traversed from root. This is mechanically reconstructable from the class hierarchy and becomes the `skos:definition` or `rdfs:comment`.
- **Two-tier axioms: unhypothetical vs. hypothetical.** Distinguish a small set of **grounding axioms** (FOLIO roots, constitutional primitives, jurisdictional constants — the system's *anupotheton*) from the much larger set of **working hypotheses** (most domain classes) that are revisable. Reasoners should report, for any given inference, which tier each premise occupies.
- **TMA-defense through punning discipline.** Where "the concept of Contract is itself a legal concept" must be expressed, use OWL 2 punning at the metamodel level and tag the assertion as *pros heauto* (definitional, not extensional) to prevent self-predication regresses.

### Aristotle: categories, demonstration, syllogism, dialectic

Aristotle converts almost one-for-one into OWL design constructs — the Organon is, in effect, a proto-specification for description-logic systems.

**Atomic unit.** Three-fold: **primary substance** (individual particular) ontologically; **categorical proposition** ("S is P" with *kath' hauto* or *kata sumbebēkos* mode) logically; **real definition** (genus + differentia, functioning as middle term) definitionally.

**Composition.** **Syllogism** via the middle term — which Aristotle's central insight in Posterior Analytics II.11 identifies as *itself* the cause of the conclusion. Barbara (*All B is A; all C is B; all C is A*) is `rdfs:subClassOf` transitivity; second- and third-figure moods propagate negation and disjointness.

**Primitives.** Three kinds of indemonstrable starting-points (APo I.10): **common axioms** (*koina* — LNC, LEM, equals-from-equals; cross-disciplinary); **postulates** (*aitēmata* — science-specific existence assumptions); **definitions** (*horoi* — essence-specifications). All grasped by **nous** via induction from perception (APo II.19). **LNC is "the firmest of all principles"** (Metaph. Γ.3, 1005b19–23).

**Critique.** The regress problem is answered only if nous-grasp is non-arbitrary. Circular demonstration is rejected except for convertible terms. Tension between Categories (individuals = primary substance) and Metaphysics Z (form = primary substance).

**Design patterns.**
- **The ontological square → four shard types mapping cleanly to OWL.**
  - *Not said-of, not present-in* (primary substance) → `owl:NamedIndividual` (actual party, contract, case).
  - *Said-of, not present-in* (essential universal) → `owl:Class` with `rdfs:subClassOf` backbone (Contract, Tort, Fiduciary).
  - *Said-of, present-in* (universal accident) → `owl:ObjectProperty`/`DatatypeProperty` (*hasParty*, *jurisdiction*).
  - *Not said-of, present-in* (particular accident/trope) → reified property assertions or SKOS-indexed instance concepts.
  
  Four corresponding shard types — **class axiom, instance assertion, class hierarchy, property assertion** — each with distinct lifecycle and validation rules.
- **Essential vs. incidental predication mode.** Every predication shard carries `folio:predicationMode ∈ {perSe, perAccidens}`. Only `perSe` shards enter demonstrations and propagate through subsumption; `perAccidens` shards are documentary only. This implements Aristotle's rule that demonstration runs only over *kath' hauto* connections — distinguishing "Acme Corp is a Delaware C-corporation" (essential, definitional for its legal personality) from "Acme Corp was sued in March 2024" (incidental).
- **Middle-term justification: every derived shard carries its cause.** No free-floating `rdf:type` assertions on complex legal classes; every such assertion must be backed by `folio:derivedVia` pointing to the definitional or statutory shard that supplied the middle term. This produces inspectable, replayable legal reasoning chains — the single most auditable design pattern in the tradition.
- **Four causes → four justification slots** on complex classification shards: material (underlying facts), formal (definition), efficient (producing agent/statute/court), final (purpose/legislative intent). Especially valuable for statutory interpretation where courts explicitly invoke purposive (final-cause) reasoning.
- **Axiom/postulate/definition trichotomy → three shard tiers.** Common axioms (LNC, identity rules — reasoner-enforced, immutable); postulates (jurisdictional existence claims — change with jurisdictional events); definitions (FOLIO class equivalences — evolve with doctrine). Distinct revision semantics per tier.
- **LNC as meta-axiom for consistency checking.** Mandatory reasoner inconsistency detection as a gate on every commit. The "same respect" qualification is critical: a statement true for one jurisdiction and false for another is not a contradiction — encode respects as named graphs keyed by jurisdiction, time, and perspective.
- **Dialectic/endoxa tier alongside demonstration.** Two inference regimes: (i) **demonstrative** — strict OWL entailment from axioms, definitions, `perSe` predications; (ii) **dialectical** — defeasible inference from *endoxa* (persuasive authority: secondary sources, minority opinions, Restatements, commentary). Dialectical conclusions are tagged `folio:dialectical` and cannot upgrade to demonstrative without explicit grounding. This reproduces Aristotle's Topics/Posterior Analytics split — and is exactly the distinction a legal reasoning system needs between **persuasive and binding** authority.

---

## Part II. Medieval Architecture: The Summa as Reference Implementation

Medieval scholasticism confronted the structural twin of FOLIO's problem: atomize a vast, contradictory, authoritative corpus (Scripture + Fathers + Aristotle + Corpus Iuris + canon law) into citable, networkable, disputable units, with polysemy handling, explicit reconciliation of conflicting authorities, and a deductive backbone. They solved it. The shard types and relations that emerge from that tradition — five-field article schema, sic-et-non structure, distinction-based polysemy forking, gloss layering, analogia for cross-domain terms — are a ready-made scholastic legal KR vocabulary.

### Augustine: sign, thing, illumination

**Atomic unit.** The *signum–res* pair: a sign (textual token, citation) bound to a signified reality with an illumination-backed judgment.

**Design patterns.**
- **Sign/Thing bifurcation at shard level.** Each shard distinguishes its *signifier* (citation, quoted passage — `dcterms:BibliographicResource`) from its *signified* (the OWL class/individual or proposition asserted). The shard is *not* the sentence; it is the binding of a sentence-token to an ontological claim. This preserves provenance under citation drift and textual variance.
- **Uti/frui normative axis.** Legal shards inherit a functional role (end-normative vs. instrumental) orthogonal to class hierarchy — e.g., protected-interest rule vs. procedural vindication rule.
- **Book-III ambiguous-sign pipeline.** Augustine's rules for resolving ambiguous signs (context, figurativeness, rule of faith) become a formal resolution pipeline on under-determined shards: check sense-within-context → check authorial voice → apply governing precedent/canon.

### Boethius: the Porphyrian tree and axiomatic theology

**Atomic unit.** The predication of genus-plus-differentia yielding species (definition by division), and the axiomatic proposition (*communis animi conceptio* / *maxima propositio*) asserted without proof.

**Why this matters.** Boethius's commentaries on Porphyry's *Isagoge* fixed the vocabulary of the **Tree of Porphyry** (Substance → Body → Living Body → Animal → Rational Animal → Man) — directly isomorphic to OWL's `rdfs:subClassOf` hierarchy with differentiae as property restrictions. His three answers to Porphyry's universals question — *ante rem*, *in re*, *post rem* — remain the modern ontologist's choice among Platonist class realism, Aristotelian immanent universals, and conceptualist nominalism.

**De Hebdomadibus** is the decisive text for axiomatic architecture. Boethius opens with nine *communes animi conceptiones* explicitly modeled on Euclid's common notions and proposes theological reasoning *more geometrico* — **prefiguring Spinoza's Ethics by eleven centuries**.

**Design patterns.**
- **Porphyrian decomposition as enforced modeling discipline.** Every new `owl:Class` must be registered with (a) explicit `rdfs:subClassOf` genus and (b) a named differentia (`owl:Restriction` or SHACL shape). **Reject classes with no differentia** — the single most common failure mode in legal taxonomies and the one FOLIO most needs enforced mechanically.
- **Explicit universals-status annotation.** `folio:universalMode ∈ {anteRem, inRe, postRem}`. *Ante rem* classes are stipulated primitives (definitions in codes); *in re* classes are empirically-recurring patterns (factual templates from cases); *post rem* classes are analyst constructs (doctrinal categories from commentary). This governs which reasoning operations are licit.
- **Axiomatic kernel layer.** On the *hebdomades* model, designate a small set of shards as the kernel: self-evident legal primitives (*pacta sunt servanda*, *nemo iudex in causa sua*, the element-structure of a contract). All other shards are theorems citing derivation chains terminating in the kernel or in cited authority.
- **Quinque voces as upper-ontology vocabulary.** Distinguish essential predicates (species, differentia) from accidental (property, accident) as metadata — reasoners know which predications are definition-constitutive.

### Thomas Aquinas: the Summa structure, first principles, analogia entis

**This is the reference implementation.** The *Summa Theologiae* is a shard-based KR system: parts → treatises → ~512 **quaestiones** → ~2,669 **articuli**, where each *articulus* has a fixed five-field schema:

| Field | Latin | Function |
|---|---|---|
| 1. Question | *Utrum…?* | Binary-framed issue |
| 2. Objections | *Videtur quod…* | Enumerated counter-arguments with cited authority |
| 3. Sed contra | *Sed contra…* | Brief authoritative counter-citation |
| 4. Body | *Respondeo dicendum quod…* | Determinative answer with distinctions |
| 5. Replies | *Ad primum…* | Point-by-point reconciliation of objections |

Aquinas almost always reconciles objections by **distinction**: the objection is not simply wrong; it uses a term in a sense different from the *respondeo*. Distinguishing the senses dissolves the contradiction. This is the direct template for polysemy handling in legal shards.

**First principles and analogia entis.** Aquinas distinguishes **self-evident in itself** (*per se nota quoad se*) from **self-evident to us** (*quoad nos*) — "God exists" is the former but not the latter. The classical gap between axiom-in-the-theory and axiom-accessible-to-the-user, which legal systems elide at their peril.

The **analogia entis** solves polysemy: terms like "being," "good," "contract," "person" predicated across domains are neither **univocal** nor **equivocal** but **analogical**, ordered by a prime analogate with proportional relation. This is the **single most important pattern for legal polysemy**: a term like "contract" applied across civil, common, ecclesiastical, international, and regulatory law is analogical, with one domain functioning as prime analogate and others bearing proportional senses.

**Real vs. rational distinctions**: real distinctions exist in the thing (matter/form); rational distinctions only in the mind (divine mercy vs. justice); rational-with-foundation-in-re is an intermediate class. In finite beings essence (*essentia*) is really distinct from existence (*esse*) — what a thing *is* vs. *that* it is.

**Design patterns.**
- **Five-field article schema as canonical shard type for disputed propositions.** Define `folio:DisputedPropositionShard` with:
  - `folio:utrum` (well-formed binary question)
  - `folio:objection[]` (each with `folio:cites` + `folio:argues`)
  - `folio:sedContra` (cites + asserts)
  - `folio:respondeo` (determination with `folio:usesDistinction` links)
  - `folio:replyToObjection[]` (one per objection)
  
  Every non-trivial legal proposition becomes a dialectically-structured unit carrying its own opposition. This solves the "how do we represent the losing argument without losing it" problem that flat legal KR cannot.
- **Per-se-nota annotation.** `folio:epistemicStatus ∈ {perSeNotaQuoadSe, perSeNotaQuoadNos, demonstrable, revelatum, authorityOnly}`. Reasoners treat differently — kernel self-evidence vs. derivable vs. accepted-only-on-authority.
- **`folio:analogousTo` as the canonical cross-domain relation.** OWL provides `owl:sameAs` (univocity) and `owl:differentFrom` (equivocity) but no native analogical predicate. Introduce `folio:analogousTo` with mandatory sub-properties `folio:primeAnalogate` (focal sense) and `folio:proportionalRelation` (explicit proportion — e.g., "contract in civil law is to *cause* as contract in common law is to *consideration*"). **Forbid `owl:sameAs` and even `skos:exactMatch` where the semantic relation is truly analogical.** Use `folio:analogousTo` for *contract* (civil/common), *property* (real/personal/IP), *person* (natural/juridical/moral), *due process* (procedural/substantive), *fault* (intention/negligence/strict).
- **Distinction-kind metadata.** `folio:distinctionKind ∈ {realis, rationis, rationisCumFundamentoInRe, analogica}`. Real distinctions warrant splitting into two classes; merely rational distinctions warrant a single class with two annotation properties. This disciplines the proliferation of near-duplicate classes — the most common ontology smell in legal taxonomies.
- **Essence/existence split: TBox vs. ABox.** Separate *essentia* shards (definition of a legal kind) from *esse* shards (attestations of particular instances). Mark TBox shards as **definitional** vs. **regulative**.
- **Subaltern-science architecture.** A regulatory scheme's primitives are imported from its enabling statute, whose primitives come from the constitution. Encode as `folio:subalternatedTo` between ontology modules — preserving Aquinas's insight that a derived science's axioms are the higher science's theorems.

### Scholastic methodology: quaestiones, sic et non, distinctions, glosses

**Abelard's Sic et Non** (c. 1121) juxtaposes 158 patristic contradictions without resolution; the Prologue supplies the complete reconciliation toolkit that *is also* the modern legal-hermeneutic toolkit: (1) check for polysemy (the *distinguo*); (2) check context; (3) check authorial voice; (4) check textual corruption; (5) check for later retraction; (6) seek a harmonizing distinction.

**Lombard's Sentences** applied the rules systematically; Alexander of Hales divided the text into **distinctiones** — the numbered citation grid used by every medieval theologian for four centuries. This is medieval hypertext: every gloss pinned to a grid point, every authority traceable to a cited locus.

**Gratian's Decretum** (*Concordia discordantium canonum*, c. 1140) applied exactly the same technique to canon law — explicitly a harmonization of discordant canons. And the Digest's *regulae iuris* and the 88 maxims of the *Liber Sextus* are a ready-made axiomatic kernel (*Nemo plus iuris transferre potest quam ipse habet*, *In dubio pro reo*, *Lex posterior derogat priori*).

**Design patterns.**
- **Sic-et-non contradictory-authorities shard type.** `folio:ConflictingAuthoritiesShard` with `folio:sic[]` (supporting authorities) and `folio:non[]` (opposing authorities) and obligatory `folio:reconciliationStrategy ∈ {senseDistinction, contextualLimitation, voiceAttribution, textualCorrection, retractionLater, subsequentOverruling, jurisdictionalScoping, unreconciled}`. This is the canonical shape for **circuit splits, majority/minority rule divergences, conflict-of-laws problems, and doctrinal oscillation over time**.
- **Distinctio-based forking as the core polysemy operator.** When a shard encounters apparent contradiction (SHACL violation or inference conflict), trigger a *distinguo* workflow: propose candidate senses, split the shard into sense-indexed children, reattach authorities, re-check consistency. Record as `folio:distinctioEvent` with rationale. Canonical split dimensions from Aquinas: *secundum quid* vs. *simpliciter*, *formaliter* vs. *materialiter*, potency vs. act, *ratione* vs. *re*.
- **Gloss layer as first-class annotation apparatus.** Commentary as layered annotations (Web Annotation / OA on base shards), each a typed shard of its own: `folio:GlossShard` subtypes `clarificatoria`, `extensiva`, `restrictiva`, `dissentiens`, `historica`. A base statute-shard accumulates glosses from regulations, treatises, cases, and secondary authority — each independently queryable, each with provenance.
- **Regulae iuris as seed axiom kernel.** Import the 88 *regulae iuris* of the *Liber Sextus* and the Digest's parallel collection as a seed axiomatic layer. Most common-law and equitable maxims map to one or more.

### Ramon Llull: combinatorial axiom generation

Llull's *Ars Magna* (c. 1305) reduces theology to nine **Dignities** (*Bonitas, Magnitudo, Eternitas, Potestas, Sapientia, Voluntas, Virtus, Veritas, Gloria*) and nine relations, combined via rotating wheels to enumerate all possible propositions. **Leibniz's 1666 *De Arte Combinatoria* explicitly cites Llull** as the precursor of the *characteristica universalis*.

**Critique.** The fundamental limitation: **combinatorial enumeration cannot, by itself, distinguish true from merely-well-formed propositions.** The wheels produce the Cartesian product of primitives; coherence with the Dignities is assumed to suffice for truth, which begs the question against any proposition whose truth-makers lie outside the Dignities.

**Design patterns.**
- **Combinatorial hypothesis-space generation with mandatory filtering.** Given FOLIO's core predicates and a Hohfeldian primitive set (right, duty, power, liability, privilege, immunity, no-right, disability — the legal analog of the Dignities), mechanically enumerate candidate propositions and **filter** by: consistency with the kernel (no contradiction), attestation in authority, SHACL passage, analogical consistency across sibling concepts. **This is a Llullian generator with mandatory post-filtering — the critical discipline Llull lacked.**
- **Hohfeldian Dignities as the legal atomic-predicate layer.** Every legal relation in FOLIO decomposes into Hohfeldian primitives plus subject/object assignment, enforced structurally.
- **Rotating-wheel UI for authored axiom exploration.** For ontology engineers, a Llullian interface: select subject, rotate relation wheel, rotate predicate wheel; system proposes candidate shards at the combination. The wheel is a *human-facing generator* over syntactically-well-formed propositions, with the ontology-as-filter behind it.
- **Anti-Llull discipline.** Document explicitly that combinatorial generation produces *hypotheses*, not *knowledge*. Each generated shard must acquire external grounding (authority citation, empirical attestation, kernel derivation) before promotion from *proposita* to *attestata*.

---

## Part III. Early Modern: The Axiomatic Architecture Matures

### Descartes: methodic doubt as extraction filter

Stripped of theology, Descartes's program is a **shard-extraction and validation protocol**. The four rules (Discourse II) are the earliest explicit statement of methodical decomposition: evidence (accept only clear-and-distinct), analysis (divide every difficulty into as many parts as possible), synthesis (simple → complex), enumeration (complete review). Methodic doubt is a targeted filter — sensory unreliability, dreaming, evil demon — each eliminating whole classes of belief. The cogito is the canonical atomic foundational truth: self-verifying, denial performatively incoherent.

**Critique — the Cartesian Circle.** Clear-and-distinct perception proves God; God's non-deceptiveness validates clear-and-distinct perception. Arnauld's objection has never been fully answered. **You cannot use the output of your inference engine to validate the axioms of your inference engine.**

**Design patterns.**
- **Methodic-doubt gauntlet.** Every candidate shard runs: *Can this be doubted under sensory error? Under interpretive ambiguity? Under adversarial construction?* Passes if reduced to minimal indubitable form (verbatim statutory text, black-letter holding stripped of dicta).
- **Rule-2 decomposition as granularity justification.** Every legal "difficulty" (a rule, a holding, a statute) divides into as many atomic parts as required.
- **Order-of-construction invariant.** The shard graph must admit a topological ordering from simple to complex; no shard references a more-complex shard as dependency.

### Spinoza's Ethics: the canonical reference implementation

**The *Ethica, ordine geometrico demonstrata* (1677) is literally a shard-based axiomatic system.** Each Part is a rigid typed graph of node-types:

- **Definitiones** — stipulative introductions of primitive terms
- **Axiomata** — propositions asserted without proof
- **Propositiones** — derived theorems (the main payload)
- **Demonstrationes** — proofs explicitly citing prior definitions, axioms, and propositions (`per Def. 3 et Ax. 1 et Prop. 7`)
- **Corollaria** — immediate consequences with their own dependencies
- **Scholia** — informal prose sitting *beside* the formal graph, **explicitly non-load-bearing**

The citation convention `E2P13L3A2` is itself a primitive URI scheme. The dependency graph is machine-checkable: every demonstration cites only nodes earlier in the topological order. Lord's description captures it exactly: "a grid of cross-references, each proposition demonstrable by reference to earlier ones, building up to a complex network of interrelated truths." **This is, in OWL terms, an RDF graph where propositions are resources and demonstrations are `prov:wasDerivedFrom` property assertions over a DAG.**

**Critique.** Bennett (*A Study of Spinoza's Ethics*, 1984) and Curley (*Behind the Geometrical Method*, 1988): the *form* is immaculate but the *content* often exceeds what the axioms bear. E1D3 (substance) quietly presupposes what E1P14 later "proves." The geometric display conceals that much argumentative work is smuggled into definitional stipulations. **Lesson: the form of explicit dependencies is independently valuable even when the axioms are contested.** The fix is not to abandon the architecture but to treat axiom-declaration as a first-class, auditable, versionable commitment — and to accept that any legal ontology will be "hypothetico-deductive" (Bennett's term): coherentist, with axioms justified by downstream utility, not apodictic self-evidence.

**Design patterns — the most important in the entire tradition for FOLIO Insights.**
- **Shard-with-explicit-dependencies.** Every shard carries a machine-readable list of the prior shards (definitions, axioms, prior propositions, statutes, cases) it depends on. **This is the core pattern.** Implement via `prov:wasDerivedFrom` + typed `folio:dependsOnAxiom`, `folio:dependsOnDefinition`, `folio:dependsOnPrecedent`.
- **Typed shard kinds** mapping one-to-one: Definitions → `skos:Concept` + `skos:definition`; Axioms → foundational assertions in a named graph; Propositions → derived claims; Demonstrations → `prov:wasDerivedFrom` chains; Scholia → `rdfs:comment` explicitly excluded from inference; Lemmas and Postulates as sub-types.
- **Topological-order invariant.** Demonstrations may cite only shards preceding them in the DAG. Cycle detection is a schema-validity check.
- **Namespaced axiom bundles.** Each subdomain (contracts, torts, evidence) introduces local definitions/axioms without polluting the global namespace — Spinoza's per-Part axiom sets.
- **Scholia as reasoning-free annotation.** Human commentary, policy arguments, examples in a dedicated property explicitly excluded from inference — preventing rhetorical content from contaminating formal derivations.
- **Hypothetico-deductive honesty.** Accept (per Bennett) that axioms are justified by coherence and utility; version and audit them accordingly.

### Leibniz: characteristica universalis, calculus ratiocinator, monadology

**Leibniz is the direct ancestor of modern KR and the only pre-modern figure whose explicit program *is* what FOLIO Insights attempts.**

**Characteristica universalis** — a universal symbolic language where every primitive concept gets a unique unambiguous sign, and every complex concept's sign transparently reveals its composition. This is the direct philosophical ancestor of **URI schemes in RDF/OWL**, **controlled vocabularies in SKOS**, and **upper ontologies like FOLIO/SALI** — a fixed skeleton of primitive legal concepts from which specific terms are composed.

**Alphabet of human thought** — the finite set of absolutely simple concepts from which every complex concept is a unique combination. The design decision behind FOLIO/SALI's closed top-level vocabulary.

**Calculus ratiocinator** — once concepts are encoded, reasoning reduces to rule-governed symbol manipulation. *Calculemus!* — "Let us calculate." The ancestor of every automated inference system; OWL/DL reasoners (HermiT, Pellet, ELK) are partial fulfillments. The Trendelenburg/Schröder distinction between "logic as language" (*characteristica* / Frege) and "logic as calculus" (*calculus* / Boole) maps directly onto the modern tension between expressiveness and decidability in DL design.

**Monadology (1714)** — a surprisingly distributed-systems-shaped metaphysics. Monads are **windowless** (no causal inflow), **individuated by perception** (identity of indiscernibles), **each mirrors the whole universe from its perspective**, **coordinated by pre-established harmony** (coherence guaranteed by shared axioms, not runtime communication). For distributed KR this is a template: each shard locally complete, stateful, not dependent on live reasoning with other shards, made globally consistent by shared axioms.

**Two principles** ground reasoning: **Contradiction** (generates truths of reason — analytic, necessary) and **Sufficient Reason** (generates truths of fact — contingent). **Predicate-in-subject theory**: every true proposition's predicate is contained (explicitly or virtually) in the subject-concept — the ancestor of `owl:equivalentClass` expansion.

**Design patterns.**
- **Characteristica universalis → stable FOLIO URI scheme.** Every legal concept gets exactly one canonical IRI; compound concepts express composition via URI structure or explicit `owl:equivalentClass` over primitives.
- **Alphabet of human thought → upper ontology.** FOLIO's closed top-level categories (actors, areas of law, documents, events, forums, industries, matters, objects) are the alphabet; specific terms are compositions.
- **Calculus ratiocinator → automated inference.** Shards are inputs to an OWL reasoner deriving new shards mechanically. *Calculemus* is the product vision.
- **Monadic compressed perspective.** Each shard caches, alongside its primary assertion, a compact context bundle — relevant axioms, nearest supertype chain, related SKOS concepts — so local reasoning proceeds without round-tripping the full graph. Pre-established harmony = globally-shared axioms guarantee coherence.
- **Sufficient reason → provenance requirement.** Every contingent shard must cite its sufficient reason — case, statute, evidentiary finding. No dangling facts.
- **Identity of indiscernibles → shard deduplication.** Two shards with identical content and dependencies are the same shard; URI canonicalization enforces this.

### Locke, Hume: empiricist atomism and its limits

**Locke** — simple ideas (sensation and reflection) as atomic building blocks; complex ideas built by combining, comparing, abstracting. Three kinds of complex ideas: **modes** (don't subsist alone — *murder, theft, contract, negligence, consideration* are **mixed modes**, constructed by convention), **substances**, **relations**. Berkeley-Hume critique: abstract general ideas are incoherent — an imagistic "triangle in general" cannot be both scalene and isoceles.

**Hume** — impressions vs. ideas; the **Copy Principle** (every simple idea copies a prior impression — a meaningfulness filter); **Hume's Fork** (relations of ideas vs. matters of fact, mutually exclusive); **bundle theory** (objects = bundles of co-occurring qualities, no hidden substratum); three **associations** (resemblance, contiguity, cause-effect); causation as constant conjunction projected by mental habit; and the devastating **problem of induction**: generalizations from past observations lack rational ground.

**Design patterns.**
- **Legal concepts as mixed modes.** Mark *contract, negligence, murder* explicitly as conventional compositions (not natural kinds). Their *jurisdictional variance* is a feature of their mixed-mode status, not an ontology bug.
- **Bundle theory → legal entities as attribute-shard clusters.** A party, contract, or cause of action is represented as the bundle of co-occurring attribute shards. No hidden "substance" substratum; OWL individuals are identified by the collection of assertions about them.
- **Hume's Fork → two-track shard system.** Mark every shard as `:AnalyticShard` (derivable from definitions — `owl:equivalentClass` expansions, subsumption chains) or `:FactualShard` (case-based, statutory, evidentiary — requires citation). **Different verification rules per track.** Contradictions on the analytic track are ontology bugs; contradictions on the factual track are conflicts of authority and require precedence-rule resolution (jurisdiction, hierarchy, recency).
- **Copy-principle meaningfulness check.** Factual shards without traceable source are quarantined.
- **Induction-risk flagging.** Any shard produced by generalization from case instances carries `:inductiveSupport` with sample size, jurisdictional scope, confidence. **The system must refuse to treat such shards as axioms for further analytic inference** — the crucial Humean discipline.

### Kant: the closed category set as upper ontology

Kant answers Hume with the thesis that experience itself is structured by an a priori conceptual framework: **the 12 categories** (Quantity: unity/plurality/totality; Quality: reality/negation/limitation; Relation: substance/causality/community; Modality: possibility/existence/necessity) plus **forms of intuition** (space, time). Synthetic a priori judgments are possible because the mind contributes a priori structure to experience. **Phenomena vs. noumena**: knowledge is schema-mediated, not direct access to reality.

**Design patterns.**
- **Closed schema of relation types.** Adopt a fixed top-level set of relation kinds under which every content-level property must subsume. Mapping for legal: Quantity → cardinality constraints; Quality → affirmative/negative/limiting holdings; Relation → legal entity / legal trigger-consequence / reciprocal rights-duties; **Modality → deontic modalities** (possible/actual/necessary directly corresponds to permitted/asserted/mandatory — the core of legal reasoning).
- **Three-way analytic/synthetic tag.** Beyond Hume's two-track system, add Kant's synthetic a priori: `:Analytic` (derivable from definitions alone), `:SyntheticAPosteriori` (requires empirical grounding), `:SyntheticAPriori` (substantive but structural — requirements like "every claim has a claimant, every cause an effect" — the formal constraints of legal discourse itself).
- **Forms-of-intuition layer.** Treat jurisdiction-and-time as framework metadata on every shard, not content-level assertions.
- **Phenomenal humility.** Document the ontology's categorial choices as commitments, not discoveries; make FOLIO↔alternative-ontology mapping a first-class integration concern.

---

## Part IV. Logical Atomism: The Program and Its Failure

Between Frege's *Begriffsschrift* (1879) and Carnap's *Aufbau* (1928), the atomistic metaphor was engineered literally. The program collapsed — spectacularly and instructively. Every non-trivial failure mode FOLIO Insights will encounter was encountered here, in cleaner form, on smaller domains. The failures are the architect's most useful inheritance.

### Frege: the invention of atomic form

**Atomic unit.** The saturated atomic proposition `F(a)` or `R(a,b)` — function + argument replacing subject-copula-predicate. **An RDF triple `⟨s, p, o⟩` is Fregean, not Aristotelian**: the predicate is a two-place function; the subject-copula-predicate reading is a throwback.

**Three further Fregean doctrines.**
- **Context principle** (*Grundlagen* §62): "never ask for the meaning of a word in isolation, but only in the context of a proposition." Extracting a term without its propositional context is epistemically malformed.
- **Sense vs. reference.** "Morning star" and "evening star" share *Bedeutung* (Venus) but differ in *Sinn* (mode of presentation). **The canonical polysemy machinery.**
- **Compositionality.** Complex-expression meaning is a function of part meanings plus mode of combination.

**Critique.** Russell's 1902 letter showed Basic Law V (unrestricted comprehension) entails paradox. **The first and archetypal instance of a formalized atomistic system dying from unrestricted comprehension.** The pattern recurs wherever KR systems admit self-reference without type discipline.

**Design patterns.**
- **Triple-as-Fregean-atom** — enforced at the shard layer, never a bare label.
- **Dual `sinn`/`bedeutung` annotation.** Every shard term carries (a) intensional description — scoped `skos:definition` tied to jurisdictional context, and (b) one or more URIs into FOLIO. **Polysemy resolved in the sense slot, not by minting new URIs**, keeping reference-side aggregation stable.
- **Context principle as provenance constraint.** Shards record the propositional context of extraction, not just isolated terms. Shards extracted as bare labels ("consideration," "fit and proper person") are malformed per Frege.

### Russell and Whitehead: Principia and logical atomism

*Principia Mathematica* proves `1+1=2` at ✸54.43 (Vol. I, p. 379). The cost of rigor. Ramified type theory blocks paradoxes but requires the **Axiom of Reducibility** to recover analysis — an *ad hoc* collapse of the ramification. Infinity and Choice are assumed but not logical truths. Gödel then showed incompleteness.

**Russell's 1918 Logical Atomism.** Atomic facts = particulars-in-relations; atomic propositions = their linguistic correlates; molecular propositions = truth-functions. **Two methodological theses dominate:**

- **Supreme maxim of scientific philosophizing:** "Wherever possible, substitute constructions out of known entities for inferences to unknown entities." Objects are logical constructions from appearances, not inferred substrata.
- **Theory of descriptions** ("On Denoting," 1905). "The present King of France is bald" is rewritten as `∃x(Kx ∧ ∀y(Ky → y=x) ∧ Bx)`. **Most apparent singular terms in ordinary language are disguised descriptions.** Knowledge by **acquaintance** (direct) vs. by **description** (routed through quantified structures).

**Design patterns.**
- **Theory-of-descriptions rewriter.** Legal prose saturates with definite descriptions — "the defendant," "the contract," "the aforesaid premises," "any reasonable person." Each rewritten at extraction time into Russell's form — **three shards (existence, uniqueness, predication) rather than one referential shard** whose referent may not exist. Non-existence handling becomes compositional rather than brittle.
- **Constructions-over-inferences rule.** Prefer composed shards from known primitives over minting new inferred entities. If "reasonable supervision" reconstructs from FOLIO duties, do not introduce `:ReasonableSupervision` as a new atomic term.
- **Acquaintance/description layer split.** Acquaintance layer = directly grounded in observable textual artifacts with document-level provenance; description layer = inferred. Reasoning terminates in acquaintance-grounded shards.
- **Explicit totality shards.** Closure claims ("these are all the statutory exceptions to §230") are their own meta-shards, not implicit CWA.

### Wittgenstein's Tractatus: the architectural exemplar

**The Tractatus is the closest thing the canon offers to a reference design for a shard-based system.** Its numbered structure is not decoration — it is the thesis performed.

**Ontology: facts, not things.**
- *1.1 The world is the totality of facts, not of things.*
- *2.01 A state of affairs (Sachverhalt) is a combination of objects.*

The primary data are relational atoms, not entities. **The single most important move for a fact-based KR.**

**Picture theory.** A proposition represents because its elements stand in the same logical relations as the objects in the state of affairs — structural isomorphism. For a KR system: **shard structure must be isomorphic to the structure of the legal reality represented.** A shard for a liability relation must have argument places for (liable-party, aggrieved-party, harm, jurisdiction) if those are constitutive.

**Elementary propositions and their logical independence.**
- *4.21 The simplest kind of proposition, an elementary proposition, asserts the existence of a state of affairs.*
- *4.211 It is a sign of an elementary proposition that no elementary proposition can contradict it.*
- *5 Propositions are truth-functions of elementary propositions.*
- *5.134 From an elementary proposition no other can be inferred.*

**The numbered structure itself** — 1, 1.1, 1.11, 1.12, 1.2, 1.21 — is a strict tree where position encodes *what the proposition is an elaboration of*. **This is the most directly importable pattern of the cluster.** A Tractarian shard identifier is not a flat UUID; it is a path in a dependency tree.

**Showing vs. saying.** Logical form cannot be stated; it shows itself in well-formed propositions. The Tractatus itself is a ladder to kick away. **For FOLIO Insights: structural invariants (type discipline, role-arity, schema) are *not* first-class content shards — they are shown by SHACL shapes and OWL TBox, not asserted in the ABox.** Reifying schema-facts as content invites liar-style paradox.

**Critique.** No elementary proposition was ever exhibited. **The colour-exclusion problem**: "a is red at t" excludes "a is green at t" but neither entails the other by truth-functional means — precipitating Wittgenstein's own abandonment of the Tractatus.

**Design patterns — the richest vein.**
- **Numbered hierarchical shard IDs.** Adopt Tractarian identifiers: `⟨ns⟩:1.21.3`. The decimal path encodes the dependency tree. Maintain `trac:elaborates` (functional on the shard side) and enforce that `shard:1.21.3 trac:elaborates shard:1.21`. **The identifier is a machine-readable claim of logical position.**
- **Facts-not-things as primary extraction target.** Extract `⟨subject, predicate, object⟩` triples for *Sachverhalte*, not entity cards. Entities recovered by projection from fact shards; facts are primary.
- **Picture-theory isomorphism as validation invariant.** Number of roles on the predicate equals argument places in the legal relation. Under-specified shards (missing roles) fail picture-theoretic adequacy.
- **Engineer elementary layer for logical independence.** Where the legal domain introduces incompatibilities (the colour-exclusion analog: "natural person" vs. "corporation"; "void" vs. "voidable"), **promote incompatibility to explicit axiom shards in a higher layer rather than letting it live implicitly in the elementary layer.** This directly addresses Wittgenstein's own abandoned problem.
- **Showing vs. saying firewall.** Keep structure in SHACL shapes, OWL TBox, and named graphs — not in the A-Box of content shards.
- **Ladder-kicking for extraction metadata.** Extraction-process artifacts (LLM confidence, prompt hash, timestamp) ride alongside the shard but are distinct from its logical core — provenance shards vs. content shards, cleanly typed.

### Vienna Circle: protocol sentences, foundationalism vs. coherentism inside the program

**Protocol sentences** — observation-report atomic statements. **Schlick** took them as incorrigible first-person reports of immediate experience; **Neurath** insisted on physicalist third-person reports with full opacity disclosed ("Otto's protocol at 3:17: [Otto's speech-thinking at 3:16 was (at 3:15 there was a table)]"), and pointedly **revisable**. Neurath's ship metaphor: "We are like sailors who must rebuild their ship on the open sea." Even within logical positivism, foundationalism vs. coherentism split the program.

**Verificationism self-refutes** (the principle is neither analytic nor empirically verifiable). Quine's *Two Dogmas* buried the analytic/synthetic line the whole edifice rested on.

**Design patterns.**
- **Protocol layer = raw-extraction shards.** A distinct layer of shards that are citation-anchored, minimally interpreted extractions from primary legal text. Each carries author (human or model identity), timestamp, source URI with pinpoint, exact textual span. **Neurath's insight: protocols include their own production conditions.** Contrast with the **derived layer** of reasoning products.
- **Verification predicate per shard.** `vc:verificationMethod` records observation, citation, or inferential path. Shards without it are quarantined.
- **Foundationalism/coherentism switch.** Support both modes. Coherentism is the realistic default for legal reasoning (a misread holding at the protocol layer must be revisable). Foundationalist islands exist (the text of a statute, once pinpointed and hashed, is not revisable by downstream coherence).

### Carnap's Aufbau and its failure

*Der logische Aufbau der Welt* (1928) is the most technically ambitious atomistic construction ever attempted: every scientific concept explicitly defined from **elementary experiences** (*Elementarerlebnisse*) via a single basic relation — **remembered similarity** — using **quasi-analysis** to construct quality-classes, sense-classes, the visual field, physical space, other minds.

**Why it failed.**
- **Goodman's *Structure of Appearance* (1951)** showed quasi-analysis is technically flawed: companionship of qualities (every red thing in a given dataset is also round) produces wrong merges; imperfect community produces wrong splits. The method cannot recover intended structure from similarity alone.
- **Quine's *Two Dogmas* (1951)** showed the construction of space at §126 is not definitional reduction but pragmatic optimization ("greatest possible regularity") — a directive, not a definition. More broadly, confirmation is holistic: no sentence has a unique range of confirming experiences.
- **No actual base** — elementary experiences were never characterized in a way that let one pick them out.
- **Paradox-driven type machinery** imported from Principia bloated the alleged simplicity.

**Later Carnap** — *Logical Syntax* (1934), **Principle of Tolerance** ("in logic there are no morals; everyone is at liberty to build his own logic"), **internal/external questions** (ESO 1950), **meaning postulates** (1952). **Meaning postulates are exactly the role OWL axioms play**: `owl:disjointWith`, `rdfs:subClassOf`, property characteristics, domain/range restrictions, property chains — all are meaning postulates in Carnap's sense. Not empirical about the world; stipulations of the framework in which empirical claims are expressed.

**Design patterns.**
- **Constitutional layering.** Build FOLIO Insights in explicit strata: (L0) primitive FOLIO vocabulary; (L1) purely definitional concepts fully reducible to L0; (L2) composed concepts requiring additional empirical input; (L3) jurisdictional/domain extensions. Each layer fully reducible to the layer below. Carnap's constitution system, stripped of its phenomenalist ambition.
- **Meaning postulates as OWL axioms — CRITICAL.** Distinguish three classes of axiom: (i) logical axioms (OWL semantics itself); (ii) meaning postulates (`owl:equivalentClass`, disjointness, property characteristics, SKOS hierarchy acting analytically); (iii) empirical/domain shards (synthetic content). **Reasoning that depends on a meaning postulate is recorded as such, because changing the postulate is a *framework* decision, not a factual update.**
- **Internal/external question split.** Queries against the graph are internal (reasoner-answered under fixed framework). Decisions about which FOLIO extension to adopt for a new jurisdiction are external — pragmatic framework-engineering, not factual. **Do not let framework questions be "answered" by inference.**
- **Tolerance operationalized.** Support multiple parallel frameworks (common-law, civil-law, specific regulatory interpretive framework) with explicit cross-framework translation as mappings, not entailments.

### Why the logical-atomist program failed — the ten anti-patterns this predicts

1. **No one could produce the atoms.** Atomicity is not absolute — it is relative to extraction operations. **Anti-pattern:** treating "atomic shard" as a primitive recognized by inspection. A shard is atomic *under extraction schema v1.3*, never absolutely.
2. **Logical independence fails at the elementary layer.** The colour-exclusion problem is legal everywhere ("natural person" vs. "corporation"). **Anti-pattern:** assuming elementary shards are independent because simple. Run independence-violation audits.
3. **Self-reference forces type hierarchies that destroy simplicity.** **Anti-pattern:** unrestricted meta-shards without layering discipline (distinct named graphs, distinct IRI schemes, distinct reasoner profiles). OWL's punning is convenient but can smuggle self-reference.
4. **Reductive definitions don't reach.** Carnap's physical-space construction relied on pragmatic directives disguised as definitions. **Anti-pattern:** claiming a shard definition is pure reduction when it relies on heuristics.
5. **Confirmation is holistic.** **Anti-pattern:** per-shard-only verification. Support cluster-level verification.
6. **Analyticity is framework-relative.** **Anti-pattern:** asserting shards are "analytic" outside an explicit framework. Record the framework F.
7. **Showing vs. saying collapses if you try to say too much.** **Anti-pattern:** reifying schema invariants as first-class content shards.
8. **Totality claims are cheap to write, expensive to justify.** **Anti-pattern:** implicit CWA in an OWA system.
9. **Rigor has a cost curve.** 379 pages to 1+1=2. **Anti-pattern:** demanding every inference be proof-theoretically explicit at all times. Routine inferences ride the reasoner's materialization; contested inferences unfold to explicit proof chains when adjudicated.
10. **Purity-driven primitives aren't domain primitives.** **Anti-pattern:** epistemically-basic over domain-basic. Let primitives be FOLIO's working primitives (actors, documents, events, forums).

---

## Part V. The Holist Critique: Quine, Wittgenstein II, Sellars

### Quine's "Two Dogmas of Empiricism" (1951) — the decisive critique

Quine attacks logical empiricism at two points, and in doing so dismantles the picture of knowledge as independently-verifiable atomic propositions.

**First dogma.** The analytic/synthetic distinction, after walking through definition, interchangeability *salva veritate*, semantic rules, and Carnap's state descriptions, is "an unempirical dogma of empiricists, a metaphysical article of faith."

**Second dogma.** Reductionism — the idea that each meaningful statement is equivalent to a logical construct of terms referring to immediate experience. Even the weakest sentence-level form fails.

**Positive doctrine — confirmation holism.** "Our statements about the external world face the tribunal of sense experience not individually but only as a corporate body." Knowledge is "a man-made fabric which impinges on experience only along the edges." "Any statement can be held true come what may, if we make drastic enough adjustments elsewhere in the system... Conversely, by the same token, no statement is immune to revision."

**Downstream.** Underdetermination of theory by data; ontological relativity; indeterminacy of translation.

**Why devastating for naive shard architectures.** A shard like "a contract lacking consideration is unenforceable" is not a free-standing empirical atom. Its truth depends on a web: "consideration" definitions (which depend on precedents), promissory estoppel (which carves exceptions), jurisdictional background theory, Restatement glosses, procedural posture. A contrary ruling doesn't falsify one shard — it redistributes truth-values across many.

**Design patterns.**
- **Web-of-belief graph model.** Shards are nodes in a dependency graph; each records `dependsOn` neighbors. **Revision protocols propagate**: retracting a shard triggers re-evaluation of dependents, with configurable stances (prefer-latest, prefer-authority, prefer-most-specific-jurisdiction).
- **No shard is unrevisable.** Including FOLIO's TBox. Every shard carries version, confidence, retraction pathway. A `folio:Contract` superclass is privileged (high revision cost, many dependents) but not sacrosanct.
- **Cluster-level validation.** Test suites target shard clusters, not individual shards. A red test can be satisfied by revising any of a set; the protocol exposes the choice rather than silently patching the first plausible candidate.
- **Underdetermination as first-class.** Store competing extractions as alternative `ExtractionHypothesis` entities rather than committing silently.

### Later Wittgenstein: family resemblance for legal concepts

**Meaning as use; language-games; forms of life.** The meaning of a word is its use in the language; words get semantic weight from concrete practices — pleading, contract drafting, statutory interpretation, appellate argument — each a distinct language-game. **The same word ("reasonable," "notice," "material") does different work in each.**

**Family resemblance.** PI §§65–71. "Games" share no common essence; they form a network of overlapping and crisscrossing similarities. **No necessary-and-sufficient conditions, no Porphyrian definition, no unique parent class.** Paradigmatic legal concepts — contract, negligence, employee, securities, discrimination, reasonable person — manifestly behave this way.

**Rule-following.** A rule does not determine applications in advance; rule-following is a public practice sustained by communal correction. Whether a fact-pattern "falls under" a shard-axiom is a normative question answered socially (by courts, the bar, expert annotators).

**Design patterns.**
- **Family-resemblance classes alongside sharp classes.** For crisp concepts (`folio:USState`), use standard OWL. For family-resemblance concepts (`folio:UnconscionableContract`, `folio:EmployeeForERISAPurposes`), model as a **prototype cluster**: paradigm instances + weighted similarity edges + optional feature vectors, queried with threshold matching rather than strict subsumption. **Pairs naturally with FOLIO's LLM-embedding search (MCP server, Python library) — but must be schema-distinguished from definitional classes so reasoners don't treat similarity as subsumption.**
- **Language-game context on every shard.** Each shard records speech-act context: *holding, dicta, party-brief-argument, statutory-definition, administrative-interpretation, contractual-term*. Same proposition plays different inferential roles in different games.
- **Jurisdiction and practice area as explicit axes** — exactly what SKOS concept schemes are for.

### Sellars: the Myth of the Given

Sellars's *Empiricism and the Philosophy of Mind* (1956) attacks the idea that knowledge has a foundation in theory-neutral, conceptually-unstructured data. Sensations are caused in us by the world, but **nothing counts as knowledge until it enters "the logical space of reasons, of justifying and being able to justify what one says."** All awareness is conceptually mediated.

**Inferentialism** (Sellars, Brandom): meaning is constituted by inferential role — by what a claim entitles and commits its maker to. To have a concept is to be able to play the game of giving and asking for reasons with it.

**Design patterns.**
- **Every shard is theory-laden; record the theory.** No shard extracted from a case is "just what the case says" — it reflects granularity, vocabulary alignment, doctrinal framing, extractor biases. **Mandatory shard metadata:** `extractor` (version/prompt hash), `framework` (ontological commitments — "treats *consideration* as an element, not a factor"), `reviewer` chain, `conceptual_scheme` (which FOLIO branches or external ontologies in play). **This is the Sellarsian remedy for the Myth of the Given applied to information extraction.**
- **Inferential-role semantics for shard meaning.** A shard's meaning is partially fixed by which shards it entails and is entailed by. Compute and expose its inferential closure under the TBox; do not treat it as semantically self-sufficient by virtue of its triple form.
- **Space-of-reasons vs. space-of-causes distinction.** Clean separation between (a) causal provenance (LLM, temperature, PDF page) and (b) normative justification (axioms, precedents, counter-authorities). **Confusing them — treating high extraction-probability as legal authority — is a category error.**

---

## Part VI. The Modern Stack: RDF/OWL/SKOS, DL, BFO, Conceptual Graphs, FOLIO

The Semantic Web is the direct modern heir to the logical atomist program, with two crucial improvements: **global URIs** replace Russellian acquaintance, and **the open-world assumption** is baked in — making it constitutively holist-friendly.

### Semantic Web / RDF / OWL

Berners-Lee, Hendler, Lassila (*Scientific American* May 2001): RDF triples + ontologies + agents. **OWL 2 DL ≈ SROIQ(D)** — the maximum expressivity that remains decidable; satisfiability is N2ExpTime-complete. **Profiles** trade expressivity for tractability: EL (polynomial, the right default for taxonomies), QL (AC⁰ data complexity), RL.

**Open World Assumption.** Absence of information is *unknown*, not *false*. A sharp architectural choice — **already holist-friendly**: refuses to pretend any local fragment is the whole story.

**SKOS** (W3C Rec 2009). `skos:Concept` is the unit of thought; `skos:prefLabel`/`altLabel`/`hiddenLabel` handle polysemy; `skos:broader`/`narrower` are non-transitive hierarchy predicates; `skos:ConceptScheme` partitions vocabularies. **`skos:Concept` should not be conflated with `owl:Class`** — mixing yields OWL Full and loses DL decidability. FOLIO does assert both on the same IRIs (SKOS as metadata) — a pragmatic compromise that works because SKOS properties are used as annotations rather than axioms.

**Named graphs + RDF-star.** Named graphs (SPARQL 1.1) assign IRIs to triple sets for graph-level provenance. **RDF-star / RDF 1.2** (W3C, advancing 2024–2025) makes quoted triples `⟨⟨s p o⟩⟩` first-class terms, enabling lightweight per-edge annotations (confidence, valid-time, source, asserter) without heavy reification. **This is the 2024/2025 best practice.**

**Design patterns.**
- **RDF triple as canonical minimal shard format.** Every shard serializes to triples + metadata. Stable IRIs under FOLIO or consumer namespace for every entity and shard.
- **TBox/ABox split enforced at shard-type level** — terminology vs. assertion shards have different validation, revision, and reasoning regimes.
- **OWA-aware query semantics.** Distinguish "not asserted" from "asserted false." Where CWA is legally required (exhaustive party lists, enumerated cause-of-action elements, statutory closed enumerations), mark explicitly with `owl:complementOf`, enumerations, `folio:closedUnder` annotations, or a CWA query layer.
- **Named graphs for document-level provenance; RDF-star for per-shard annotation.** Named-graph-per-source-document as default container; RDF-star for confidence/extractor/valid-time without bloating the main graph.
- **Description-logic profile discipline.** Constrain TBox shards to **OWL 2 EL** by default (covers almost all legal-taxonomic axioms; polynomial reasoning with ELK). Reserve SROIQ features for tightly-scoped modules where their expressive payoff justifies worst-case exponential reasoning.

### Barry Smith's BFO

BFO (ISO/IEC 21838-2:2021) is a **realist** upper ontology, representing entities in reality rather than concepts in heads. Smith's long-running polemic against concept-based ontologies is that conflating terminology with what terminology is about produces inconsistencies across conceptual guises.

**Core split: continuant vs. occurrent.** Continuants (objects, qualities, roles, dispositions) are wholly present at each time they exist. Occurrents (processes, events) unfold through time with temporal parts. **The cut maps beautifully onto legal domains:** parties, contracts-as-documents, instruments, rights, obligations, jurisdictions, offices are continuants; filings, hearings, negotiations, breaches, trials, enforcements are occurrents. **Roles** (plaintiff, defendant, trustee) are realizable dependent continuants inhering in parties and realized in processes.

**Design patterns.**
- **BFO-aligned top-level split.** At ingest, every shard's primary subject is typed as `bfo:Continuant` or `bfo:Occurrent`. Parties, instruments, courts, clauses, doctrines = continuants; filings, hearings, breaches, payments, holdings-as-events = occurrents. **Forces discipline on confused extractions** — a "breach" is an occurrent; the *condition of being in breach* is a dependent continuant.
- **Roles as dependent continuants, not subclasses of Person.** Model `PlaintiffRole` as `bfo:Role` inhering in a party and realized in a proceeding. Personhood is essential; plaintiffhood is contingent. FOLIO's existing player/actor structures align.

### Sowa's Conceptual Graphs

A raw RDF triple is semantically thin — cannot natively express n-ary relations, negation, conditionals, or scoped quantifiers without reification. A **conceptual graph** is a richer atomic unit: concepts as typed boxes, relations as arrows, **Peircean contexts as nested ovals** handling negation, quantifier scope, modal embedding. Maps to Common Logic (ISO 24707).

**Design patterns.**
- **Two-layer shard format.** *Simple shards* = RDF triples (fast, queryable, OWL-reasonable). *Complex shards* = CG-structures (or OWL2+SWRL rule forms, or JSON-LD with nested contexts) for propositions with scope, conditionality, or n-ary structure — paradigmatically **case holdings, statutory provisions with conditions, contract clauses with exceptions**. Complex shards decompose into simple shards + a rule-skeleton preserving the structure.
- **Peircean contexts for legal nesting.** Use context-nesting for hypothetical, counterfactual, or party-attributed claims ("The plaintiff alleges that...", "Assuming Delaware law..."). More natural than reifying everything.

### FOLIO itself: a syncretic case study

FOLIO (CC-BY, 18,000+ classes, ALEA Institute) is genuinely syncretic. Its bones are **Porphyrian** (subclass hierarchies), **Fregean** (IRI-identified classes and properties), and **description-logic** (OWL reasoning). Its flesh is **Wittgensteinian** (SKOS alternatives, multi-parents, concept schemes acknowledging fuzzy context-dependent extensions). Its pragmatic governance (federated, open-world, revisable, LLM-augmented via MCP and Python library) is **Quinean**. It is not a pure BFO-style realist upper ontology — it is a **concept-based legal ontology with realist ambitions and Wittgensteinian accommodations**. This is the right design for the domain; legal concepts really are partly about the world and partly about the practice of law.

**FOLIO-specific patterns.**
- **SKOS concept grouping across OWL class splits.** When a term has genuinely distinct senses across jurisdictions, mint separate OWL classes (distinct entity types) linked under a shared SKOS concept grouping. Reserve `owl:equivalentClass` for entity-level equivalence.
- **Multi-parent as family resemblance.** Treat each parent-edge as one "resemblance dimension" rather than a strict is-a. Annotate edges with the dimension they represent (functional, structural, regulatory, historical).
- **SALI legacy identifier transparency.** Preserve `lmss.sali.org` IRI backward-compatibility in shards to maintain institutional continuity.

---

## Part VII. The Architectural Resolution: Moderate Atomism for FOLIO Insights

The central tension is not between atomism and holism as metaphysical positions; it is between **atomism as engineering discipline** (addressable, composable, citable units) and **holism as epistemic honesty** (meaning, verification, and revision happen at the cluster level). The resolution is a **moderate atomism** in which the shard is the unit of representation and addressing, *never* the unit of verification, meaning, or grounding.

The following seven design principles integrate the inheritance. Each maps a philosophical constraint onto a concrete architectural discipline.

### P1 — Atomize for tractability; validate at the cluster level

The shard is the unit of extraction, storage, addressing, citation, and versioning. It is *not* the unit of verification. Every shard belongs to one or more **clusters** (shards from a common document, doctrinal neighborhood, or holding). Test suites, consistency checks, coverage metrics, and adversarial evaluations operate at cluster granularity. A shard internally well-formed but inconsistent with its cluster is suspect. *Warrant: Quine, Duhem-Quine thesis; Aristotle's demonstrative/dialectical tier distinction.*

### P2 — Every shard records its framework

No shard is raw. Mandatory metadata: `extractor_version`, `extraction_prompt_hash`, `source_document` (named graph), `source_span`, `ontological_framework`, `reviewer_chain`, `confidence`, `language_game` (holding / dictum / pleading / statute / contract-term), `jurisdiction`, `valid_time` / `transaction_time`, `asserter`. Use **RDF-star** for the triple + metadata, **named graphs** for document containers. *Warrant: Sellars, Myth of the Given; Frege, context principle; Neurath, protocol sentences with production conditions.*

### P3 — No shard is unrevisable; model the web explicitly

Shards link via domain predicates **and** via `dependsOn` edges (definitional / doctrinal / evidential). Retraction propagates as a configurable wave through dependents. Clients resolve conflicts by policy. Maintain competing extractions as first-class `ExtractionHypothesis` entities rather than silently picking winners. Even the FOLIO TBox is versionable. *Warrant: Quine, web of belief, underdetermination; Davidson/Brandom, perspectival interpretation; Spinoza's explicit-dependency citation as the enabling mechanism.*

### P4 — Separate TBox from ABox; constrain TBox to OWL 2 EL by default

Terminology shards (class inclusions, role hierarchies, compositions over FOLIO concepts) are stable, editorially curated, reasoned at classification time (ELK/HermiT). Assertion shards (case-fact, contract-fact, party-fact) are higher-volume, machine-extracted, reasoned at query time. Use SROIQ features sparingly in scoped modules. Pre-materialize inferred hierarchies; push updates incrementally. *Warrant: Aristotle's ontological square; Aquinas's essence/existence distinction; DL tractability theory.*

### P5 — Embrace OWA; mark CWA islands explicitly

Default query semantics is open-world: absence = unknown, not false. Where closed-world reasoning is legally required (exhaustive party lists, enumerated cause-of-action elements, statutory closed enumerations), mark with `folio:closedUnder` annotations, `owl:AllDisjointClasses`, or explicit enumerations. **Never silently treat OWA as CWA in dashboards or analytics.** Totality claims are explicit scoped shards. *Warrant: Russell's explicit totality facts; Semantic Web architecture; Quinean humility about local fragments.*

### P6 — Family-resemblance handling for polysemous legal concepts

For concepts resistant to necessary-and-sufficient definition (contract, negligence, employee, security, reasonable person, material), use a **three-tier structure**: (i) a SKOS concept grouping the term across jurisdictions; (ii) jurisdiction-specific OWL classes under that grouping with local TBox axioms; (iii) a prototype set of paradigmatic instances with similarity edges and embedding vectors for fuzzy retrieval. **Symbolic subsumption and distributional similarity answer different questions — expose both; never collapse them.** Use SKOS mapping properties (`closeMatch`, `relatedMatch`) and `folio:analogousTo` for cross-jurisdiction alignment; **avoid promiscuous `owl:sameAs`**. *Warrant: later Wittgenstein, family resemblance; Aquinas's analogia entis; SKOS design.*

### P7 — BFO-aligned top-level split

Every shard's primary subject is typed at ingest under a FOLIO spine aligned with BFO: **continuants** (parties, instruments, documents, clauses, roles, obligations, rights, jurisdictions, courts, offices) and **occurrents** (filings, hearings, negotiations, breaches, payments, trials, enforcements, holdings-as-events). Roles are `bfo:Role` dependent continuants inhering in parties and realized in proceedings — not subclasses of `Person`. *Warrant: Barry Smith / BFO realism; Aristotle's primary substance / accident distinction.*

### Shard schema: what 2,500 years of thought suggests every shard carries

Synthesizing, a FOLIO Insights shard optimally carries:

1. A **Fregean triple** in function-argument form (Frege, RDF).
2. A **Tractarian numbered identifier** encoding dependency-tree position (Wittgenstein).
3. A **sense/reference pair** — intensional definition + URI reference (Frege).
4. A **propositional context of extraction** — the source span and the logical form imputed (Frege context principle; Neurath protocol).
5. A **layer tag** — L0 primitive / L1 definitional / L2 composed / L3 jurisdictional; or protocol / derived (Carnap; Neurath).
6. A **type tag** — norm / fact / meaning-postulate / totality / meta (Aristotle, Aquinas, Carnap).
7. A **predication-mode flag** — `perSe` vs. `perAccidens` (Aristotle).
8. A **Hume-fork tag** — analytic / synthetic-a-posteriori / synthetic-a-priori (Hume, Kant).
9. An **epistemic-status flag** — `perSeNotaQuoadSe`, `perSeNotaQuoadNos`, `demonstrable`, `authorityOnly`, `aporetic` (Aquinas, Socrates).
10. A **verification-method pointer** (Vienna Circle).
11. An **explicit-dependencies list** — `prov:wasDerivedFrom` + typed sub-properties (Spinoza, Quine).
12. A **framework identifier** under which meaning postulates apply (Carnap).
13. A **language-game / speech-act context** — holding / dictum / pleading / statute / contract-term (Wittgenstein II).
14. **Full provenance metadata** — extractor version, prompt hash, source URI, pinpoint, reviewer chain, confidence (Sellars, Neurath).
15. A **BFO top-level classification** — continuant vs. occurrent (Smith).

Five shard **types** emerge from the scholastic tradition and cover the common cases:

- **SimpleAssertionShard** — a bare Fregean triple with mandatory provenance (protocol layer).
- **DisputedPropositionShard** — Summa-article schema with `utrum`, objections, sed contra, respondeo, replies.
- **ConflictingAuthoritiesShard** — sic-et-non structure with `sic[]`, `non[]`, reconciliation strategy.
- **GlossShard** — typed annotation (clarificatoria, extensiva, restrictiva, dissentiens, historica) on a base shard.
- **HypothesisShard** — Llullian-generated or inductively-projected, requiring promotion to attested status.

Cross-cutting relations worth minting as first-class FOLIO vocabulary (beyond standard OWL/SKOS/PROV): `folio:analogousTo` (with `primeAnalogate` and `proportionalRelation`), `folio:distinguishes`, `folio:subalternatedTo`, `folio:derivedFromKernel`, `folio:elaborates` (the Tractarian tree edge), `folio:dependsOnAxiom` / `folio:dependsOnDefinition` / `folio:dependsOnPrecedent`, `folio:closedUnder`.

### The shard is a move, not an atom

The final posture is Wittgensteinian: a shard is best understood not as an atom of truth but as a **move in a language-game** — specifically, the game of formal legal knowledge representation, played by extractors, reviewers, reasoners, and downstream consumers. Its meaning is constituted by (i) its inferential role in the graph, (ii) the rules of the game that legitimize its assertion, (iii) the communal norms for its revision.

Frege and Russell gave us the triple. Carnap tried to reduce knowledge to triples. Quine showed the reduction fails. Wittgenstein, Sellars, and Brandom showed why. Aristotle and Aquinas gave us the typed shard with essential vs. incidental modes, middle-term justification, and analogical polysemy. Spinoza gave us explicit-dependency citation as the operative discipline. Leibniz gave us the vision of the *characteristica* + *calculus* the Semantic Web is still executing. Neurath gave us protocol sentences with production conditions. Sellars warned us that no shard is raw. Wittgenstein II gave us family resemblance for the concepts — contract, reasonable, negligence, material — that no definition will ever close.

FOLIO Insights, done right, keeps the triple as engineering primitive, drops atomistic metaphysics, and operationalizes the holist discipline as: disciplined metadata, cluster validation, family-resemblance tolerance, OWA humility, distinction-based polysemy forking, BFO-aligned typing, and revisable web-of-belief topology — all on top of the OWL/SKOS/BFO stack that twenty years of Semantic Web experience has been converging on.

**The shard is useful because it is small. It is dangerous because it looks self-sufficient.** Design FOLIO Insights so that it never *is* self-sufficient — so that every shard wears its context, its theory, its dependencies, its framework, and its revisability on its sleeve. That is the architecture that twenty-five centuries of the best critics of atomism were, in effect, asking for.