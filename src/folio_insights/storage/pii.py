"""Configurable PII ingest gate (Phase 13 R6 / KTD6).

Runs on shard creation, revision and bulk ingest BEFORE the journal append, so
a refused record never reaches the immutable journal, the RDF projection, or
any dump derived from them. The refusal names the field path and the pattern,
never the matched text.

Defaults cover three US patterns:

* ``ssn`` — ``AAA-GG-SSSS`` with dash or space separators, excluding the
  never-issued 000/666/9xx areas, 00 groups and 0000 serials.
* ``aba_routing`` — a standalone nine-digit number that passes the ABA
  checksum and starts with a valid Federal Reserve prefix.
* ``us_phone`` — a NANP number written with separators or a parenthesized
  area code (``(212) 555-0142``, ``212-555-0142``, ``+1 212.555.0142``).

Scope: every string leaf of the record is scanned, including IRIs and raw
input that a migration would drop. Machine-generated cryptographic material
(``signatures`` subtrees, ``*_hash`` fields and edit signatures) is skipped.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from folio_insights.storage.errors import PiiRejected


@dataclass(frozen=True)
class PiiPattern:
    """One named pattern, with an optional validator over each regex match."""

    name: str
    regex: re.Pattern[str]
    validator: Callable[[str], bool] | None = None

    def matches(self, text: str) -> bool:
        for match in self.regex.finditer(text):
            if self.validator is None or self.validator(match.group(0)):
                return True
        return False


_ABA_PREFIXES = (
    set(range(0, 13)) | set(range(21, 33)) | set(range(61, 73)) | {80}
)


def _aba_checksum_ok(digits: str) -> bool:
    if len(digits) != 9 or not digits.isdigit():
        return False
    if int(digits[:2]) not in _ABA_PREFIXES:
        return False
    d = [int(c) for c in digits]
    total = 3 * (d[0] + d[3] + d[6]) + 7 * (d[1] + d[4] + d[7]) + (d[2] + d[5] + d[8])
    return total % 10 == 0


SSN_PATTERN = PiiPattern(
    "ssn",
    re.compile(r"(?<![\w-])(?!000|666|9\d\d)\d{3}[- ](?!00)\d{2}[- ](?!0000)\d{4}(?![\w-])"),
)
ABA_ROUTING_PATTERN = PiiPattern(
    "aba_routing",
    re.compile(r"(?<![\w.-])\d{9}(?![\w-]|\.\d)"),
    _aba_checksum_ok,
)
US_PHONE_PATTERN = PiiPattern(
    "us_phone",
    re.compile(
        r"(?<![\w-])(?:\+?1[-.\s]?)?(?:\([2-9]\d{2}\)\s?|[2-9]\d{2}[-.\s])"
        r"[2-9]\d{2}[-.\s]\d{4}(?![\w-])"
    ),
)

DEFAULT_PII_PATTERNS: tuple[PiiPattern, ...] = (
    SSN_PATTERN,
    ABA_ROUTING_PATTERN,
    US_PHONE_PATTERN,
)

# Keys whose values are machine-generated cryptographic material.
_SKIP_KEYS = frozenset({"signatures", "signature", "cosigners"})


def _is_skipped_key(key: str) -> bool:
    return key in _SKIP_KEYS or key.endswith("_hash")


def _string_leaves(value: Any, path: str) -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(key, str) and _is_skipped_key(key):
                continue
            yield from _string_leaves(item, f"{path}.{key}" if path else str(key))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _string_leaves(item, f"{path}[{index}]")


@dataclass(frozen=True)
class PiiGate:
    """Scan a JSON-shaped record and refuse it if any pattern matches.

    An empty ``patterns`` tuple disables the gate (an explicit configuration
    choice, never a silent fallback).
    """

    patterns: tuple[PiiPattern, ...] = field(default=DEFAULT_PII_PATTERNS)

    @classmethod
    def from_mapping(
        cls, patterns: Mapping[str, str], *, include_defaults: bool = True
    ) -> PiiGate:
        """Build a gate from ``{name: regex}`` configuration (plus defaults)."""
        extra = tuple(PiiPattern(name, re.compile(rx)) for name, rx in patterns.items())
        base = DEFAULT_PII_PATTERNS if include_defaults else ()
        return cls(patterns=base + extra)

    def check(self, record: Any) -> None:
        """Raise ``PiiRejected`` for the first matching field; return otherwise."""
        if not self.patterns:
            return
        for path, text in _string_leaves(record, ""):
            for pattern in self.patterns:
                if pattern.matches(text):
                    raise PiiRejected(path or "<root>", pattern.name)


__all__ = [
    "ABA_ROUTING_PATTERN",
    "DEFAULT_PII_PATTERNS",
    "PiiGate",
    "PiiPattern",
    "SSN_PATTERN",
    "US_PHONE_PATTERN",
]
