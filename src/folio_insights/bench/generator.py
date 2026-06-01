"""1M-triple scaled-real corpus generator (D-13, D-14, D-15, D-16).

Scope:
- Emit structurally-correct RDF 1.2 N-Quads distributed across THREE named
  graphs (advocacy / fre / restatement — STORAGE-03) with seeded RNG.
- Attach annotation-pipe SEMANTICS (fi:confidence, fi:validFrom on the subject
  triple) as rdf:Statement reification — NEVER `<<>>` subject position
  (Pitfall 1 BLOCKING).
- Replay bitemporal edits/supersessions via fi:supersededBy chains up to the
  profile's configured edit_rounds depth.
- Single `random.Random(seed)` instance threaded everywhere (Pitfall 7).

Determinism contract (D-15):
- Same --seed produces byte-identical N-Quads output across runs and across
  fresh Python processes (verified: pyoxigraph.Store.dump iterates in a stable
  SPO-ordered sequence that does not depend on insertion order, RNG state, or
  process PID).
- All collection iterations are pre-sorted; no module-level random; no NumPy RNG.

Phase 0 implementation note:
- Emits structurally-synthetic quads driven by the seeded RNG — does NOT call
  the v1 PipelineOrchestrator live (avoids bootstrap circularity; the v2
  extraction pipeline is not yet wired for re-extraction against live corpora).
  PROFILES encode v1 real-corpus subtype-ratio data per D-03.
- When Phase 10 Stage 8 Shard Minter lands, this class gains an optional
  `real_extraction=True` path routed through v1 extraction. For Gate 1-5
  measurement the synthesized RDF pattern is sufficient — the gates test
  syntax, perf, image, and digest, not extraction fidelity.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from pathlib import Path

from pyoxigraph import (
    Literal,
    NamedNode,
    Quad,
    RdfFormat,
    Store,
)

from folio_insights.bench.profiles import PROFILES, PhaseProfile

# ── Phase 8 D-02 / D-04 vocab pin ──────────────────────────────────────────
#
# Per-shard ``fi:vocabVersion`` quad emission stamps every generated shard
# with the source-of-truth FOLIO Insights v2.0 vocabulary version constant
# owned by ``folio_insights.vocab`` (Plan 08-01).
from folio_insights.vocab._constants import VOCAB_VERSION  # WR-01: avoid pyoxigraph import via vocab/__init__

logger = logging.getLogger(__name__)

# Vocab namespaces — MUST match Phase 8 fi:* when those land; for Phase 0
# the generator uses stable canonical IRIs.
FI = "https://folio-insights.aleainstitute.ai/vocab/"
CORPUS = "https://folio-insights.aleainstitute.ai/corpus/"
SHARD = "https://folio-insights.aleainstitute.ai/shard/"
CONCEPT = "https://folio-insights.aleainstitute.ai/concept/"
FRAMEWORK = "https://folio-insights.aleainstitute.ai/framework/"
RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
XSD = "http://www.w3.org/2001/XMLSchema#"

_A_PRED = NamedNode(f"{RDF_NS}type")
_RDF_STMT = NamedNode(f"{RDF_NS}Statement")
_RDF_SUBJ = NamedNode(f"{RDF_NS}subject")
_RDF_PRED = NamedNode(f"{RDF_NS}predicate")
_RDF_OBJ = NamedNode(f"{RDF_NS}object")
_DECIMAL = NamedNode(f"{XSD}decimal")

_FW_CHOICES: tuple[str, ...] = (
    "us.federal.frcp",
    "us.federal.fre",
    "us.restatement.contracts",
)


@dataclass
class BenchGenerator:
    """D-13 scaled-real benchmark corpus generator.

    Seed + phase profile together fully determine the output. Two invocations
    with identical seed + profile produce byte-identical N-Quads (D-15).
    """

    seed: int
    profile_name: str = "phase-0-gate"
    _rng: random.Random = field(init=False, repr=False)
    _profile: PhaseProfile = field(init=False, repr=False)

    def __post_init__(self) -> None:
        # Pitfall 7: single explicit RNG instance, threaded everywhere below.
        if self.profile_name not in PROFILES:
            raise ValueError(
                f"Unknown profile {self.profile_name!r}; "
                f"available: {sorted(PROFILES)}"
            )
        self._rng = random.Random(self.seed)
        self._profile = PROFILES[self.profile_name]

    def generate(self, target_triples: int, output_path: Path) -> Path:
        """Produce a deterministic N-Quads file with roughly `target_triples` quads.

        Side-effect: writes `output_path` (parent dirs created).
        Returns: the resolved `output_path` (echoed for CLI callers).

        The final quad count may be slightly below the target due to
        per-corpus share rounding — callers should allow ~0.1% tolerance.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # In-memory Store — we bulk-add, then dump. A disk-backed Store would
        # introduce RocksDB mtime variance into ancillary files (not the
        # N-Quads dump itself, but into the Store lifecycle). Keep everything
        # in memory for clean determinism.
        store = Store(path=None)
        triples_emitted = 0

        # Pitfall 7: pre-sort the corpus-name list; iterate in deterministic order.
        corpora_with_shares = sorted(
            [
                ("advocacy", self._profile.advocacy_share),
                ("fre", self._profile.fre_share),
                ("restatement", self._profile.restatement_share),
            ],
            key=lambda x: x[0],
        )

        for corpus_name, share in corpora_with_shares:
            graph_iri = NamedNode(f"{CORPUS}{corpus_name}")
            corpus_target = int(target_triples * share)
            emitted_for_corpus = 0
            shard_idx = 0
            while emitted_for_corpus < corpus_target:
                subtype = self._pick_subtype()
                shard_quads = self._emit_shard_quads(
                    corpus_name=corpus_name,
                    subtype=subtype,
                    shard_idx=shard_idx,
                    graph_iri=graph_iri,
                )
                for quad in shard_quads:
                    store.add(quad)
                    emitted_for_corpus += 1
                    triples_emitted += 1
                    if emitted_for_corpus >= corpus_target:
                        break
                shard_idx += 1

        logger.info(
            "Emitting %d quads from store to %s (profile=%s, seed=%s)",
            triples_emitted,
            output_path,
            self._profile.name,
            self.seed,
        )

        # Dump as N-Quads (all named graphs in one file).
        # pyoxigraph emits a stable SPO-ordered sequence — determinism verified
        # across fresh Python processes (see generator module docstring).
        with open(output_path, "wb") as f:
            store.dump(f, format=RdfFormat.N_QUADS)

        return output_path

    def _pick_subtype(self) -> str:
        """Weighted random subtype per D-03 ratios, using self._rng (Pitfall 7).

        Sorted-key iteration ensures profile-to-output mapping is stable.
        """
        weights = self._profile.subtype_weights
        # Pitfall 7: sort keys before iteration for determinism
        keys = sorted(weights.keys())
        cumweights: list[float] = []
        total = 0.0
        for k in keys:
            total += weights[k]
            cumweights.append(total)
        r = self._rng.random() * total
        # WR-02: strict less-than so a zero-weight key (cumweight equal to prior
        # cumweight) is never selected. rng.random() returns [0.0, 1.0) so the
        # loop always matches before exhaustion under non-zero total weights;
        # the keys[-1] return below is a floating-point safety valve.
        for k, cw in zip(keys, cumweights, strict=True):
            if r < cw:
                return k
        return keys[-1]

    def _emit_shard_quads(
        self,
        corpus_name: str,
        subtype: str,
        shard_idx: int,
        graph_iri: NamedNode,
    ) -> list[Quad]:
        """Emit one shard's worth of quads in the given named graph.

        Structure per shard (shard_idx → deterministic IRIs):
        - Base quads: type, corpus, framework
        - Subject-concept triple
        - rdf:Statement reification of the subject triple (RDF-12 annotation-pipe
          SEMANTICS — the object-position-only constraint is honored by using
          reification instead of `<<...>>` subject terms; Pitfall 1)
        - fi:confidence literal on the reified statement
        - fi:epistemicStatus "aporetic" for DisputedProposition subtype
        - fi:supersededBy chain for (profile.edit_rounds - 1) edits
        - fi:dependsOnAxiom edge with probability == profile.adversarial_density
        """
        shard_iri = NamedNode(f"{SHARD}{corpus_name}/{shard_idx:08x}")
        out: list[Quad] = []

        # Base type quad
        out.append(
            Quad(shard_iri, _A_PRED, NamedNode(f"{FI}{subtype}Shard"), graph_iri)
        )
        # Corpus quad
        out.append(
            Quad(
                shard_iri,
                NamedNode(f"{FI}corpus"),
                NamedNode(f"{CORPUS}{corpus_name}"),
                graph_iri,
            )
        )
        # Framework quad (deterministic per shard_idx)
        fw = _FW_CHOICES[shard_idx % len(_FW_CHOICES)]
        out.append(
            Quad(
                shard_iri,
                NamedNode(f"{FI}framework"),
                NamedNode(f"{FRAMEWORK}{fw}"),
                graph_iri,
            )
        )

        # ── Phase 8 D-04 (Plan 08-02): per-shard fi:vocabVersion pin ──
        # Deterministic insertion point: AFTER framework, BEFORE the
        # subject-concept triple. Shifts every Phase 0 digest by exactly N
        # quads (one per shard); the byte-stability contract (D-15) holds
        # because the insertion is positionally invariant under fixed seed.
        out.append(
            Quad(
                shard_iri,
                NamedNode(f"{FI}vocabVersion"),
                Literal(VOCAB_VERSION),
                graph_iri,
            )
        )

        # Subject-concept triple
        concept = NamedNode(f"{CONCEPT}{subtype.lower()}-{shard_idx % 50}")
        subject_pred = NamedNode(f"{FI}subject")
        out.append(Quad(shard_iri, subject_pred, concept, graph_iri))

        # Annotation on the subject triple — reified form (RDF-12 object-only
        # constraint honored; never `<<...>>` subject term). RDF 1.2 Turtle
        # annotation-pipe `?s ?p ?o {| fi:confidence ?c |}` normalizes into
        # this reification when serialized to N-Quads.
        stmt_iri = NamedNode(f"{SHARD}{corpus_name}/{shard_idx:08x}/stmt0")
        out.append(Quad(stmt_iri, _A_PRED, _RDF_STMT, graph_iri))
        out.append(Quad(stmt_iri, _RDF_SUBJ, shard_iri, graph_iri))
        out.append(Quad(stmt_iri, _RDF_PRED, subject_pred, graph_iri))
        out.append(Quad(stmt_iri, _RDF_OBJ, concept, graph_iri))
        conf = round(0.5 + self._rng.random() * 0.5, 3)
        out.append(
            Quad(
                stmt_iri,
                NamedNode(f"{FI}confidence"),
                Literal(str(conf), datatype=_DECIMAL),
                graph_iri,
            )
        )

        # Epistemic status for DisputedProposition
        if subtype == "DisputedProposition":
            out.append(
                Quad(
                    shard_iri,
                    NamedNode(f"{FI}epistemicStatus"),
                    Literal("aporetic"),
                    graph_iri,
                )
            )

        # Bitemporal-edit rounds — supersession chain
        for round_idx in range(self._profile.edit_rounds - 1):
            succ_iri = NamedNode(
                f"{SHARD}{corpus_name}/{shard_idx:08x}/v{round_idx + 1:02x}"
            )
            out.append(
                Quad(
                    shard_iri,
                    NamedNode(f"{FI}supersededBy"),
                    succ_iri,
                    graph_iri,
                )
            )

        # Adversarial-density injection (Phase 16 profile skews this)
        if self._rng.random() < self._profile.adversarial_density:
            adv_target = NamedNode(
                f"{SHARD}adversarial/{self._rng.randrange(1000):08x}"
            )
            out.append(
                Quad(
                    shard_iri,
                    NamedNode(f"{FI}dependsOnAxiom"),
                    adv_target,
                    graph_iri,
                )
            )

        return out
