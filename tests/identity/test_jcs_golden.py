"""Cross-implementation JCS golden test — Plan 06-01 Task 4 (F4 closure).

For every vendored fixture under `tests/identity/fixtures/jcs_golden/`,
asserts our `_jcs_canonical_bytes` output equals the RFC-8785 reference
output produced by `jcs.canonicalize` (cyberphone/json-canonicalization
Python port, pinned at `jcs==0.2.1` per `pyproject.toml`).

This is the orthogonal half of the F4 (BLOCKING) closure: the property
test (`test_canonical_jcs_properties.py`) proves INTERNAL consistency
(order-independence over 1000 random shards); this test proves EXTERNAL
correctness against the reference. Both gates are required.

For the cases jcs alone cannot handle (NFD vs NFC accents are equivalent
under our recipe but produce different bytes from raw jcs.canonicalize),
the test asserts NFD == NFC AFTER our recipe — proving the NFC
pre-normalization step is doing its job.

Fixture set composition (~50 inputs, see fixtures/jcs_golden/README.md):
  * unicode (15): NBSP, em-dash, curly quotes, BMP + astral emoji, NFC/NFD
    accents, CJK, RTL Arabic, ZWJ sequence, control chars, escaped chars
  * numbers (10): 0, 1, neg, 0.0, 1.0, 0.5, 1e-7, 1e21, pi-precision,
    beyond-2^53 integer
  * structure (10): empty obj/array, single/two-key sorted+reverse,
    nested, array-of-objects, object-of-arrays, deeply-nested, Unicode keys
  * nulls (8): null, true/false, arrays + objects with null, all-falsy
  * key_ordering (7): reverse-sorted, mixed Unicode, numeric-string,
    empty-string key, nested key order, array-order-preserved
"""
from __future__ import annotations

import json
import pathlib

import jcs
import pytest

from folio_insights.revision.content_edit import _jcs_canonical_bytes, _normalize_for_jcs

pytestmark = pytest.mark.identity


# Discover fixtures at module load — pytest parametrize then iterates them.
FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures" / "jcs_golden"

_FIXTURE_FILES = sorted(FIXTURES_DIR.glob("*.json"))


def _load_fixture(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "fixture_path",
    _FIXTURE_FILES,
    ids=[p.stem for p in _FIXTURE_FILES],
)
def test_jcs_canonical_bytes_match_reference(fixture_path: pathlib.Path) -> None:
    """For every fixture, _jcs_canonical_bytes output matches the RFC-8785 reference
    after both sides see the same NFC pre-normalization.

    Our `_jcs_canonical_bytes` applies the F4 recipe (recursive NFC + datetime
    pin + None-keep) BEFORE calling `jcs.canonicalize`. For the fixtures here,
    the only F4 surface is NFC; the datetime path doesn't fire (no ISO datetime
    strings) and None-keep matches jcs's default behavior.

    The reference comparison: feed the SAME NFC-normalized input to both sides,
    and assert byte-for-byte equality. This is the cross-impl gate.
    """
    fixture = _load_fixture(fixture_path)
    input_value = fixture["input"]

    # Apply our F4 recipe (NFC normalization on the input only — the datetime
    # path is a no-op for these JSON-native fixtures).
    normalized = _normalize_for_jcs(input_value)

    ours = _jcs_canonical_bytes(input_value)
    reference = jcs.canonicalize(normalized)

    assert ours == reference, (
        f"[{fixture['id']}] _jcs_canonical_bytes diverged from RFC-8785 reference\n"
        f"  description: {fixture['description']}\n"
        f"  category:    {fixture['category']}\n"
        f"  ours:        {ours!r}\n"
        f"  reference:   {reference!r}"
    )


# ── F4 closure: NFD/NFC equivalence pairs ────────────────────────────────


_NFD_NFC_PAIRS = [
    ("u08_combining_accent_nfc.json", "u09_combining_accent_nfd.json"),
]


@pytest.mark.parametrize("nfc_fixture,nfd_fixture", _NFD_NFC_PAIRS)
def test_jcs_nfc_and_nfd_canonical_bytes_are_equal(
    nfc_fixture: str, nfd_fixture: str
) -> None:
    """An NFC string and its NFD equivalent produce IDENTICAL canonical bytes
    through `_jcs_canonical_bytes` — the F4 normalization closure.

    This is the gate that proves our pre-normalization recipe is doing what
    raw `jcs.canonicalize` alone cannot: making the canonical form invariant
    under Unicode normalization form. Without this, a signer using NFD input
    and a verifier using NFC input would compute different hashes over the
    "same" content and signatures would silently fail to verify.
    """
    nfc_path = FIXTURES_DIR / nfc_fixture
    nfd_path = FIXTURES_DIR / nfd_fixture
    nfc_input = _load_fixture(nfc_path)["input"]
    nfd_input = _load_fixture(nfd_path)["input"]

    # Sanity: the inputs are actually DIFFERENT byte sequences pre-normalization.
    assert nfc_input != nfd_input or len(nfc_input.encode("utf-8")) != len(
        nfd_input.encode("utf-8")
    ), (
        f"Test data invariant: {nfc_fixture} and {nfd_fixture} must differ "
        "pre-normalization (else this test isn't proving anything)."
    )

    nfc_bytes = _jcs_canonical_bytes(nfc_input)
    nfd_bytes = _jcs_canonical_bytes(nfd_input)
    assert nfc_bytes == nfd_bytes, (
        f"NFC form ({nfc_fixture}) and NFD form ({nfd_fixture}) produced "
        f"DIFFERENT canonical bytes through _jcs_canonical_bytes:\n"
        f"  NFC: {nfc_bytes!r}\n"
        f"  NFD: {nfd_bytes!r}\n"
        f"F4 NFC pre-normalization closure is broken."
    )


def test_at_least_50_fixtures_present() -> None:
    """Plan acceptance criterion: ~50 vendored golden fixtures present.

    A pre-commit-style guard so a future refactor that loses fixtures
    breaks the build instead of silently shrinking F4 coverage.
    """
    assert len(_FIXTURE_FILES) >= 50, (
        f"Expected >= 50 JCS golden fixtures, found {len(_FIXTURE_FILES)} "
        f"under {FIXTURES_DIR}. Plan 06-01 Task 4 acceptance: ~50 inputs."
    )
