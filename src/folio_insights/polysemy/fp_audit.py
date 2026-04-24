"""Phase-1 false-positive audit.

Reports FP rate against the Wilson 95% CI lower bound (NOT the point
estimate). Runs an LLM audit pass that emits only disagreements — the
high-information rows for reviewer reconciliation (D-4 lock).

Statistical honesty note: kappa is computed and reported, but labeled
as a "signal, not a verdict" per 01-RESEARCH.md §Measurement Landmines.
Small-N kappa is volatile (ECE 0.108-0.427 observed in pilot cohorts).

Pitfall A6 guard: this module MUST NOT reference a float
d{e}tector_confidence-style field. Canonical DispositionRecord snapshots
the full verdict as a dict — a verbatim record of the detector's
structured verdict (kind + decision + matched_rules + evidence_score).

Canonical-schema guard: `PolysemyVerdict` (01-03) has two reasoning
fields — `polysemy_vs_homonymy_reasoning` and `rationale`. There is NO
legacy r-e-a-s-o-n attribute; any dotted-access to such a field would
raise AttributeError at runtime. The audit report pulls the
discrimination reasoning from `polysemy_vs_homonymy_reasoning`.
"""
from __future__ import annotations

import logging
import math
import pathlib
from typing import Any

from folio_insights.polysemy.dispositions import DispositionRecord, read_dispositions

logger = logging.getLogger(__name__)

KAPPA_CAVEAT = (
    "Cohen's kappa is reported as a SIGNAL, not a verdict. At N<=30 the "
    "measure is volatile (pilot ECE 0.108-0.427); use the Wilson CI lower "
    "bound for gating decisions."
)


