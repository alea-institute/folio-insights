"""Content-free projections of explicitly selected, recorded pipeline evidence.

Only the dataclasses in this module reach output. Source models, exception text
and caller-supplied strings must never become report fields.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Literal, TypeVar

InputState = Literal['not_supplied', 'available', 'unreadable', 'invalid', 'inconsistent']


@dataclass(frozen=True)
class Inputs:
    extraction: InputState = 'not_supplied'
    dispositions: InputState = 'not_supplied'
    labeled_set: InputState = 'not_supplied'


@dataclass(frozen=True)
class RecordedFraction:
    numerator: int | None = None
    denominator: int | None = None
    negative_units: int | None = None
    unknown_units: int | None = None
    fraction: float | None = None

    @classmethod
    def from_flags(cls, flags: list[bool | None]) -> RecordedFraction:
        positive = sum(flag is True for flag in flags)
        negative = sum(flag is False for flag in flags)
        unknown = sum(flag is None for flag in flags)
        total = len(flags)
        return cls(positive, total, negative, unknown,
                   positive / total if total and not unknown else None)


@dataclass(frozen=True)
class Coverage:
    status: Literal['unavailable', 'empty', 'incomplete', 'available'] = 'unavailable'
    denominator_basis: Literal['emitted_units'] = 'emitted_units'
    emitted_units: int | None = None
    recorded_documents_processed: int | None = None
    distinct_source_files: int | None = None
    source_reference_unknown_units: int | None = None
    recorded_iri_tagging: RecordedFraction = field(default_factory=RecordedFraction)
    recorded_anchor_flags: RecordedFraction = field(default_factory=RecordedFraction)
    full_source_coverage: None = None
    full_source_coverage_reason: Literal['source_coverage_not_recorded'] = 'source_coverage_not_recorded'


@dataclass(frozen=True)
class ReadinessReport:
    inputs: Inputs = field(default_factory=Inputs)
    coverage: Coverage = field(default_factory=Coverage)
    diagnostics: tuple[str, ...] = ()
    schema_version: Literal['folio-insights/readiness/v1'] = 'folio-insights/readiness/v1'

    @property
    def exit_code(self) -> int:
        return int(any(state not in ('not_supplied', 'available')
                       for state in asdict(self.inputs).values()))

    def as_dict(self) -> dict:
        data = asdict(self)
        data['diagnostics'] = list(self.diagnostics)
        return data


class _InconsistentEvidence(ValueError):
    pass


T = TypeVar('T')


def _read_selected(path: Path | None, reader: Callable[[Path], T]) -> tuple[InputState, T | None]:
    if path is None:
        return 'not_supplied', None
    try:
        return 'available', reader(path)
    except _InconsistentEvidence:
        return 'inconsistent', None
    except OSError:
        return 'unreadable', None
    except (ValueError, RecursionError):
        # Includes JSON, Unicode and Pydantic failures; never expose their text.
        return 'invalid', None


def _count(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError
    return value


def _tagged(unit: dict) -> bool | None:
    if 'folio_tags' not in unit:
        return None
    tags = unit['folio_tags']
    if not isinstance(tags, list):
        raise ValueError
    positive, unknown = False, False
    for tag in tags:
        if not isinstance(tag, dict):
            raise ValueError
        if 'iri' not in tag:
            unknown = True
        elif not isinstance(tag['iri'], str):
            raise ValueError
        elif tag['iri']:
            positive = True
    return True if positive else None if unknown else False


def _read_extraction(path: Path) -> Coverage:
    doc = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(doc, dict) or not isinstance(doc.get('units'), list):
        raise ValueError
    units = doc['units']
    if 'total_units' in doc and _count(doc['total_units']) != len(units):
        raise _InconsistentEvidence
    documents = None
    if 'summary' in doc:
        if not isinstance(doc['summary'], dict):
            raise ValueError
        if 'documents_processed' in doc['summary']:
            documents = _count(doc['summary']['documents_processed'])
    tags, anchors, sources = [], [], set()
    unknown_sources = 0
    for unit in units:
        if not isinstance(unit, dict):
            raise ValueError
        tags.append(_tagged(unit))
        if 'anchor_verified' in unit and type(unit['anchor_verified']) is not bool:
            raise ValueError
        anchors.append(unit.get('anchor_verified'))
        if 'source_file' in unit and not isinstance(unit['source_file'], str):
            raise ValueError
        if unit.get('source_file'):
            sources.add(unit['source_file'])
        else:
            unknown_sources += 1
    tagging = RecordedFraction.from_flags(tags)
    anchoring = RecordedFraction.from_flags(anchors)
    incomplete = unknown_sources or tagging.unknown_units or anchoring.unknown_units or documents is None
    return Coverage(
        status='empty' if not units else 'incomplete' if incomplete else 'available',
        emitted_units=len(units), recorded_documents_processed=documents,
        distinct_source_files=None if unknown_sources else len(sources),
        source_reference_unknown_units=unknown_sources,
        recorded_iri_tagging=tagging, recorded_anchor_flags=anchoring,
    )


def build_readiness_report(*, extraction: Path | None = None) -> ReadinessReport:
    """Read selected evidence without opening any referenced source or state store."""
    state, coverage = _read_selected(extraction, _read_extraction)
    diagnostics = () if state in ('available', 'not_supplied') else (f'extraction_{state}',)
    return ReadinessReport(inputs=Inputs(extraction=state), coverage=coverage or Coverage(),
                           diagnostics=diagnostics)
