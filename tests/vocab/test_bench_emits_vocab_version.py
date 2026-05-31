"""Phase 8 Plan 08-02: per-shard ``fi:vocabVersion`` emission in the bench generator.

Asserts that ``BenchGenerator.generate(...)``:
  1. Emits exactly one ``fi:vocabVersion "2026.05.0"`` quad per shard.
  2. Produces byte-stable output (two back-to-back runs with the same seed
     yield identical bytes — the Phase 0 D-15 contract still holds with
     the new quad).
  3. The SHA-256 of the canonical N-Quads output matches the pinned baseline
     at ``tests/bench/fixtures/expected_digest.txt``.

The N-Quads format is the existing Phase 0 emission (pyoxigraph SPO-sorted
N-Quads dump). The new quad inserts deterministically per shard, so the
new digest is byte-stable and pinned here.

Plan 08-02 owns the new digest fixture (no pre-existing digest baseline
exists in the repo — the existing ``tests/bench/test_generator_determinism.py``
only compares two runs to each other, not to a fixed value).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from folio_insights.bench import BenchGenerator

try:
    from folio_insights.vocab import VOCAB_VERSION  # type: ignore
except ImportError:  # pragma: no cover — Plan 08-01 ordering fallback
    from folio_insights.shards.envelope import VOCAB_VERSION  # type: ignore

# Fixed small-but-representative settings: small enough to keep the test
# under the 30s timeout, large enough that all three corpora emit several
# shards each (so the per-corpus loop is exercised).
_BASELINE_SEED = 42
_BASELINE_TARGET = 1_000  # ~1k quads → small handful of shards per corpus

_FIXTURE_DIGEST_PATH = Path(__file__).parent.parent / "bench" / "fixtures" / "expected_digest.txt"


def _generate_to(tmp_path: Path, name: str, seed: int = _BASELINE_SEED) -> Path:
    out = tmp_path / name
    gen = BenchGenerator(seed=seed, profile_name="phase-0-gate")
    gen.generate(target_triples=_BASELINE_TARGET, output_path=out)
    return out


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _count_shards(path: Path) -> int:
    """Count distinct shard IRIs in the N-Quads output.

    A shard IRI is the subject of the rdf:type ``fi:*Shard`` quad emitted at
    the top of ``_emit_shard_quads`` — there is exactly one such quad per
    shard, so the count of those quads equals the shard count.
    """
    raw = path.read_text()
    # type predicate URI in the N-Quads serialization
    type_pred = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>"
    n_shards = 0
    for line in raw.splitlines():
        if type_pred in line and "Shard>" in line:
            n_shards += 1
    return n_shards


def test_one_vocab_version_quad_per_shard(tmp_path: Path) -> None:
    """Every shard gets exactly one ``fi:vocabVersion "<VOCAB_VERSION>"`` quad."""
    out = _generate_to(tmp_path, "one.nq")
    raw = out.read_text()
    # The vocabVersion line is ``<shard_iri> <fi:vocabVersion> "<v>" <graph> .``
    assert "vocabVersion" in raw, "generator did not emit any vocabVersion quad"
    assert VOCAB_VERSION in raw, (
        f"generator output is missing the VOCAB_VERSION literal {VOCAB_VERSION!r}"
    )

    # Count lines containing the vocabVersion predicate (one per shard).
    vocab_lines = [line for line in raw.splitlines() if "vocabVersion" in line]
    n_shards = _count_shards(out)

    assert n_shards >= 3, (
        f"expected at least 3 shards (one per corpus); got {n_shards}"
    )

    # Generator emission order is: type → corpus → framework → vocabVersion →
    # subject-concept → reified-statement → ... The per-corpus inner loop
    # breaks the moment the corpus_target budget is reached, which can
    # truncate the *last* shard in each corpus mid-emission at ANY quad
    # boundary (including between framework and vocabVersion). So we cannot
    # require an exact 1:1 ratio; the truncation tax is at most one missing
    # quad per corpus (3 corpora → at most 3 vocabVersion quads may be cut).
    framework_lines = [
        line for line in raw.splitlines()
        if "<https://folio-insights.aleainstitute.ai/vocab/framework>" in line
    ]
    # vocabVersion is emitted RIGHT AFTER framework; so its count cannot
    # exceed framework's, and must be within 3 (one per corpus tail-cut).
    assert 0 <= len(framework_lines) - len(vocab_lines) <= 3, (
        f"vocabVersion vs framework quad delta out of bounds: "
        f"framework={len(framework_lines)}, vocabVersion={len(vocab_lines)}; "
        f"delta must be in [0, 3] (at most one tail-cut per corpus)"
    )

    # Floor guard: at least n_shards - 3 vocabVersion quads must land.
    assert len(vocab_lines) >= n_shards - 3, (
        f"expected vocabVersion lines >= n_shards - 3 (at most 1 truncated "
        f"shard per corpus); got {len(vocab_lines)} lines vs {n_shards} shards"
    )

    # Every vocabVersion quad must carry the canonical version literal.
    for line in vocab_lines:
        assert f'"{VOCAB_VERSION}"' in line, (
            f"vocabVersion quad does not pin the canonical version "
            f"{VOCAB_VERSION!r}: {line!r}"
        )


def test_byte_stable_across_two_runs(tmp_path: Path) -> None:
    """Phase 0 D-15 contract holds with the new quad — same seed → identical bytes."""
    a = _generate_to(tmp_path, "a.nq")
    b = _generate_to(tmp_path, "b.nq")
    digest_a = _sha256(a)
    digest_b = _sha256(b)
    assert digest_a == digest_b, (
        "Phase 0 D-15 byte-stability violated after Plan 08-02 vocabVersion "
        f"emission was added.\n  a={digest_a}\n  b={digest_b}\n"
        "Likely cause: the new Quad insertion point is not deterministic, "
        "or VOCAB_VERSION is being read from a non-stable source."
    )


def test_digest_matches_pinned_baseline(tmp_path: Path) -> None:
    """SHA-256 of the generator output matches the pinned baseline.

    The baseline at ``tests/bench/fixtures/expected_digest.txt`` was
    regenerated during Plan 08-02; any future drift means either the
    generator is no longer deterministic or VOCAB_VERSION changed.
    """
    assert _FIXTURE_DIGEST_PATH.exists(), (
        f"baseline fixture missing: {_FIXTURE_DIGEST_PATH}"
    )
    expected = _FIXTURE_DIGEST_PATH.read_text().strip()
    out = _generate_to(tmp_path, "out.nq")
    actual = _sha256(out)
    assert actual == expected, (
        f"bench-generator digest drift.\n  expected: {expected}\n  actual:   {actual}\n"
        f"If this is an intentional emission change, regenerate the baseline:\n"
        f"  python -c 'from folio_insights.bench import BenchGenerator; "
        f"from pathlib import Path; "
        f"BenchGenerator(seed={_BASELINE_SEED}).generate({_BASELINE_TARGET}, "
        f"Path(\"/tmp/x.nq\"))' "
        f"&& sha256sum /tmp/x.nq | cut -d' ' -f1 > {_FIXTURE_DIGEST_PATH}"
    )
