"""Axiom kernel: packaged regulae iuris, seeding and kernel derivation (drain U3).

* ``catalog`` — the verified Liber Sextus (VI 5.12) and Digest 50.17 maxims,
  their canonical citation URIs, minted shard IRIs and the kernel manifest.
* ``seed`` — write the kernel into a corpus as ``SimpleAssertionShard``s.
* ``traversal`` — ``derived_from_kernel``: kernel shards a shard derives from.
* ``export`` — a derivation chain as JSON or Turtle.
* ``cli`` — ``folio-insights kernel list|seed|chain``.

Submodules import lazily; this package root pulls in nothing heavy.
"""
from __future__ import annotations

from folio_insights.kernel.catalog import (
    KernelCatalog,
    KernelMaxim,
    is_kernel_iri,
    kernel_manifest,
    load_catalog,
)

__all__ = [
    "KernelCatalog",
    "KernelMaxim",
    "is_kernel_iri",
    "kernel_manifest",
    "load_catalog",
]
