"""folio-insights CI pipeline (Dagger Python SDK driver).

Plan 00-05 renamed this package from ``dagger/`` to ``ci/`` because a local
``dagger/`` directory at the repo root would shadow the installed
``dagger-io`` SDK package (site-packages) — Python's default import order
puts cwd on sys.path[0], so ``import dagger`` inside ``dagger/build.py``
would resolve to our own package, not the SDK. ``ci/`` keeps the intent
(CI pipeline code) without the collision.

Entry points:
  - ``python -m ci.build`` — build web+worker, lint, test, publish, record digests
  - ``python -m ci.railway`` — deploy pushed images to Railway (invoked by
    ``ci/build.py`` after publish on main branch)
"""
