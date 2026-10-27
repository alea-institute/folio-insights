"""False-positive audit and the PRINCIPLE-06 FP gate (Phase 1 spike; Phase 9 U6).

The gate (R9, KTD9) reads the Wilson 95% CI **upper** bound of the FP rate,
never the point estimate and never the lower bound. Phase 1 recorded a "pass"
against the lower bound (2 of 22: lower 2.53%, upper 27.82%); a ceiling claim
("FP rate <= 10%") needs the upper bound, so that "pass" did not hold.

FP definition (KTD9): a detector MISCALL — the detector said ``polysemy`` and
the disposition rejects it, with a rationale. Phase 1 counted "reject with an
empty rationale", which measures disposition quality rather than the detector.
A reject with an empty rationale is now an invalid disposition (the review CLI
and ``append_disposition`` refuse one): the gate never counts it as an FP and
leaves it out of N, reporting the count.

Gate status (``fp_gate``) never self-certifies:

* upper bound > 10%                              -> ``fail`` (certified or not);
* upper bound <= 10% with a valid human
  certification of this exact labeled set         -> ``pass``;
* otherwise                                       -> ``provisional``.

A certification record names a human (``certified_by``), when, the sample the
human reviewed, and the SHA-256 of the labeled cases it covers; agents never
write one. Who certifies is Open Question 1 of the Phase 9 plan.

Also runs an LLM audit pass that emits only disagreements — the
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
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from folio_insights.polysemy.dispositions import DispositionRecord, read_dispositions
from folio_insights.proposals.signed_decisions import SignedDecision

if TYPE_CHECKING:  # labeled_set imports this module; no runtime cycle
    from folio_insights.polysemy.labeled_set import LabeledSet

logger = logging.getLogger(__name__)

KAPPA_CAVEAT = (
    "Cohen's kappa is reported as a SIGNAL, not a verdict. At N<=30 the "
    "measure is volatile (pilot ECE 0.108-0.427); use the Wilson CI upper "
    "bound for gating decisions."
)

# R9: the Wilson 95% upper bound of the FP rate must be at most 10%.
FP_GATE_THRESHOLD = 0.10
GateStatus = Literal["provisional", "pass", "fail"]
# The reviewer ID agent-written (first-pass) dispositions carry.
AGENT_LABELER_ID = "urn:folio-insights:labeler:agent"
# A certifier naming any of these tokens (case-insensitive) names an agent, not
# a human; a certification by one is refused.
_AGENT_TOKENS = frozenset({"agent", "assistant", "ai", "llm", "claude", "gpt", "bot", "model"})
_TOKEN = re.compile(r"[A-Za-z0-9]+")
# A certification counts only when its reviewed sample covers at least this
# share of the cases (rounded up) and at least one case of every gold label.
MIN_SAMPLE_SHARE = 0.20


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


def _detector_flagged(record: DispositionRecord) -> bool:
    return (record.detector_verdict or {}).get("decision") == "polysemy"


def is_valid_disposition(record: DispositionRecord) -> bool:
    """A reject needs a rationale; every other disposition is valid as recorded."""
    return record.decision != "reject" or record.has_rationale


def is_false_positive(record: DispositionRecord) -> bool:
    """KTD9: a detector miscall — the detector said ``polysemy`` and the
    disposition rejects that with a rationale. An empty-rationale reject is
    invalid, never an FP."""
    return _detector_flagged(record) and record.decision == "reject" and record.has_rationale


def _names_an_agent(value: str) -> bool:
    text = value.strip()
    if not text or text == AGENT_LABELER_ID:
        return True
    tokens = {t.lower() for t in _TOKEN.findall(text)}
    return bool(tokens & _AGENT_TOKENS)


class Certification(BaseModel):
    """A human's certification of one labeled set (Open Question 1 hook).

    Agents never write this record. It binds to the labeled cases by digest,
    so editing a case after certification voids it, and ``fp_gate`` honours it
    only when the reviewed sample is meaningful (``MIN_SAMPLE_SHARE`` of the
    cases and at least one case of every gold label).

    Legacy unsigned records remain readable but cannot certify the gate.
    The gate verifies ``signed_decision`` against the complete certificate,
    its corpus and the current reviewer registry. This authenticates review
    authorship; the sample, case correspondence and Wilson checks still decide
    whether the evaluation passes.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    certified_by: str = Field(min_length=1)   # a human handle or DID
    certified_at: datetime
    sample_reviewed: tuple[str, ...] = Field(min_length=1)  # case IDs the human checked
    cases_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    note: str = ""
    corpus: str | None = None
    signed_decision: SignedDecision | None = None

    @field_validator("certified_by")
    @classmethod
    def _human(cls, value: str) -> str:
        if _names_an_agent(value):
            raise ValueError(f"certified_by {value!r} does not name a human reviewer")
        return value


