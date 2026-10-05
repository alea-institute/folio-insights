"""The ``Reasoner`` seam and TBox profiles (Phase 9 U4, KTD5).

The shared TBox is kept inside OWL 2 EL by a syntactic check
(``reason.el_profile``); reasoning itself runs HermiT for both profiles, behind
this protocol, so an EL reasoner (ELK) can be added later without changing any
caller. The HermiT adapter imports owlready2 only when it reasons, so this
module is safe to import in the JVM-free web tier.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

TBoxProfile = Literal["EL", "DL"]
TBOX_PROFILES: tuple[TBoxProfile, ...] = ("EL", "DL")


@dataclass(frozen=True)
class ReasonerResult:
    """A reasoner's verdict on one ontology file."""

    reasoner: str
    profile: TBoxProfile
    consistent: bool
    unsatisfiable: tuple[str, ...] = field(default_factory=tuple)
    elapsed_s: float = 0.0


@runtime_checkable
class Reasoner(Protocol):
    """Consistency and satisfiability over an ontology file."""

    @property
    def name(self) -> str: ...

    @property
    def profiles(self) -> frozenset[TBoxProfile]: ...

    def check(self, ontology_path: Path, *, profile: TBoxProfile) -> ReasonerResult: ...


class HermitReasoner:
    """HermiT (via ``reason.HermitHarness``) for both EL and DL TBoxes."""

    name = "hermit"
    profiles: frozenset[TBoxProfile] = frozenset(TBOX_PROFILES)

    def __init__(self, xmx_mb: int = 4096) -> None:
        self.xmx_mb = xmx_mb

    def check(self, ontology_path: Path, *, profile: TBoxProfile) -> ReasonerResult:
        if profile not in self.profiles:
            raise ValueError(f"unknown TBox profile {profile!r}")
        from folio_insights.reason.hermit_harness import HermitHarness  # worker tier only

        result = HermitHarness(xmx_mb=self.xmx_mb).reason(ontology_path)
        return ReasonerResult(
            reasoner=self.name,
            profile=profile,
            consistent=result.consistent,
            unsatisfiable=tuple(result.inconsistent_classes),
            elapsed_s=result.elapsed_s,
        )


def reasoner_for_profile(profile: TBoxProfile) -> Reasoner:
    """The reasoner for a TBox profile: HermiT for both today (KTD5, no ELK)."""
    if profile not in TBOX_PROFILES:
        raise ValueError(f"unknown TBox profile {profile!r}; expected one of {TBOX_PROFILES}")
    return HermitReasoner()


__all__ = [
    "HermitReasoner",
    "Reasoner",
    "ReasonerResult",
    "TBOX_PROFILES",
    "TBoxProfile",
    "reasoner_for_profile",
]
