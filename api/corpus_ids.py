"""Corpus identifiers on the API: validated once, centrally, before any handler runs.

A corpus name arrives as the ``{corpus_id}`` path segment or the ``?corpus=`` query parameter
and becomes a directory under the output dir (``<output>/<corpus>/review.db``,
``extraction.json``, ``sources/`` ...). An unvalidated name is a path: ``../escaped`` would
create directories and SQLite files anywhere the server user can write (security review,
drain plan fixes A).

:func:`require_valid_corpus_ids` is an **application-level** dependency (``api/main.py``), so
every route of every router, including routes added later, refuses a bad name with 422 before
its handler, its body parsing or its own guards run. Every value of a repeated query parameter
is checked. :func:`check_corpus_id` is the same rule for server helpers that build paths
(defence in depth: they refuse a bad name even if reached without the dependency).

The rule is :data:`api.services.proposals.CORPUS_ID`: 1-128 characters of letters, digits,
``.``, ``_`` or ``-``, starting with a letter or digit. Names the API itself creates
(``slugify`` in ``POST /api/v1/corpora``) always match it.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from api.services.proposals import CORPUS_ID

#: Path and query parameter names that carry a corpus name on this API.
CORPUS_PARAMS = ("corpus_id", "corpus")

_DETAIL = (
    "corpus must be a corpus ID: 1-128 letters, digits, '.', '_' or '-', starting with a "
    "letter or digit"
)


def is_valid_corpus_id(value: object) -> bool:
    """True when *value* is a string matching :data:`CORPUS_ID` exactly."""
    return isinstance(value, str) and CORPUS_ID.fullmatch(value) is not None


def check_corpus_id(value: str) -> str:
    """Return *value* if it is a valid corpus ID, else raise ``HTTPException(422)``.

    The refused value is never echoed: it is attacker-controlled and may hold control bytes.
    """
    if not is_valid_corpus_id(value):
        raise HTTPException(status_code=422, detail=_DETAIL)
    return value


def require_valid_corpus_ids(request: Request) -> None:
    """Application-level dependency: 422 unless every corpus parameter is a corpus ID.

    Checks the ``corpus_id`` / ``corpus`` path parameters of the matched route and every value
    of a ``corpus_id`` / ``corpus`` query parameter, whether or not the route declares it, so
    a name can never slip past as an undeclared parameter a handler later reads.
    """
    for name in CORPUS_PARAMS:
        if name in request.path_params:
            check_corpus_id(request.path_params[name])
        for value in request.query_params.getlist(name):
            check_corpus_id(value)


__all__ = [
    "CORPUS_PARAMS",
    "check_corpus_id",
    "is_valid_corpus_id",
    "require_valid_corpus_ids",
]