@dataclass(frozen=True)
class FpGateReport:
    """The FP gate's figures and status (every figure, not only the gate's)."""

    n: int                      # valid dispositions (the gate's denominator)
    false_positives: int
    fp_rate: float
    ci_lower: float
    ci_upper: float             # THE gate figure
    threshold: float
    status: GateStatus
    certified: bool
    certification_problem: str | None
    invalid_dispositions: int   # empty-rationale rejects, excluded from n
    detector_positives: int     # dispositions where the detector said polysemy
    # FP / detector positives: the share of the detector's flags that were wrong.
    # Reported, not gated (R9 gates the FP rate over the labeled set).
    false_discovery_rate: float
    false_discovery_upper: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _records_match_cases(records: list[DispositionRecord], labeled: LabeledSet) -> bool:
    """Exactly one record per case (``audit_label`` = case ID) carrying that
    case's term, decision and rationale."""
    by_case: dict[str, DispositionRecord] = {}
    for record in records:
        if record.audit_label is None or record.audit_label in by_case:
            return False
        by_case[record.audit_label] = record
    if set(by_case) != {c.id for c in labeled.cases}:
        return False
    return all(
        by_case[c.id].term == c.term
        and by_case[c.id].decision == c.disposition.decision
        and by_case[c.id].rationale == c.disposition.rationale
        for c in labeled.cases
    )


def _certification_problem(records: list[DispositionRecord], labeled: LabeledSet | None) -> str | None:
    if labeled is None or labeled.certification is None:
        return "no certification record (status stays provisional; Open Question 1)"
    certification = labeled.certification
    if certification.cases_sha256 != labeled.cases_sha256():
        return "the certification does not cover these labeled cases (digest mismatch)"
    if not _records_match_cases(records, labeled):
        return "the records do not match the labeled cases (one record per case, same disposition)"
    sample = set(certification.sample_reviewed)
    needed = math.ceil(MIN_SAMPLE_SHARE * len(labeled.cases))
    if len(sample) < needed:
        return f"the reviewed sample has {len(sample)} cases; at least {needed} are needed"
    sampled_labels = {c.gold for c in labeled.cases if c.id in sample}
    missing = sorted({c.gold for c in labeled.cases} - sampled_labels)
    if missing:
        return f"the reviewed sample has no case of gold label(s) {missing}"
    from folio_insights.polysemy.signing import verify_certification
    from folio_insights.proposals.signed_decisions import DecisionPolicyMisconfigured

    try:
        verify_certification(certification, corpus=labeled.corpus)
    except (ValueError, DecisionPolicyMisconfigured):
        return "registered reviewer signature does not verify for this certification"
    return None


def fp_gate(
    records: Iterable[DispositionRecord],
    *,
    labeled: LabeledSet | None = None,
    threshold: float = FP_GATE_THRESHOLD,
) -> FpGateReport:
    """The PRINCIPLE-06 gate over ``records`` (see the module docstring).

    The certification, if any, comes from ``labeled`` (never from the caller),
    and it counts only when the gate itself finds that it names the digest of
    ``labeled``'s cases, that ``records`` are exactly those cases'
    dispositions, and that the reviewed sample is meaningful.
    """
    all_records = list(records)
    valid = [r for r in all_records if is_valid_disposition(r)]
    n = len(valid)
    fps = sum(1 for r in valid if is_false_positive(r))
    positives = sum(1 for r in valid if _detector_flagged(r))
    ci_lower, ci_upper = wilson_score_interval(fps, n)
    _, fdr_upper = wilson_score_interval(fps, positives)

    problem = _certification_problem(all_records, labeled)
    certified = problem is None

    if ci_upper > threshold:  # includes n == 0, whose interval is (0, 1)
        status: GateStatus = "fail"
    else:
        status = "pass" if certified else "provisional"
    return FpGateReport(
        n=n,
        false_positives=fps,
        fp_rate=(fps / n) if n else 0.0,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        threshold=threshold,
        status=status,
        certified=certified,
        certification_problem=problem,
        invalid_dispositions=len(all_records) - n,
        detector_positives=positives,
        false_discovery_rate=(fps / positives) if positives else 0.0,
        false_discovery_upper=fdr_upper,
    )


