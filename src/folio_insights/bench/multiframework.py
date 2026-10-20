"""Synthetic multi-framework corpus for the Phase 9 roll-up (Phase 9 U8).

``bench.generator.BenchGenerator`` emits structurally synthetic N-Quads for
the Phase 0 gates; it never builds a ``Shard``. The Phase 9 roll-up needs
real envelopes that pass storage (model validation, the PII gate, SHACL, the
framework guard and the dependency-cycle guard) and that carry everything
the seven principles act on. This module extends the bench with that corpus
and leaves ``BenchGenerator`` and its byte-identical output untouched.

``MultiFrameworkCorpusGenerator(seed=...).generate()`` returns a
``SyntheticCorpus``: sources with the metadata the P2 framework detector
reads (explicit IDs, a v1 year-suffixed ID, citation forms, a title only the
LLM stage can place, and one source whose LLM answer is unregistered), and
per source a list of ``SyntheticUnit`` specs. A unit becomes a shard only
after the roll-up has detected its source's framework (P2) and typed its
subject (P7), the way Phase 10's minter will: ``mint_shard`` builds the
envelope from a unit plus those two answers.

Planted features (``PlantedFeatures``) give each principle something to
find: a cross-source textual contradiction, a cross-framework citation, a
coverage gap, a formal disjointness clash, a retraction web with a successor,
a supersession pair across two statute versions, a contest, a dependency
3-cycle (which storage must refuse), a closed-world island and a polysemy
term with a disjointness seed between two frameworks.

Everything is synthetic: placeholder senses, made-up concept leaves under
the FOLIO namespace (ancestry supplied by ``folio_parents``, never read from
FOLIO), invented citation strings and dates. No book or source text. The
same seed and size give the same corpus (one ``random.Random`` instance,
sorted iteration; Pitfall 7).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from folio_insights.bfo.spine import FOLIO_BRANCH_SPINE, FOLIO_PREFIX
from folio_insights.frameworks.detector import SourceMetadata
from folio_insights.frameworks.valid_time import SourceTimeMetadata, ValidTimeWindow
from folio_insights.models.framework import Framework

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
FI = "https://folio-insights.aleainstitute.ai/vocab/"
SYNTHETIC_PREDICATE = "synthetic predicate"  # not an IRI: never a formal axiom
EXTRACTED_AT = datetime(2026, 1, 1, tzinfo=UTC)

# Framework a corpus admin registers (P2): an imaginary jurisdiction.
REGISTERED_FRAMEWORK = Framework(
    id="zz.synthetic.code",
    label="Synthetic code of an imaginary jurisdiction",
    jurisdiction="zz.synthetic",
)
UNREGISTERED_FRAMEWORK_ID = "zz.unregistered.body"

UNTYPEABLE_PREFIX = "untypeable"  # subjects a fake BFO LLM must not type


def leaf_concept(branch: int, k: int) -> str:
    return f"{FOLIO_PREFIX}Rsyn{branch:02d}c{k}"


def mid_concept(branch: int) -> str:
    return f"{FOLIO_PREFIX}Rsyn{branch:02d}m"


def planted_concept(branch: int, name: str) -> str:
    return f"{FOLIO_PREFIX}Rsyn{branch:02d}{name}"


@dataclass(frozen=True)
class SyntheticUnit:
    """What an extractor would hand the minter for one shard."""

    key: str                       # stable handle (e.g. "cl-a/3", "planted/retracted")
    span: str
    concept: str                   # FOLIO concept IRI (triple subject + reference)
    sense: str
    logical_form: str
    speech_act: str = "holding"
    subject: str = ""              # what the BFO stage sees as the subject text
    tags: tuple[str, ...] = ()     # verified FOLIO tag IRIs (empty: no rule typing)
    depends_on_shards: tuple[str, ...] = ()       # unit keys
    depends_on_precedents: tuple[str, ...] = ()   # unit keys
    supersedes: str | None = None                 # unit key
    superseded_by: str | None = None              # unit key
    triple: tuple[str, str, str] | None = None    # overrides (concept, predicate, object)
    confidence: float = 0.9


@dataclass(frozen=True)
class SyntheticSource:
    key: str
    uri: str
    metadata: SourceMetadata
    units: tuple[SyntheticUnit, ...]
    expected_framework: str | None   # None: detection must fail the gate


@dataclass(frozen=True)
class PlantedFeatures:
    """Unit keys (and IRIs/terms) of everything planted for the principles."""

    contradiction: tuple[str, str]
    cross_framework_citation: tuple[str, str]          # (citing, cited)
    coverage_gap_concept: str
    coverage_covered_concept: str
    formal_clash: tuple[str, str]
    disjoint_classes: tuple[str, str]
    retracted: str
    successor: str
    direct_dependents: tuple[str, ...]
    deep_dependents: tuple[str, ...]
    superseded: str
    superseding: str
    supersession_reference: str
    contested: str
    resolved: str
    cycle: tuple[SyntheticUnit, ...]                   # never ingestable
    cycle_source: str                                  # source key the cycle claims
    closed_source: str                                 # source key of the island
    polysemy_concept: str                              # concept IRI of the planted term
    polysemy_frameworks: tuple[str, str]


@dataclass(frozen=True)
class SyntheticCorpus:
    seed: int
    sources: tuple[SyntheticSource, ...]
    registered_frameworks: tuple[Framework, ...]
    folio_parents: dict[str, tuple[str, ...]]
    task_tree: tuple[dict[str, Any], ...]
    planted: PlantedFeatures

    def units(self) -> list[tuple[SyntheticSource, SyntheticUnit]]:
        return [(s, u) for s in self.sources for u in s.units]

    def source(self, key: str) -> SyntheticSource:
        return next(s for s in self.sources if s.key == key)

    @property
    def frameworks(self) -> tuple[str, ...]:
        return tuple(sorted({s.expected_framework for s in self.sources if s.expected_framework}))


def unit_iri(source_uri: str, span: str) -> str:
    from folio_insights.shards import mint_shard_iri

    return mint_shard_iri(source_uri, span)[0]


def mint_shard(
    source: SyntheticSource,
    unit: SyntheticUnit,
    *,
    framework_id: str,
    bfo_category: str,
    valid_time: ValidTimeWindow | None,
    iri_of: dict[str, str],
) -> Any:
    """The envelope for ``unit``, given the P2 framework and P7 category
    (what Phase 10's minter fills). ``iri_of`` maps unit keys to IRIs."""
    from folio_insights.shards import SimpleAssertionShard, Triple, mint_shard_iri

    iri, provenance = mint_shard_iri(source.uri, unit.span)
    subject, predicate, obj = unit.triple or (unit.concept, SYNTHETIC_PREDICATE, "synthetic object")
    return SimpleAssertionShard(
        shard_iri=iri,
        provenance_hash=provenance,
        source_uri=source.uri,
        source_span=unit.span,
        extracted_at=EXTRACTED_AT,
        first_extractor_did="did:key:zSyntheticRollupExtractor",
        triple=Triple(subject=subject, predicate=predicate, object=obj),
        sense=unit.sense,
        reference=unit.concept,
        logical_form_imputed=unit.logical_form,
        layer="L3_jurisdictional",
        predication_mode="per_se",
        fork="analytic",
        epistemic_status="authority_only",
        verification_method="textual_citation",
        depends_on_shards=[iri_of[k] for k in unit.depends_on_shards],
        depends_on_precedents=[iri_of[k] for k in unit.depends_on_precedents],
        supersedes=iri_of[unit.supersedes] if unit.supersedes else None,
        superseded_by=iri_of[unit.superseded_by] if unit.superseded_by else None,
        framework_id=framework_id,
        speech_act=unit.speech_act,
        extractor_version="rollup-synthetic-1",
        extraction_prompt_hash="0" * 64,
        extractor_model="synthetic",
        confidence=unit.confidence,
        bfo_category=bfo_category,
        valid_time_start=None if valid_time is None else valid_time.start,
        valid_time_end=None if valid_time is None else valid_time.end,
        transaction_time=EXTRACTED_AT,
    )


# (key, metadata, expected framework). Citation strings and dates are invented.
def _source_specs() -> list[tuple[str, SourceMetadata, str | None]]:
    statute = dict(kind="statute", effective_date=date(2000, 12, 1),
                   amendment_dates=(date(2011, 12, 1), date(2023, 12, 1)))
    return [
        ("cl-a", SourceMetadata(framework_id="us.common_law", time=SourceTimeMetadata(
            kind="case", decision_date=date(2015, 3, 2))), "us.common_law"),
        ("cl-b", SourceMetadata(framework_id="us.common_law"), "us.common_law"),
        # v1 year-suffixed ID: migrated, with a warning (P2 v1 migration).
        ("la-a", SourceMetadata(framework_id="us.louisiana.civil_code.2024"),
         "us.louisiana.civil_code"),
        ("la-b", SourceMetadata(citations=("La. Civ. Code art. 9001 (synthetic)",)),
         "us.louisiana.civil_code"),
        ("fre-2011", SourceMetadata(framework_id="us.federal.fre", time=SourceTimeMetadata(
            **statute, version_date=date(2012, 6, 1))), "us.federal.fre"),
        ("fre-2023", SourceMetadata(framework_id="us.federal.fre", time=SourceTimeMetadata(
            **statute, version_date=date(2024, 1, 1))), "us.federal.fre"),
        ("frcp", SourceMetadata(citations=("Fed. R. Civ. P. 99 (synthetic)", "FRCP 98")),
         "us.federal.frcp"),
        # Only the (fake) LLM stage can place this one.
        ("uk", SourceMetadata(title="synthetic english source"), "uk.england.common_law"),
        ("zz", SourceMetadata(framework_id=REGISTERED_FRAMEWORK.id), REGISTERED_FRAMEWORK.id),
        # The (fake) LLM proposes an unregistered ID: rejected, gate fails.
        ("rogue", SourceMetadata(title="rogue synthetic source"), None),
    ]


@dataclass
class MultiFrameworkCorpusGenerator:
    """Deterministic synthetic multi-framework corpus (see module docstring).

    ``units_per_source`` ordinary units per source (at least 6), plus the
    planted units. The seed drives the units' confidences; every 13th
    ordinary unit is left untagged for the BFO LLM stage, and every second
    of those has a subject the (fake) LLM cannot type, so it gets the
    documented default.
    """

    seed: int = 9
    units_per_source: int = 8
    _rng: random.Random = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.units_per_source < 6:
            raise ValueError("units_per_source must be at least 6")
        self._rng = random.Random(self.seed)

    def generate(self) -> SyntheticCorpus:
        rng = self._rng
        branches = len(FOLIO_BRANCH_SPINE)
        parents: dict[str, tuple[str, ...]] = {}
        for b, branch in enumerate(FOLIO_BRANCH_SPINE):
            parents[mid_concept(b)] = (branch.iri,)

        def concept(c: str, b: int) -> str:
            parents.setdefault(c, (mid_concept(b),))
            return c

        units: dict[str, list[SyntheticUnit]] = {}
        n = 0
        untyped_every = 13
        for key, _meta, _fw in _source_specs():
            speech = "statutory_text" if key.startswith("fre") else "holding"
            rows: list[SyntheticUnit] = []
            for i in range(self.units_per_source):
                b = n % branches
                c = concept(leaf_concept(b, (n // branches) % 2), b)
                untyped = n % untyped_every == untyped_every - 1
                default = n % (2 * untyped_every) == 2 * untyped_every - 1
                subject = (f"{UNTYPEABLE_PREFIX} subject {n}" if default
                           else f"synthetic subject {n}")
                rows.append(SyntheticUnit(
                    key=f"{key}/{i}",
                    span=f"synthetic span {key} {i}",
                    concept=c,
                    sense=f"synthetic sense {n}",
                    logical_form=f"SYN{n % 7}(x, y)",
                    speech_act="practitioner_advice" if i % 5 == 4 else speech,
                    subject=subject,
                    tags=() if untyped else (c,),
                    depends_on_shards=(f"{key}/{i - 1}",) if i % 3 else (),
                    confidence=round(0.6 + rng.random() * 0.4, 3),
                ))
                n += 1
            units[key] = rows

        def add(source: str, unit: SyntheticUnit) -> SyntheticUnit:
            units[source].append(unit)
            return unit

        def planted(source: str, name: str, c: str, sense: str, **kw: Any) -> SyntheticUnit:
            kw.setdefault("tags", (c,))
            kw.setdefault("logical_form", f"PLANTED_{name.upper().replace('-', '_')}(x)")
            kw.setdefault("subject", f"synthetic subject {name}")
            return add(source, SyntheticUnit(
                key=f"planted/{name}", span=f"synthetic span planted {name}",
                concept=c, sense=sense, **kw))

        # P1: a textual contradiction across two sources on one concept.
        c_contra = concept(planted_concept(1, "contra"), 1)
        a = planted("cl-a", "contra-a", c_contra, "A synthetic duty of care is owed.")
        b = planted("cl-b", "contra-b", c_contra, "A synthetic duty of care is not owed.")
        # P1: a cross-framework citation (us common law resting on English law).
        citing = planted("cl-a", "citing", concept(planted_concept(2, "cite"), 2),
                         "A synthetic rule borrowed from abroad.",
                         depends_on_precedents=("uk/0",))
        # P1: coverage. One task leaf is covered by a holding, one only by advice.
        c_gap = concept(planted_concept(3, "gap"), 3)
        planted("cl-b", "advice-only", c_gap, "Synthetic advice on the gap task.",
                speech_act="practitioner_advice")
        c_cov = concept(planted_concept(3, "covered"), 3)
        planted("cl-b", "covered", c_cov, "A synthetic holding on the covered task.")
        # P1: a formal clash: one individual typed into two disjoint classes.
        alpha, beta = "urn:synthetic:class/Alpha", "urn:synthetic:class/Beta"
        individual = "urn:synthetic:individual/1"
        c_formal = concept(planted_concept(4, "formal"), 4)
        fa = planted("zz", "formal-a", c_formal, "A synthetic entity of kind alpha.",
                     triple=(individual, RDF_TYPE, alpha))
        fb = planted("zz", "formal-b", c_formal, "A synthetic entity of kind beta.",
                     triple=(individual, RDF_TYPE, beta))
        # P3: a retraction web with a successor (records link both ways).
        c_ret = concept(planted_concept(5, "ret"), 5)
        planted("cl-b", "retracted", c_ret, "A synthetic rule later withdrawn.",
                superseded_by="planted/successor")
        planted("cl-b", "successor", c_ret, "A synthetic replacement rule.",
                supersedes="planted/retracted")
        planted("cl-b", "dep-1", c_ret, "A synthetic consequence one.",
                depends_on_shards=("planted/retracted",))
        planted("cl-b", "dep-2", c_ret, "A synthetic consequence two.",
                depends_on_precedents=("planted/retracted",))
        planted("cl-b", "dep-deep", c_ret, "A synthetic consequence of a consequence.",
                depends_on_shards=("planted/dep-1",))
        # P3: supersession across two statute versions (same reference).
        c_sup = concept(planted_concept(6, "sup"), 6)
        planted("fre-2011", "rule-old", c_sup, "Synthetic rule text, earlier version.",
                speech_act="statutory_text")
        planted("fre-2023", "rule-new", c_sup, "Synthetic rule text, later version.",
                speech_act="statutory_text", supersedes="planted/rule-old")
        # P3: contest (one stays contested, one is resolved).
        planted("frcp", "contested", concept(planted_concept(7, "contest"), 7),
                "A synthetic procedural rule under dispute.")
        planted("frcp", "resolved", concept(planted_concept(7, "resolve"), 7),
                "A synthetic procedural rule once disputed.")
        # P3: a 3-cycle; storage must refuse it (never ingested).
        c_cyc = concept(planted_concept(8, "cycle"), 8)
        cycle = tuple(
            SyntheticUnit(key=f"cycle/{x}", span=f"synthetic span cycle {x}", concept=c_cyc,
                          sense=f"synthetic cyclic sense {x}", logical_form="CYC(x)",
                          subject=f"synthetic subject cycle {x}", tags=(c_cyc,),
                          depends_on_shards=(f"cycle/{y}",))
            for x, y in (("a", "b"), ("b", "c"), ("c", "a"))
        )
        # P6: one term used by three shards in each of two frameworks.
        term = concept(planted_concept(9, "poly"), 9)
        senses = {
            "cl": ("Synthetic bargained exchange binds a promise.",
                   "Synthetic detriment to the promisee supports a promise.",
                   "Synthetic reciprocal inducement makes a promise binding."),
            "la": ("Synthetic lawful cause grounds an obligation.",
                   "Synthetic motive of the obligor sustains a duty.",
                   "Synthetic reason for obligating oneself suffices."),
        }
        for tag, source_keys in (("cl", ("cl-a", "cl-b", "cl-a")), ("la", ("la-a", "la-b", "la-a"))):
            for i, (src, text) in enumerate(zip(source_keys, senses[tag], strict=True)):
                planted(src, f"poly-{tag}-{i}", term, text, logical_form=text)

        sources = []
        for key, meta, fw in _source_specs():
            sources.append(SyntheticSource(
                key=key, uri=f"urn:synthetic:source/{key}", metadata=meta,
                units=tuple(units[key]), expected_framework=fw,
            ))
        task_tree = (
            {"id": "task-root", "parent_id": None, "label": "Synthetic root task"},
            {"id": "task-covered", "parent_id": "task-root", "label": "Synthetic covered task",
             "folio_iri": c_cov},
            {"id": "task-gap", "parent_id": "task-root", "label": "Synthetic uncovered task",
             "folio_iri": c_gap},
        )
        return SyntheticCorpus(
            seed=self.seed,
            sources=tuple(sources),
            registered_frameworks=(REGISTERED_FRAMEWORK,),
            folio_parents={k: parents[k] for k in sorted(parents)},
            task_tree=task_tree,
            planted=PlantedFeatures(
                contradiction=(a.key, b.key),
                cross_framework_citation=(citing.key, "uk/0"),
                coverage_gap_concept=c_gap,
                coverage_covered_concept=c_cov,
                formal_clash=(fa.key, fb.key),
                disjoint_classes=(alpha, beta),
                retracted="planted/retracted",
                successor="planted/successor",
                direct_dependents=("planted/dep-1", "planted/dep-2"),
                deep_dependents=("planted/dep-deep",),
                superseded="planted/rule-old",
                superseding="planted/rule-new",
                supersession_reference=c_sup,
                contested="planted/contested",
                resolved="planted/resolved",
                cycle=cycle,
                cycle_source="cl-a",
                closed_source="frcp",
                polysemy_concept=term,
                polysemy_frameworks=("us.common_law", "us.louisiana.civil_code"),
            ),
        )


__all__ = [
    "MultiFrameworkCorpusGenerator",
    "PlantedFeatures",
    "REGISTERED_FRAMEWORK",
    "SyntheticCorpus",
    "SyntheticSource",
    "SyntheticUnit",
    "UNREGISTERED_FRAMEWORK_ID",
    "UNTYPEABLE_PREFIX",
    "leaf_concept",
    "mint_shard",
    "unit_iri",
]
