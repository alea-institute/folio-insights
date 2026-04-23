"""Gate 0 prerequisite: bench generator determinism (D-15, D-14).

These tests enforce Pitfall 7 discipline: --seed 42 MUST produce
bit-identical output across runs; --seed 42 vs --seed 43 MUST differ.
They also enforce Pitfall 1 (no `<<` subject-position triple terms).
"""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

SMOKE_TARGET = 10_000  # 10k — fast test iteration (~5s); D-15 logic is scale-invariant


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _run_gen(
    tmp_path: Path,
    seed: int,
    out_name: str,
    profile: str = "phase-0-gate",
    target: int = SMOKE_TARGET,
) -> Path:
    out_path = tmp_path / out_name
    result = subprocess.run(
        [
            "uv", "run", "folio-insights", "bench", "gen",
            "--seed", str(seed),
            "--target", str(target),
            "--profile", profile,
            "--out", str(out_path),
        ],
        capture_output=True, text=True, check=True,
    )
    assert out_path.exists(), (
        f"gen didn't produce output\nstderr: {result.stderr}\nstdout: {result.stdout}"
    )
    return out_path


def test_same_seed_produces_bit_identical_output(tmp_path: Path) -> None:
    """D-15: --seed 42 twice => byte-identical files."""
    a = _run_gen(tmp_path, seed=42, out_name="a.nq")
    b = _run_gen(tmp_path, seed=42, out_name="b.nq")
    assert _sha256(a) == _sha256(b), (
        "Pitfall 7 violation: seeded output is not deterministic\n"
        f"  a={_sha256(a)}\n  b={_sha256(b)}"
    )


def test_different_seed_produces_different_output(tmp_path: Path) -> None:
    """Seed actually matters (not just structural determinism)."""
    a = _run_gen(tmp_path, seed=42, out_name="a.nq")
    c = _run_gen(tmp_path, seed=43, out_name="c.nq")
    assert _sha256(a) != _sha256(c), "Seed has no effect — RNG probably not threaded"


def test_output_contains_no_sparql_star_subject_terms(tmp_path: Path) -> None:
    """Pitfall 1 BLOCKING: banned `<<?s ?p ?o>>` subject-position terms.

    Any literal occurrence of `<<` in N-Quads output is a bug — RDF-12
    annotations must use object-position or reification only.
    """
    a = _run_gen(tmp_path, seed=42, out_name="a.nq")
    raw = a.read_bytes()
    assert b"<<" not in raw, "Generator emitted banned `<<...>>` subject-position triple term"


def test_output_roundtrips_through_pyoxigraph_bulk_load(tmp_path: Path) -> None:
    """Generator output must be parseable by pyoxigraph.Store.bulk_load."""
    from pyoxigraph import RdfFormat, Store

    a = _run_gen(tmp_path, seed=42, out_name="a.nq")
    store = Store(path=None)
    with open(a, "rb") as f:
        store.bulk_load(f, format=RdfFormat.N_QUADS)
    store.optimize()
    # Sanity: at least SMOKE_TARGET-100 quads landed (we requested SMOKE_TARGET;
    # share-rounding may drop a handful).
    count = sum(1 for _ in store)
    assert count >= SMOKE_TARGET - 100, f"expected ~{SMOKE_TARGET}, got {count}"


def test_profile_flag_routes_to_different_output(tmp_path: Path) -> None:
    """D-16: --profile changes output (different ratios → different SHA)."""
    gate = _run_gen(tmp_path, seed=42, out_name="gate.nq", profile="phase-0-gate")
    adv = _run_gen(
        tmp_path, seed=42, out_name="adv.nq", profile="phase-16-sparql-adversarial"
    )
    assert _sha256(gate) != _sha256(adv), "--profile did not change output"