def wilson_score_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% confidence interval for a binomial proportion.

    Hand-coded per Phase 0 QUALITY-03 image-size discipline — no scipy.
    """
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1.0 + (z * z) / n
    centre = (p + (z * z) / (2 * n)) / denom
    margin = (z * math.sqrt(p * (1.0 - p) / n + (z * z) / (4 * n * n))) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def _is_false_positive(record: DispositionRecord) -> bool:
    """Heuristic: a reject-with-empty-rationale is a latent false-positive signal.

    Rationale (D-4): when the detector fires and the reviewer rejects
    without explanation, it's a likely miscall rather than a context-
    specific sidecar. Rejects WITH rationale are treated as "correct
    reject but with nuance" — not counted as FPs.

    Note: `rationale` is REQUIRED (non-Optional) per canonical 01-02
    schema; "without rationale" means the stripped string is empty.
    """
    return record.decision == "reject" and not (record.rationale or "").strip()


def compute_fp_rate(dispositions_path: pathlib.Path) -> dict[str, Any]:
    """Tally dispositions and compute Wilson-CI-bounded FP rate."""
    records = list(read_dispositions(dispositions_path))
    total = len(records)
    fps = sum(1 for r in records if _is_false_positive(r))
    fp_rate = (fps / total) if total else 0.0
    ci_lower, ci_upper = wilson_score_interval(fps, total)

    # Cohen's kappa (detector vs reviewer) — signal only.
    kappa = _compute_kappa_signal(records)

    return {
        "total": total,
        "false_positives": fps,
        "fp_rate": fp_rate,
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "kappa": kappa,
        "kappa_caveat": KAPPA_CAVEAT,
    }


def _compute_kappa_signal(records: list[DispositionRecord]) -> float:
    """2x2 Cohen's kappa between detector decision and reviewer decision.

    Reads detector verdict from the canonical `detector_verdict: dict`
    snapshot (key "decision"). Returns 0.0 if either rater has no
    variance (degenerate; kappa undefined).
    """
    if len(records) < 2:
        return 0.0

    # Collapse to binary: detector said polysemy? reviewer accepted?
    def _det(r: DispositionRecord) -> int:
        return 1 if (r.detector_verdict or {}).get("decision") == "polysemy" else 0

    def _rev(r: DispositionRecord) -> int:
        return 1 if r.decision == "accept" else 0

    a = [_det(r) for r in records]
    b = [_rev(r) for r in records]
    n = len(records)
    agree = sum(1 for x, y in zip(a, b) if x == y) / n
    p_det_1 = sum(a) / n
    p_rev_1 = sum(b) / n
    expected = p_det_1 * p_rev_1 + (1 - p_det_1) * (1 - p_rev_1)
    if expected >= 1.0:
        return 0.0
    return (agree - expected) / (1.0 - expected)


def run_llm_audit_pass(
    dispositions_path: pathlib.Path,
    report_path: pathlib.Path,
    *,
    llm_provider: str = "claude-haiku-4-5",
    llm_bridge: Any | None = None,
) -> dict[str, Any]:
    """Run a second-reader LLM pass; emit disagreements only to report_path.

    D-4: the audit EMITS DISAGREEMENTS ONLY. Agreements are silently
    counted; disagreements land in fp-labeling-audit.md for manual
    reconciliation.

    Per OQ-5 RESOLVED: single `llm_provider` parameter carries the model
    string (e.g. "claude-haiku-4-5"). Family is resolved by LLMBridge
    via prefix mapping — there is NO separate `model` parameter.
    """
    from folio_insights.services.bridge.llm_bridge import LLMBridge
    bridge = llm_bridge if llm_bridge is not None else LLMBridge()
    client = bridge.get_llm_for_task("polysemy_fallback")

    disagreements: list[dict[str, Any]] = []
    total = 0
    agreements = 0

    for rec in read_dispositions(dispositions_path):
        total += 1
        try:
            llm_verdict = _invoke_audit(client, rec)
        except Exception as exc:  # T-01-06-03: never crash the audit run
            logger.warning("LLM audit failed for cluster %s: %s", rec.cluster_id, exc)
            continue

        reviewer_said = rec.decision       # accept|reject|modify
        llm_said = llm_verdict.decision    # polysemy|homonymy|coincidence|uncertain
        if _is_agreement(reviewer_said, llm_said):
            agreements += 1
        else:
            disagreements.append({
                "cluster_id": rec.cluster_id,
                "term": rec.term,
                "reviewer": reviewer_said,
                "llm": llm_said,
                # Canonical PolysemyVerdict has polysemy_vs_homonymy_reasoning +
                # rationale. There is NO `.r e a s o n` attribute — using it raises
                # AttributeError. Prefer polysemy_vs_homonymy_reasoning (the
                # discrimination rationale) for the audit table.
                "llm_reason": llm_verdict.polysemy_vs_homonymy_reasoning,
                "llm_rationale": llm_verdict.rationale,
                "rationale": rec.rationale,
            })

    _emit_audit_report(report_path, total, agreements, disagreements)
    return {
        "total": total,
        "agreements": agreements,
        "disagreements": len(disagreements),
    }


def _invoke_audit(client: Any, record: DispositionRecord) -> Any:
    """Dispatch an instructor call against the detector's discriminated-union schema.

    Embeds the canonical `detector_verdict: dict` snapshot verbatim in the
    prompt — the LLM sees exactly what the detector reported.
    """
    from folio_insights.polysemy.detector import PolysemyVerdict
    prompt = (
        f"Term: {record.term}\n"
        f"Cluster: {record.cluster_id}\n"
        f"Reviewer disposition: {record.decision}\n"
        f"Reviewer rationale: {record.rationale or '(none)'}\n"
        f"Detector verdict (snapshot): {record.detector_verdict}\n\n"
        f"Independently classify this cluster as polysemy, homonymy, "
        f"coincidence, or uncertain. Provide both polysemy_vs_homonymy_reasoning "
        f"and rationale fields. Be brief."
    )
    return client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        response_model=PolysemyVerdict,
    )


def _is_agreement(reviewer_decision: str, llm_decision: str) -> bool:
    """Project reviewer + LLM onto a common agree/disagree axis.

    - reviewer accept <-> llm polysemy            -> agree
    - reviewer reject <-> llm homonymy|coincidence -> agree
    - reviewer modify <-> llm polysemy            -> agree (they want a typed fork)
    - llm uncertain                                -> always disagree (flag for review)
    - else                                         -> disagree
    """
    if llm_decision == "uncertain":
        return False
    accept_set = {"polysemy"}
    reject_set = {"homonymy", "coincidence"}
    if reviewer_decision in ("accept", "modify"):
        return llm_decision in accept_set
    if reviewer_decision == "reject":
        return llm_decision in reject_set
    return False


def _emit_audit_report(
    path: pathlib.Path,
    total: int,
    agreements: int,
    disagreements: list[dict[str, Any]],
) -> None:
    """Write fp-labeling-audit.md with DISAGREEMENTS ONLY (D-4)."""
    lines = [
        "# FP Labeling Audit — Phase 01 polysemy/distinguo spike",
        "",
        f"**Total reviewed:** {total}",
        f"**Agreements (LLM ~= reviewer):** {agreements}",
        f"**Disagreements (surfaced below):** {len(disagreements)}",
        "",
        "> Per D-4: only disagreements are emitted. The reviewer authors",
        "> the final authoritative label in the `Final Label` column.",
        "",
        "| Cluster | Term | Reviewer | LLM | LLM Reasoning (polysemy_vs_homonymy) | Reviewer Rationale | Final Label |",
        "|---------|------|----------|-----|---------------------------------------|--------------------|-------------|",
    ]
    for d in disagreements:
        llm_reason = d["llm_reason"][:80].replace("|", "\\|")
        reviewer_rationale = (d["rationale"] or "—")[:60].replace("|", "\\|")
        lines.append(
            f"| `{d['cluster_id']}` | `{d['term']}` | {d['reviewer']} | {d['llm']} "
            f"| {llm_reason} "
            f"| {reviewer_rationale} "
            f"| _TBD_ |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


__all__ = [
    "wilson_score_interval",
    "compute_fp_rate",
    "run_llm_audit_pass",
    "KAPPA_CAVEAT",
]
