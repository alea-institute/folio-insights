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
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

CONSIDERATION_NAMED_GRAPH = "urn:folio:corpus/consideration-spike"

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


def fixture_framework_iri(framework: str) -> str:
    """The framework IRI for a fixture framework tag (``KeyError`` if unknown)."""
    from folio_insights.vocab._constants import framework_iri

    return framework_iri(FIXTURE_FRAMEWORK_IDS[framework])


class ShardFixture(BaseModel):
    iri: str
    framework: Framework
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
        axiom = s.axiom_summary.replace("\\", "\\\\").replace('"', '\\"')
        src = s.source_doc.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(
            f"<{s.iri}> a fi:ShardFixture ;\n"
            f'    fi:termOfArt "{s.term}" ;\n'
            f"    fi:inFramework <{fixture_framework_iri(s.framework)}> ;\n"
            f'    fi:sourceDoc "{src}" ;\n'
            f'    fi:axiomSummary "{axiom}" .\n\n'
        )
    return "".join(lines)
