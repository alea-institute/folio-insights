"""Phase 8 Plan 08-03 Task 2 — fi:SupersessionAlignmentShape both-polarity tests.

D-10: when shard A fi:supersedes shard B, B.fi:validTimeEnd MUST equal
A.fi:validTimeStart (PRD §21.9 valid-time alignment). The SHACL belt enforces
this at storage / export time. The shape's sh:sparql constraint matches the
BAD case (FILTER on string-inequality of the two timestamps), so a non-empty
result yields ``conforms=False`` (mirrors Phase 7
governance/shapes/supersession_shape.ttl polarity discipline).

Two polarities:
  (1) ALIGNED   — the 10-link chain from Task 1: every link's start == prev
                  link's end → conforms=True.
  (2) MISALIGNED — inline 2-shard fixture where B.validTimeEnd != A.validTimeStart
                  → conforms=False + report mentions SupersessionAlignmentShape.

This test is dep-leak EXEMPT from the temporal/ guard because it lives under
tests/temporal/, not under src/folio_insights/temporal/. pyshacl is allowed
in test code.
"""

from __future__ import annotations

from pathlib import Path

import pyshacl
from rdflib import Graph

from folio_insights.vocab import load_graph


_ALIGNED_FIXTURE = Path(__file__).parent / "fixtures" / "supersession_chain.ttl"


# Misaligned: B.validTimeEnd (2026-04-30) != A.validTimeStart (2026-05-01).
# The two timestamps differ by 1 day, which is exactly the kind of off-by-one
# the shape exists to catch (and which a human reviewer would otherwise miss).
_MISALIGNED_TTL = """
@prefix fi: <https://folio-insights.aleainstitute.ai/vocab/> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<urn:test:misaligned/B>
    fi:validTimeStart "2026-04-01T00:00:00+00:00"^^xsd:dateTime ;
    fi:validTimeEnd   "2026-04-30T00:00:00+00:00"^^xsd:dateTime .

<urn:test:misaligned/A>
    fi:validTimeStart "2026-05-01T00:00:00+00:00"^^xsd:dateTime ;
    fi:supersedes <urn:test:misaligned/B> .
"""


def _load_shapes() -> Graph:
    """The merged vocab graph — includes the appended SupersessionAlignmentShape."""
    return load_graph()


def test_aligned_chain_conforms_true() -> None:
    """Polarity (1): the 10-link chain from Task 1 is perfectly aligned →
    pyshacl returns conforms=True.
    """
    data_g = Graph()
    data_g.parse(str(_ALIGNED_FIXTURE), format="turtle")
    shapes_g = _load_shapes()

    conforms, _report_graph, _report_text = pyshacl.validate(
        data_graph=data_g,
        shacl_graph=shapes_g,
        inference="none",
    )
    assert conforms is True, (
        "Aligned 10-link chain MUST conform to fi:SupersessionAlignmentShape "
        "(every link's start == previous link's end per PRD §21.9). "
        f"Report:\n{_report_text}"
    )


def test_misaligned_chain_conforms_false() -> None:
    """Polarity (2): a 2-shard misaligned chain (1-day gap) →
    pyshacl returns conforms=False and the report mentions
    SupersessionAlignmentShape.
    """
    data_g = Graph()
    data_g.parse(data=_MISALIGNED_TTL, format="turtle")
    shapes_g = _load_shapes()

    conforms, _report_graph, report_text = pyshacl.validate(
        data_graph=data_g,
        shacl_graph=shapes_g,
        inference="none",
    )
    assert conforms is False, (
        "Misaligned chain (B.validTimeEnd != A.validTimeStart) MUST NOT "
        "conform to fi:SupersessionAlignmentShape. "
        f"Report:\n{report_text}"
    )
    assert "SupersessionAlignmentShape" in report_text, (
        "pyshacl report must cite fi:SupersessionAlignmentShape by name so "
        "the violation is greppable. "
        f"Report:\n{report_text}"
    )