def compute_fp_rate(dispositions_path: pathlib.Path) -> dict[str, Any]:
    """Tally a dispositions log and compute the Wilson-bounded FP rate.

    ``total`` counts valid dispositions only; ``invalid_dispositions`` counts
    the empty-rationale rejects left out. A plain log carries no
    certification, so ``status`` is never ``pass`` here.
    """
    records = list(read_dispositions(dispositions_path))
    report = fp_gate(records)
    # Cohen's kappa (detector vs reviewer) — signal only.
    kappa = _compute_kappa_signal([r for r in records if is_valid_disposition(r)])
    return {
        "total": report.n,
        "false_positives": report.false_positives,
        "fp_rate": report.fp_rate,
        "ci_lower": report.ci_lower,
        "ci_upper": report.ci_upper,
        "status": report.status,
        "invalid_dispositions": report.invalid_dispositions,
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
    llm: Any | None = None,
) -> dict[str, Any]:
    """Run a second-reader LLM pass; emit disagreements only to report_path.

    D-4: the audit EMITS DISAGREEMENTS ONLY. Agreements are silently
    counted; disagreements land in fp-labeling-audit.md for manual
    reconciliation.

    Per OQ-5 RESOLVED: single `llm_provider` parameter carries the model
    string (e.g. "claude-haiku-4-5"). Its family is resolved with the
    detector's prefix mapping and the call is routed through the LLM port —
    there is NO separate `model` parameter.

    The client is the Phase 10 port's ``TaskLLM`` (via ``LLMBridge.
    get_llm_for_task``); ``llm`` injects any object with the same
    ``structured_model_sync(prompt, schema, *, template)`` call (a fake in
    tests), and then no route or credential is resolved at all.
    """
    if llm is not None:
        client = llm
    else:
        from folio_insights.llm import Route
        from folio_insights.polysemy.detector import _resolve_provider_family
        from folio_insights.services.bridge.llm_bridge import LLMBridge

        bridge = llm_bridge if llm_bridge is not None else LLMBridge()
        family = _resolve_provider_family(llm_provider)
        model = llm_provider.removeprefix("ollama/")
        client = bridge.get_llm_for_task(
            "polysemy_fallback", route=Route(provider=family, model=model)
        )

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
    """One validated ``PolysemyVerdict`` call through the LLM port's task facade.

    Embeds the canonical `detector_verdict: dict` snapshot verbatim in the
    prompt — the LLM sees exactly what the detector reported. (The previous
    version called an instructor-style ``client.chat.completions.create`` on
    the folio-enrich provider, which has no such method.)
    """
    from folio_insights.llm.schemas import PolysemyVerdict
    from folio_insights.llm.templates import POLYSEMY_FP_AUDIT

    prompt = POLYSEMY_FP_AUDIT.render(
        term=record.term,
        cluster_id=record.cluster_id,
        decision=record.decision,
        rationale=record.rationale or "(none)",
        detector_verdict=record.detector_verdict,
    )
    return client.structured_model_sync(prompt, PolysemyVerdict, template=POLYSEMY_FP_AUDIT)


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
    "AGENT_LABELER_ID",
    "Certification",
    "MIN_SAMPLE_SHARE",
    "FP_GATE_THRESHOLD",
    "FpGateReport",
    "GateStatus",
    "KAPPA_CAVEAT",
    "compute_fp_rate",
    "fp_gate",
    "is_false_positive",
    "is_valid_disposition",
    "run_llm_audit_pass",
    "wilson_score_interval",
]
