"""`folio-insights bench` Click subgroup (D-14 CLI surface).

Exposes two sibling commands (only `gen` implemented here — Gate-measurement
harnesses land in later plans):

- `folio-insights bench gen` — seeded, phase-profile-aware N-Quads generator.
  `--format owl` additionally converts the N-Quads output to OWL/RDF-XML via
  an rdflib bridge for D-11 HermiT reasoning (Plan 00-07 consumer).
"""
from __future__ import annotations

import logging
from pathlib import Path

import click

logger = logging.getLogger("folio_insights.bench")


@click.group("bench")
def bench() -> None:
    """Phase 0 benchmark harness (1M-triple gen + gate measurement)."""


@bench.command("gen")
@click.option(
    "--target",
    default=1_000_000,
    show_default=True,
    type=int,
    help="Target triple count (D-14).",
)
@click.option(
    "--seed",
    default=42,
    show_default=True,
    type=int,
    help="RNG seed for deterministic output (D-15).",
)
@click.option(
    "--profile",
    default="phase-0-gate",
    show_default=True,
    type=click.Choice(
        [
            "phase-0-gate",
            "phase-13-storage",
            "phase-16-sparql-adversarial",
        ]
    ),
    help="Phase-profile flag (D-16).",
)
@click.option(
    "--out",
    "-o",
    default="fixtures/bench.nq",
    show_default=True,
    type=click.Path(resolve_path=True),
    help="Output path. For --format owl, a .owl sibling is written next to the .nq.",
)
@click.option(
    "--format",
    "fmt",
    default="nq",
    show_default=True,
    type=click.Choice(["nq", "owl"]),
    help=(
        "Output serialization. 'nq' = N-Quads (default, Gate 2). "
        "'owl' = OWL/RDF-XML for D-11 HermiT reasoning (Plan 00-07)."
    ),
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="Enable verbose (DEBUG) logging.",
)
def bench_gen(
    target: int,
    seed: int,
    profile: str,
    out: str,
    fmt: str,
    verbose: bool,
) -> None:
    """Generate a deterministic scaled-real benchmark corpus (D-13..D-16)."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    from folio_insights.bench.generator import BenchGenerator

    gen = BenchGenerator(seed=seed, profile_name=profile)
    nq_path = gen.generate(
        target_triples=target, output_path=Path(out).with_suffix(".nq")
    )

    if fmt == "owl":
        # D-11 prereq: convert N-Quads → OWL/RDF-XML via rdflib for HermiT
        # ingestion. One-way serialize bridge (RESEARCH.md Pitfall 2). Memory
        # cost ~3-5× N-Quads size; caller must budget RAM for --target 1M.
        from rdflib import Dataset

        ds = Dataset()
        ds.parse(source=str(nq_path), format="nquads")
        owl_path = Path(out).with_suffix(".owl")
        # Default graph only — HermiT does not consume named graphs; merge at
        # the boundary by writing a flattened single-graph RDF/XML file.
        flat = ds.default_context
        for ctx in ds.contexts():
            for triple in ctx:
                flat.add(triple)
        flat.serialize(destination=str(owl_path), format="xml")
        click.echo(
            f"Generated {target:,} triples "
            f"(seed={seed}, profile={profile}) -> {owl_path} (OWL, from {nq_path})"
        )
    else:
        click.echo(
            f"Generated {target:,} triples "
            f"(seed={seed}, profile={profile}) -> {nq_path}"
        )
