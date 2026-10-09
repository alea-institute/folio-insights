"""Server-assigned time for governance (R17 / KTD12).

A governance event carries ``signature.signed_at``, the time its signer
*claims* to have signed. That value is inside the signed payload, so it cannot
be moved after signing, but the signer chooses it before signing. Windowing
roles by it would let a signer pick when they held a role: a revoked admin
could backdate an assertion to before the revocation, and a grant could be
backdated to authorize actions that were committed before it existed.

The persistent journal therefore decides time. Every governance row records
the server's ``committed_at``; role windows, the signer-must-be-admin and
last-admin checks and the central ``authorize()`` decision are all evaluated
at that server time, and history replay uses each stored row's
``committed_at``. ``signed_at`` stays in the signed payload (the signature
format is unchanged) and must sit within ``SIGNING_SKEW`` of the server time
at append, or the append is refused with ``GovernanceClockSkew``.

This follows the precedent of the framework registry
(``frameworks/registry.py``), which re-exports ``SIGNING_SKEW`` from here.

D-04 boundary: stdlib only.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from folio_insights.governance.events import GovernanceEvent

# How far a signer's claimed signing time may sit from the server time at
# which the write is committed (governance events) or authorized / committed
# (framework registrations).
SIGNING_SKEW = timedelta(minutes=5)

#: Maps a governance event to the time it took effect, or ``None`` when it
#: has no usable time (and so never windows into a role query).
EventTime = Callable[["GovernanceEvent"], "datetime | None"]


class GovernanceClockSkew(ValueError):
    """Raised when a governance event's ``signed_at`` is missing, or is more
    than ``SIGNING_SKEW`` away from the server time at which it would be
    committed. Nothing is appended."""


def signed_at_time(event: GovernanceEvent) -> datetime | None:
    """The signer-claimed time of ``event``.

    Only meaningful where no server clock exists: the in-memory log, an
    offline/test structure. Persistent storage never windows by it.
    """
    return event.signature.signed_at


def as_utc(value: datetime) -> datetime:
    """``value`` as an aware UTC datetime (a naive value is taken as UTC)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def parse_committed_at(value: str) -> datetime:
    """Parse a journal ``committed_at`` column (ISO 8601) as aware UTC."""
    return as_utc(datetime.fromisoformat(value))


def check_signing_skew(event: GovernanceEvent, server_time: datetime) -> None:
    """Refuse ``event`` unless its ``signed_at`` is within ``SIGNING_SKEW`` of
    ``server_time``.

    Raises:
        GovernanceClockSkew: ``signed_at`` is ``None`` or outside the skew.
    """
    signed_at = event.signature.signed_at
    if signed_at is None:
        raise GovernanceClockSkew(
            f"governance {event.action} event signed by {event.signature.did!r} "
            "has no signed_at; the server cannot check it against its commit "
            "time, so nothing was appended"
        )
    drift = as_utc(signed_at) - as_utc(server_time)
    if abs(drift) > SIGNING_SKEW:
        raise GovernanceClockSkew(
            f"governance {event.action} event signed by {event.signature.did!r} "
            f"claims signed_at {as_utc(signed_at).isoformat()}, which is "
            f"{abs(drift)} {'before' if drift < timedelta(0) else 'after'} the "
            f"server commit time {as_utc(server_time).isoformat()}; it must be "
            f"within {SIGNING_SKEW}. Re-sign with the current time; nothing was "
            "appended"
        )


__all__ = [
    "EventTime",
    "GovernanceClockSkew",
    "SIGNING_SKEW",
    "as_utc",
    "check_signing_skew",
    "parse_committed_at",
    "signed_at_time",
]
