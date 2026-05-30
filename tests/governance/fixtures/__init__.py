"""Shared fixture helpers for governance tests (07-05b cascade preview + onward).

This package marker exposes nothing by itself; the per-helper modules
(e.g. ``cascade_corpora.py``) re-export their factories from their own
namespaces so test files import them by path:

    from tests.governance.fixtures.cascade_corpora import seed_cascade_corpus

Mirrors the polysemy fixtures convention (``tests/polysemy/`` keeps fixture
data inline; the governance suite needed an importable factory module
because the cascade-preview tests + the interactive-flow checkpoint share
the SAME seed shape).
"""
