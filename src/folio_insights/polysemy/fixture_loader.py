"""Loader for Phase 1 hand-curated consideration shards (D-1).

Each JSON shard under
`.planning/phases/01-polysemy-distinguo-spike/fixtures/consideration/` carries
a `framework` tag + verbatim excerpt + axiom summary. This module converts
those JSONs to validated `ShardFixture` instances (pydantic) and provides a
TTL-emission helper consumed by the 01-03 detector / 01-04 distinguo pipelines.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

CONSIDERATION_NAMED_GRAPH = "urn:folio:corpus/consideration-spike"

# The Phase 1 spike's framework labels. Phase 9 U6 fixtures (and shards read
# from P1 clusters) name registered framework IDs instead; ``ShardFixture``
# accepts either, and every consumer resolves through ``resolve_framework_id``.
Framework = Literal["CommonLaw", "CivilLaw", "Restatement", "FRE", "UCC"]

# Phase 9 U0/U2: fi:inFramework is an ObjectProperty, so a fixture's framework
# tag is emitted as the IRI of its registered framework, never as a literal.
# Every ID here is in the starter set (frameworks/default_frameworks.json).
FIXTURE_FRAMEWORK_IDS: dict[str, str] = {
    "CommonLaw": "us.common_law",
    "CivilLaw": "us.louisiana.civil_code",
    "Restatement": "us.restatement_2d.contracts",
    "FRE": "us.federal.fre",
    "UCC": "us.ucc",
}


# Characters Turtle/SPARQL IRIREF forbids between ``<`` and ``>`` (RDF 1.1 Turtle §6.5).
_IRIREF_ILLEGAL = re.compile(r'[\x00-\x20<>"{}|^`\\]')
# A scheme (RFC 3987): an absolute IRI is needed in hand-built Turtle.
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")


def check_iri(value: object) -> str:
    """Return ``value`` if it can sit inside ``<...>`` in Turtle, else raise
    ``ValueError``: it must be an absolute IRI with none of the characters
    IRIREF forbids, so it can never close the IRI and inject triples."""
    if not isinstance(value, str) or not _SCHEME.match(value) or _IRIREF_ILLEGAL.search(value):
        raise ValueError(f"{value!r} is not an absolute IRI usable in Turtle (IRIREF)")
    return value


def _turtle_literal(text: str) -> str:
    """Escape ``text`` for a ``"..."`` Turtle literal (ECHAR)."""
    return (
        text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
    )


def resolve_framework_id(framework: str) -> str:
    """The registered-framework ID for a spike label or a framework ID.

    A spike label maps through ``FIXTURE_FRAMEWORK_IDS``; anything else must
    already match the framework ID pattern (``MalformedFrameworkId`` if not).
    Registration itself is the caller's check (``candidates`` and the labeled
    set resolve against the corpus ``FrameworkRegistry``).
    """
    from folio_insights.models.framework import check_framework_id

    return check_framework_id(FIXTURE_FRAMEWORK_IDS.get(framework, framework))


def fixture_framework_iri(framework: str) -> str:
    """The framework IRI for a fixture framework tag or framework ID."""
    from folio_insights.vocab._constants import framework_iri

    return framework_iri(resolve_framework_id(framework))


class ShardFixture(BaseModel):
    iri: str
    framework: str = Field(
        description="A spike label (``Framework``) or a registered framework ID.",
    )
    source_doc: str = Field(min_length=1)
    extracted_text: str = Field(min_length=1)
    axiom_summary: str = Field(
        min_length=1,
        description=(
            "One-sentence axiom proxy. Required to prevent Pitfall 1 "
            "(flagging on surface text instead of axioms)."
        ),
    )
    prime_analogate_hint: str | None = None
    proportional_relation_hint: str | None = None
    term: str = Field(default="consideration")

    @field_validator("framework")
    @classmethod
    def _known_framework(cls, value: str) -> str:
        resolve_framework_id(value)  # a spike label or a pattern-valid framework ID
        return value

    @property
    def framework_id(self) -> str:
        return resolve_framework_id(self.framework)


def load_consideration_fixtures(fixture_dir: Path) -> list[ShardFixture]:
    """Load + validate all `*.json` shards from a directory.

    Sorted by filename for deterministic test ordering. Raises
    `pydantic.ValidationError` if any shard is missing required fields
    (e.g. empty `axiom_summary`), which guards Pitfall 1.
    """
    shards: list[ShardFixture] = []
    for path in sorted(fixture_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        shards.append(ShardFixture.model_validate(payload))
    return shards


def _shard_hex8(shard: ShardFixture) -> str:
    return hashlib.sha256(shard.iri.encode("utf-8")).hexdigest()[:8]


def consideration_fixtures_to_ttl(shards: list[ShardFixture]) -> str:
    """Emit a minimal TTL fragment. Consumed by the 01-03 detector via
    PyoxigraphStore bulk-load into named graph `urn:folio:corpus/consideration-spike`.

    The shape is intentionally lean: a single `fi:ShardFixture` class per shard
    with `fi:termOfArt`, `fi:sourceDoc`, `fi:axiomSummary` data-properties and
    `fi:inFramework` linking the framework's IRI (an ObjectProperty — Phase 9
    U0 fixed the literal this used to emit). Full distinguo vocabulary is
    emitted by 01-04, not here.
    """
    header = (
        "@prefix fi: <https://folio-insights.aleainstitute.ai/vocab/> .\n"
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n\n"
    )
    lines = [header]
    for s in shards:
        # Every interpolated value is escaped (literals) or checked (IRIs), so
        # fixture text can never close a literal or an IRI and inject triples.
        lines.append(
            f"<{check_iri(s.iri)}> a fi:ShardFixture ;\n"
            f'    fi:termOfArt "{_turtle_literal(s.term)}" ;\n'
            f"    fi:inFramework <{check_iri(fixture_framework_iri(s.framework))}> ;\n"
            f'    fi:sourceDoc "{_turtle_literal(s.source_doc)}" ;\n'
            f'    fi:axiomSummary "{_turtle_literal(s.axiom_summary)}" .\n\n'
        )
    return "".join(lines)
