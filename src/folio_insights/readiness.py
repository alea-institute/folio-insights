"""Content-free projections of explicitly selected, recorded pipeline evidence.

Only the dataclasses in this module reach output. Source models, exception text
and caller-supplied strings must never become report fields.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Literal, TypeVar

if TYPE_CHECKING:
    from folio_insights.polysemy.dispositions import DispositionRecord
    from folio_insights.polysemy.labeled_set import LabeledSet

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
class PolysemyR9:
    status: Literal['unavailable', 'fail', 'provisional', 'pass'] = 'unavailable'
    basis: Literal['recorded_log', 'recorded_labeled_set'] | None = None
    current_detector_evaluated: Literal[False] = False
    certification_assurance: Literal['none', 'self_asserted'] = 'none'
    certified: bool | None = None
    n: int | None = None
    false_positives: int | None = None
    fp_rate: float | None = None
    ci_upper: float | None = None
    threshold: float | None = None
    invalid_dispositions: int | None = None
    detector_positives: int | None = None
    false_discovery_rate: float | None = None


@dataclass(frozen=True)
class ReadinessReport:
    inputs: Inputs = field(default_factory=Inputs)
    coverage: Coverage = field(default_factory=Coverage)
    polysemy_r9: PolysemyR9 = field(default_factory=PolysemyR9)
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


def _read_records(path: Path) -> list[DispositionRecord]:
    from folio_insights.polysemy.dispositions import read_dispositions

    records = list(read_dispositions(path))
    for record in records:
        decision = record.detector_verdict.get('decision')
        if not isinstance(decision, str) or decision not in (
            'polysemy', 'homonymy', 'coincidence', 'uncertain',
        ):
            raise ValueError
    return records


def _read_labeled(path: Path) -> LabeledSet:
    from folio_insights.polysemy.labeled_set import load_labeled_set

    return load_labeled_set(path)


def _matches_cases(records: list[DispositionRecord], labeled: LabeledSet) -> bool:
    # The owning gate only checks pairing when certification is present. This
    # adapter must also reject an incomplete *uncertified* saved evaluation.
    by_case = {record.audit_label: record for record in records}
    return (
        len(by_case) == len(records)
        and set(by_case) == {case.id for case in labeled.cases}
        and all(
            (by_case[case.id].term, by_case[case.id].decision, by_case[case.id].rationale)
            == (case.term, case.disposition.decision, case.disposition.rationale)
            for case in labeled.cases
        )
    )


def _recorded_gate(
    records: list[DispositionRecord], labeled: LabeledSet | None,
) -> tuple[PolysemyR9, list[str]]:
    from folio_insights.polysemy.fp_audit import fp_gate

    gate = fp_gate(records, labeled=labeled)
    diagnostics = []
    if not gate.n:
        diagnostics.append('insufficient_evidence')
    if gate.invalid_dispositions:
        diagnostics.append('invalid_dispositions_excluded')
    if gate.certification_problem:
        diagnostics.append('certification_missing' if labeled is None or labeled.certification is None
                           else 'certification_invalid')
    return PolysemyR9(
        status=gate.status, basis='recorded_log' if labeled is None else 'recorded_labeled_set',
        certification_assurance='self_asserted' if gate.certified else 'none',
        certified=gate.certified, n=gate.n, false_positives=gate.false_positives,
        fp_rate=gate.fp_rate if gate.n else None, ci_upper=gate.ci_upper,
        threshold=gate.threshold, invalid_dispositions=gate.invalid_dispositions,
        detector_positives=gate.detector_positives,
        false_discovery_rate=gate.false_discovery_rate if gate.detector_positives else None,
    ), diagnostics


def build_readiness_report(
    *, extraction: Path | None = None, dispositions: Path | None = None,
    labeled_set: Path | None = None,
) -> ReadinessReport:
    """Read selected evidence without opening any referenced source or state store."""
    if labeled_set is not None and dispositions is None:
        raise ValueError('labeled_set_requires_dispositions')
    extraction_state, coverage = _read_selected(extraction, _read_extraction)
    log_state, records = _read_selected(dispositions, _read_records)
    label_state, labeled = _read_selected(labeled_set, _read_labeled)
    gate, diagnostics = PolysemyR9(), []
    if records is not None and (labeled_set is None or labeled is not None):
        if labeled is not None and not _matches_cases(records, labeled):
            log_state = label_state = 'inconsistent'
        else:
            gate, diagnostics = _recorded_gate(records, labeled)
    inputs = Inputs(extraction_state, log_state, label_state)
    diagnostics.extend(f'{role}_{state}' for role, state in asdict(inputs).items()
                       if state not in ('available', 'not_supplied'))
    return ReadinessReport(inputs=inputs, coverage=coverage or Coverage(), polysemy_r9=gate,
                           diagnostics=tuple(sorted(diagnostics)))
