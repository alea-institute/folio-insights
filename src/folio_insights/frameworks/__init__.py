"""Framework records (Phase 9 U2, PRD §8 P2 — PRINCIPLE-02).

* ``registry`` — per-corpus registry (starter set + signed admin
  registrations in the corpus ledger) and the write-time ``FrameworkGuard``.
* ``detector`` — metadata -> corpus default -> citations -> LLM (registered
  IDs only), with evidence and the confidence gate's input.
* ``valid_time`` — windows from supplied metadata, with evidence.
* ``query`` — temporal "framework X at T" over the projection.
* ``default_frameworks.json`` — the starter set (one data file; provisional).

The model and the pure v1 migration live in ``folio_insights.models.framework``.
Submodules are imported directly (no eager imports here, so the pure modules
never pull in storage).
"""
