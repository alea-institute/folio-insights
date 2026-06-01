"""Phase 8 Plan 08-04 — predicate drift audit (D-12 + D-13 + Plan 08-04 acceptance).

Cross-checks every ``fi:*`` predicate emitted by Phase 2–7 source code against
``src/folio_insights/vocab/predicates.ttl`` + ``classes.ttl`` + ``shapes.ttl``
(Plan 08-01).  Any emitted local name MUST be either:

  (a) declared in ``predicates.ttl`` (Object/Datatype/Annotation property), OR
  (b) declared as ``owl:Class`` in ``classes.ttl``, OR
  (c) declared as a ``sh:NodeShape`` in ``shapes.ttl``, OR
  (d) explicitly waived in ``DOCUMENTED_WAIVERS`` with a cited rationale that
      points at the audit-report row in ``08-DRIFT-AUDIT.md``.

The 4 D-12 named suspects (``fi:hasRole``, ``fi:signedAction``,
``fi:GovernanceLog``, ``fi:supersedes``/``fi:supersededBy``) carry dedicated
assertions further down — they are not just enumeration entries.

D-13 SCOPE DISCIPLINE: every in-scope fix lands as an atomic commit
``fix(08): align fi:X with PRD §7.1`` and is documented in the audit report.
Out-of-scope mismatches (renames, broader refactors, new features) are
deferred and waived here with a citation.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import get_args as _get_args

import pytest
from rdflib import OWL, RDF, URIRef
from rdflib.namespace import Namespace

from folio_insights.vocab import FI_PREFIX, load_graph
from folio_insights.shards.envelope import SignedAction

SH = Namespace("http://www.w3.org/ns/shacl#")

# WR-03: anchor all source-tree paths to __file__ so the audit doesn't
# silently no-op when pytest is invoked from a non-root cwd. pytest does
# not chdir to rootdir; bare relative paths previously evaluated against
# the process cwd and (when wrong) returned an empty scan with vacuous
# pass.
_REPO_ROOT = Path(__file__).parent.parent.parent  # tests/vocab/ → repo root
_SOURCE_ROOT = _REPO_ROOT / "src" / "folio_insights"
_SHAPES_TTL = _SOURCE_ROOT / "vocab" / "shapes.ttl"

# ---------------------------------------------------------------------------
# Scan configuration
# ---------------------------------------------------------------------------

# Source roots whose ``*.py`` + ``*.ttl`` we scan for ``fi:<localName>`` hits.
_SOURCE_PACKAGE_DIRS: tuple[str, ...] = (
    "governance",
    "shards",
    "polysemy",
    "bench",
    "revision",
    "temporal",
)

# Local-names that are emitted by source code but legitimately do NOT belong
# in the canonical fi: vocab (because they are shape identifiers internal to a
# per-package SHACL file, or test/fixture sentinels).  Each entry is keyed by
# the local name; the value is the audit-report row that explains the waiver.
DOCUMENTED_WAIVERS: Mapping[str, str] = {
    # ── Per-package SHACL NodeShape identifiers (live in governance/*.ttl
    # not vocab/*.ttl on purpose).  Plan 08-01 D-08 split-layout discipline:
    # only the vocab-anchor shapes (VocabPinShape, SignedActionEnumShape,
    # RoleEnumShape, SupersessionAlignmentShape) live in vocab/shapes.ttl;
    # per-event governance shapes stay co-located with the governance
    # subsystem so the audit-trail belt and the dep-leak guard are sharper.
    "ContestShape": "08-DRIFT-AUDIT.md §Waiver-1 — governance subsystem shape",
    "ContestResolutionShape": "08-DRIFT-AUDIT.md §Waiver-1 — governance subsystem shape",
    "PromotionShape": "08-DRIFT-AUDIT.md §Waiver-1 — governance subsystem shape",
    "RetractionShape": "08-DRIFT-AUDIT.md §Waiver-1 — governance subsystem shape",
    "SupersessionShape": "08-DRIFT-AUDIT.md §Waiver-1 — governance subsystem shape",
    "RoleAssertionShape": "08-DRIFT-AUDIT.md §Waiver-1 — governance subsystem shape",
    "RoleRevocationShape": "08-DRIFT-AUDIT.md §Waiver-1 — governance subsystem shape",
    "GovernanceLogShape": "08-DRIFT-AUDIT.md §Waiver-1 — governance subsystem shape",
    "ForwardOnlyShape": "08-DRIFT-AUDIT.md §Waiver-1 — revision subsystem shape",
    # ── Test-fixture / runtime sentinels (not vocabulary predicates).
    "PrototypeCluster_": "08-DRIFT-AUDIT.md §Waiver-2 — runtime fixture marker",
    "ShardFixture": "08-DRIFT-AUDIT.md §Waiver-2 — test fixture marker",
    "GovernanceEvent": "08-DRIFT-AUDIT.md §Waiver-2 — Phase 7 internal urn-prefix sentinel",
}


_FI_LOCAL_RE = re.compile(r"fi:([a-zA-Z][a-zA-Z0-9_]*)")


def _scan_emitted_predicates() -> dict[str, set[str]]:
    """Return ``{local_name: {source_file, ...}}`` for every ``fi:*`` hit.

    Looks at ``*.py`` and ``*.ttl`` files under each of the documented
    Phase 2–7 source packages (D-12 scope).
    """
    root = _SOURCE_ROOT
    sources: dict[str, set[str]] = {}
    for pkg in _SOURCE_PACKAGE_DIRS:
        pkg_root = root / pkg
        if not pkg_root.exists():
            continue
        for path in [*pkg_root.rglob("*.py"), *pkg_root.rglob("*.ttl")]:
            text = path.read_text(encoding="utf-8")
            for match in _FI_LOCAL_RE.finditer(text):
                name = match.group(1)
                sources.setdefault(name, set()).add(str(path))
    return sources


def _declared_local_names() -> set[str]:
    """Collect declared local names from the loaded vocab graph.

    Counts subjects in the canonical ``fi:`` namespace whose ``rdf:type`` is
    one of:
      * ``owl:ObjectProperty`` / ``owl:DatatypeProperty`` / ``owl:AnnotationProperty``
      * ``owl:Class``
      * ``sh:NodeShape``
      * ``owl:NamedIndividual``
    """
    g = load_graph(include_bfo_mapping=True)
    accepted_types = {
        OWL.ObjectProperty,
        OWL.DatatypeProperty,
        OWL.AnnotationProperty,
        OWL.Class,
        SH.NodeShape,
        OWL.NamedIndividual,
    }
    declared: set[str] = set()
    for subj, _, obj in g.triples((None, RDF.type, None)):
        if obj not in accepted_types:
            continue
        s = str(subj)
        if s.startswith(FI_PREFIX):
            declared.add(s[len(FI_PREFIX):])
    return declared


# ---------------------------------------------------------------------------
# Enumeration test — 1 sweeping cross-check (D-12)
# ---------------------------------------------------------------------------


def test_every_emitted_predicate_is_declared_or_waived() -> None:
    """Every emitted local name must be either declared in vocab or waived."""
    sources = _scan_emitted_predicates()
    emitted = set(sources)
    declared = _declared_local_names()
    waived = set(DOCUMENTED_WAIVERS)

    missing = sorted(emitted - declared - waived)
    if missing:
        lines = ["The following emitted fi:* predicates are neither declared in vocab nor waived:"]
        for name in missing:
            sample = sorted(sources[name])[0]
            lines.append(f"  fi:{name}   first seen in {sample}")
        lines.append("")
        lines.append("D-13: either add a declaration to vocab/predicates.ttl (or classes.ttl)")
        lines.append("via an atomic 'fix(08): align fi:X with PRD §7.1' commit, OR add the")
        lines.append("predicate to DOCUMENTED_WAIVERS with a citation to 08-DRIFT-AUDIT.md.")
        raise AssertionError("\n".join(lines))


# ---------------------------------------------------------------------------
# 4 explicit D-12 named-suspect tests
# ---------------------------------------------------------------------------


def _vocab_graph_with_bfo():
    return load_graph(include_bfo_mapping=True)


def test_hasRole_datatype_with_sh_in_enum() -> None:
    """D-12 Suspect 1: fi:hasRole DatatypeProperty + sh:in role enum."""
    g = _vocab_graph_with_bfo()
    has_role = URIRef(FI_PREFIX + "hasRole")
    assert (has_role, RDF.type, OWL.DatatypeProperty) in g, (
        "fi:hasRole must be declared as owl:DatatypeProperty (PRD §7.1)"
    )

    role_enum_shape = URIRef(FI_PREFIX + "RoleEnumShape")
    assert (role_enum_shape, RDF.type, SH.NodeShape) in g, (
        "fi:RoleEnumShape must be declared as sh:NodeShape in vocab/shapes.ttl (Plan 08-01)"
    )

    # The sh:in list must enumerate exactly: extractor / reviewer / arbiter / corpus_admin.
    shapes_text = _SHAPES_TTL.read_text(encoding="utf-8")
    for role in ("extractor", "reviewer", "arbiter", "corpus_admin"):
        assert f'"{role}"' in shapes_text, (
            f"fi:RoleEnumShape sh:in must include {role!r} (PRD §7.1)"
        )


def test_signedAction_datatype_with_13_value_enum() -> None:
    """D-12 Suspect 2: fi:signedAction DatatypeProperty + 13-value sh:in mirror."""
    g = _vocab_graph_with_bfo()
    signed_action = URIRef(FI_PREFIX + "signedAction")
    assert (signed_action, RDF.type, OWL.DatatypeProperty) in g, (
        "fi:signedAction must be owl:DatatypeProperty (PRD §7.1)"
    )

    enum_shape = URIRef(FI_PREFIX + "SignedActionEnumShape")
    assert (enum_shape, RDF.type, SH.NodeShape) in g, (
        "fi:SignedActionEnumShape must be declared as sh:NodeShape in vocab/shapes.ttl"
    )

    # Mirror the 13-value SignedAction Literal from envelope.py:85.
    expected_values = set(_get_args(SignedAction))
    shapes_text = _SHAPES_TTL.read_text(encoding="utf-8")
    for value in expected_values:
        assert f'"{value}"' in shapes_text, (
            f"fi:SignedActionEnumShape sh:in must include {value!r} "
            f"(mirrors envelope.py:85 SignedAction Literal)"
        )


def test_GovernanceLog_class_declared() -> None:
    """D-12 Suspect 3: fi:GovernanceLog declared as owl:Class in classes.ttl."""
    g = _vocab_graph_with_bfo()
    gov_log = URIRef(FI_PREFIX + "GovernanceLog")
    assert (gov_log, RDF.type, OWL.Class) in g, (
        "fi:GovernanceLog must be declared as owl:Class in vocab/classes.ttl"
    )


def test_supersedes_inverseOf_supersededBy() -> None:
    """D-12 Suspect 4: fi:supersedes + fi:supersededBy declared + owl:inverseOf link."""
    g = _vocab_graph_with_bfo()
    sup = URIRef(FI_PREFIX + "supersedes")
    sup_by = URIRef(FI_PREFIX + "supersededBy")

    assert (sup, RDF.type, OWL.ObjectProperty) in g, "fi:supersedes must be owl:ObjectProperty"
    assert (sup_by, RDF.type, OWL.ObjectProperty) in g, "fi:supersededBy must be owl:ObjectProperty"

    inverse_link = (
        (sup, OWL.inverseOf, sup_by) in g
        or (sup_by, OWL.inverseOf, sup) in g
    )
    assert inverse_link, (
        "fi:supersedes and fi:supersededBy must be linked by owl:inverseOf (D-10)"
    )
