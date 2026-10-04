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

Scope: every string leaf of the record is scanned, and so is every integer
leaf (as its decimal text; booleans are not integers here, and an integer too
large to render is refused as ``unscannable_integer``). That includes IRIs,
mapping keys, raw input that a migration would drop, and every field of signature
objects (``did``, ``signing_key_id``, ``action``, cosigners...). Only two
machine-generated values are exempt, and only when they have the exact shape
of what they claim to be: a ``signature`` value that is an Ed25519 signature
in unpadded base64url (86 characters of ``[A-Za-z0-9_-]``), and a ``*_hash``
value that is a 64-char lowercase hex digest. Anything else under those keys
is scanned like any other text.
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
    # The pattern can only match text containing a run of at least this many
    # consecutive digits (``\d``, Unicode-aware like the patterns). 0, the
    # default for configured patterns, means "no such guarantee" and disables
    # the gate's digit-run prefilter.
    min_digit_run: int = 0

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
    min_digit_run=3,
)
ABA_ROUTING_PATTERN = PiiPattern(
    "aba_routing",
    re.compile(r"(?<![\w.-])\d{9}(?![\w-]|\.\d)"),
    _aba_checksum_ok,
    min_digit_run=9,
)
US_PHONE_PATTERN = PiiPattern(
    "us_phone",
    re.compile(
        r"(?<![\w-])(?:\+?1[-.\s]?)?(?:\([2-9]\d{2}\)\s?|[2-9]\d{2}[-.\s])"
        r"[2-9]\d{2}[-.\s]\d{4}(?![\w-])"
    ),
    min_digit_run=3,
)

DEFAULT_PII_PATTERNS: tuple[PiiPattern, ...] = (
    SSN_PATTERN,
    ABA_ROUTING_PATTERN,
    US_PHONE_PATTERN,
)

# Keys whose values are machine-generated cryptographic material.
_HEX_DIGEST = re.compile(r"[0-9a-f]{64}")
_ED25519_B64URL = re.compile(r"[A-Za-z0-9_-]{86}")


def _is_skipped(key: str, value: Any) -> bool:
    """Exempt only exactly-shaped cryptographic values (see module docstring)."""
    if not isinstance(value, str):
        return False
    if key == "signature":
        return value == "" or _ED25519_B64URL.fullmatch(value) is not None
    return key.endswith("_hash") and _HEX_DIGEST.fullmatch(value) is not None


def _path(parts: tuple[str | int, ...]) -> str:
    out = ""
    for part in parts:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out = f"{out}.{part}" if out else part
    return out


# Integers are scanned as their decimal text (a 9-digit integer can be an ABA
# routing number). Python refuses int -> str above ~4300 digits; an integer
# beyond this bound is refused rather than skipped (fail closed).
MAX_SCANNED_INT_BITS = 14_000
UNSCANNABLE_INTEGER = "unscannable_integer"


def _is_scanned_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _string_leaves(value: Any, path: str) -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif _is_scanned_int(value) and value.bit_length() <= MAX_SCANNED_INT_BITS:
        yield path, str(value)
    elif isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(key, str):
                # The key itself is input text (never echoed: the path below
                # names the parent, not the key).
                yield (f"{path}.<key>" if path else "<key>"), key
                if _is_skipped(key, item):
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
        """Raise ``PiiRejected`` for the first matching field; return otherwise.

        Same leaves, same order and same field paths as ``_string_leaves``;
        the path string is built only for a match. When every pattern
        declares a minimum digit run, text without such a run is skipped
        with one regex search instead of one per pattern.
        """
        if not self.patterns:
            return
        run = min(p.min_digit_run for p in self.patterns)
        prefilter = re.compile(rf"\d{{{run}}}").search if run > 0 else None
        patterns = self.patterns

        def scan(text: str, parts: tuple[str | int, ...]) -> None:
            if prefilter is not None and prefilter(text) is None:
                return
            for pattern in patterns:
                if pattern.matches(text):
                    raise PiiRejected(_path(parts) or "<root>", pattern.name)

        def walk(value: Any, parts: tuple[str | int, ...]) -> None:
            if isinstance(value, str):
                scan(value, parts)
            elif _is_scanned_int(value):
                if value.bit_length() > MAX_SCANNED_INT_BITS:
                    raise PiiRejected(_path(parts) or "<root>", UNSCANNABLE_INTEGER)
                scan(str(value), parts)
            elif isinstance(value, Mapping):
                for key, item in value.items():
                    if isinstance(key, str):
                        scan(key, (*parts, "<key>"))
                        if _is_skipped(key, item):
                            continue
                    walk(item, (*parts, key if isinstance(key, str) else str(key)))
            elif isinstance(value, (list, tuple)):
                for index, item in enumerate(value):
                    walk(item, (*parts, index))

        walk(record, ())


__all__ = [
    "ABA_ROUTING_PATTERN",
    "DEFAULT_PII_PATTERNS",
    "PiiGate",
    "PiiPattern",
    "SSN_PATTERN",
    "US_PHONE_PATTERN",
]
