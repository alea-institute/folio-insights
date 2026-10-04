"""Human approval queue (governance plan U3, Stage C).

``build_queue`` lists the proposals that still need a human decision, with the
evidence a reviewer compares on: the current judgment (verdict, reasoning,
guardrail, nearest FOLIO concepts) and provenance references (runs, unit IDs,
spans). FOLIO definitions are attached from the lexicon when one is given. The
queue carries no source text or excerpt (R5), the same rule as the worklist.

``render_html`` renders the queue as one self-contained page. A reviewer picks
Approve / Reject / Merge / Needs work per card and copies a
``proposed-class-approvals/v1`` JSON paste-back for ``apply_approvals.py``.
The judgment's recommendation is marked on its button but **never
pre-selected**: only a choice the reviewer actually makes enters the
paste-back, so no judgment is promoted to an approval by default (KTD4). Inputs
carry ``autocomplete="off"`` and the script reads the state the page shows, so a
restored form never disagrees with the paste-back. A Merge carries the target
typed in (prefilled from a ``MERGE_WITH`` judgment); without one,
``apply_approvals.py`` refuses the merge with a clear message.

Producing a queue records nothing and approves nothing.
"""
from __future__ import annotations

import html
import json
from typing import Any

from folio_insights.proposals.decisions import MAX_NOTE_CHARS, STATUS_PENDING
from folio_insights.proposals.judgments import judgment_view
from folio_insights.proposals.lexicon import FolioLexicon
from folio_insights.proposals.registry import Proposal, ProposalRegistry

QUEUE_SCHEMA = "proposed-class-approval-queue/v1"
DECISIONS_SCHEMA = "proposed-class-approvals/v1"

# Judgment verdict -> the decision the reviewer is pointed at (never pre-selected).
RECOMMENDATION = {
    "NOVEL": "approve",
    "DUPLICATE_OF": "reject",
    "SYNONYM_OF": "reject",
    "MERGE_WITH": "merge",
    "NEEDS_WORK": "needs_work",
}
_ORDER = {
    "NOVEL": 0, None: 1, "ALIAS_CANDIDATE": 2, "NEEDS_WORK": 3, "MERGE_WITH": 4,
    "SYNONYM_OF": 5, "DUPLICATE_OF": 6,
}


def _entry(p: Proposal, lexicon: FolioLexicon | None) -> dict[str, Any]:
    judgment = judgment_view(p.judgment)
    verdict = (judgment or {}).get("verdict")
    nearest = []
    for n in (judgment or {}).get("nearest") or []:
        row = dict(n)
        if lexicon is not None:
            row["definition"] = lexicon.definition(n.get("iri") or "")
        nearest.append(row)
    if judgment is not None:
        judgment["nearest"] = nearest
    return {
        "proposal_id": p.proposal_id,
        "proposed_label": p.proposed_label,
        "label_variants": list(p.label_variants),
        "occurrences": p.occurrences,
        "provenance": {
            "runs": list(p.runs),
            "units": [
                {"run": s["run"], "unit_id": s["unit_id"], "source_span": s.get("source_span")}
                for s in p.supporting_units
            ],
        },
        "judgment": judgment,
        "recommendation": RECOMMENDATION.get(verdict),
        "decision": {"status": p.decision.get("status"), "decided_at": p.decision.get("decided_at")},
    }


def build_queue(
    registry: ProposalRegistry,
    lexicon: FolioLexicon | None = None,
    *,
    include_decided: bool = False,
    min_occurrences: int = 1,
) -> dict[str, Any]:
    """Pending proposals (or every proposal with ``include_decided``), ordered
    by verdict, then occurrences (descending), then label. Unjudged proposals
    seen fewer than ``min_occurrences`` times are counted in ``hidden``."""
    entries = []
    hidden = 0
    for p in registry.all():
        if not include_decided and p.decision.get("status") != STATUS_PENDING:
            continue
        if p.judgment is None and p.occurrences < min_occurrences:
            hidden += 1
            continue
        entries.append(_entry(p, lexicon))
    entries.sort(key=lambda e: (
        _ORDER.get((e["judgment"] or {}).get("verdict"), 9),
        -e["occurrences"],
        e["proposed_label"].casefold(),
        e["proposal_id"],
    ))
    return {
        "schema": QUEUE_SCHEMA,
        "decisions_schema": DECISIONS_SCHEMA,
        "corpus": registry.corpus,
        "ledger_head": registry.head,
        "counts": {"entries": len(entries), "hidden": hidden},
        "entries": entries,
    }


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


_CSS = """
:root{--paper:#f3f1ea;--panel:#fbfaf5;--ink:#1d2630;--ink2:#46525f;--mut:#6b7480;
--line:#ddd8ca;--accent:#1f6a66;--accent-ink:#ffffff;--warn:#9c3d2b;
--serif:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
--mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--paper:#13171c;
--panel:#1a2028;--ink:#e6e2d8;--ink2:#c0bdb3;--mut:#8b93a0;--line:#2c343e;
--accent:#48a59d;--accent-ink:#0d1114;--warn:#e07a63;}}
:root[data-theme="dark"]{--paper:#13171c;--panel:#1a2028;--ink:#e6e2d8;--ink2:#c0bdb3;
--mut:#8b93a0;--line:#2c343e;--accent:#48a59d;--accent-ink:#0d1114;--warn:#e07a63;}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--serif);
line-height:1.5;padding-bottom:96px}
.wrap{max-width:980px;margin:0 auto;padding:0 16px}
header{padding:28px 0 18px;border-bottom:2px solid var(--line)}
.eyebrow{font-family:var(--mono);font-size:12px;letter-spacing:.14em;text-transform:uppercase;
color:var(--accent);margin:0}
h1{font-size:clamp(24px,4vw,34px);margin:6px 0 8px}
.meta{font-family:var(--mono);font-size:12px;color:var(--mut)}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;margin:16px 0;
padding:14px 16px}
.card h2{font-size:19px;margin:0 0 4px}
.pid,.prov{font-family:var(--mono);font-size:11.5px;color:var(--mut);overflow-wrap:anywhere}
.verdict{font-family:var(--mono);font-size:11px;text-transform:uppercase;letter-spacing:.08em;
border:1px solid var(--line);border-radius:999px;padding:2px 8px}
.reason{color:var(--ink2);margin:8px 0}
.guardrail{color:var(--warn);font-weight:600;margin:8px 0}
table{width:100%;border-collapse:collapse;font-size:13px;margin:8px 0}
th,td{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{font-family:var(--mono);font-size:10.5px;text-transform:uppercase;color:var(--mut)}
fieldset{border:0;padding:0;margin:10px 0 6px;display:flex;flex-wrap:wrap;gap:8px}
legend{font-family:var(--mono);font-size:11px;text-transform:uppercase;color:var(--mut);
margin-bottom:4px}
label.opt{border:1px solid var(--line);border-radius:999px;padding:3px 11px;cursor:pointer}
label.opt:has(input:checked){border-color:var(--accent);outline:1px solid var(--accent)}
label.rec::after{content:" (recommended)";font-family:var(--mono);font-size:10px;color:var(--accent)}
label.merge{display:block;font-family:var(--mono);font-size:11px;color:var(--mut);margin:4px 0 8px}
label.merge input{font:inherit;color:var(--ink);background:var(--paper);border:1px solid var(--line);
border-radius:6px;padding:4px 6px;margin-left:6px;width:min(320px,100%)}
textarea{width:100%;min-height:40px;border:1px solid var(--line);border-radius:8px;
background:var(--paper);color:var(--ink);font:inherit;padding:6px 8px}
input:focus-visible,textarea:focus-visible,button:focus-visible{outline:2px solid var(--accent);
outline-offset:2px}
.bar{position:fixed;left:0;right:0;bottom:0;background:var(--panel);border-top:1px solid var(--line)}
.bar .wrap{display:flex;gap:10px;align-items:center;padding:10px 16px;flex-wrap:wrap}
.bar span{font-family:var(--mono);font-size:12px;color:var(--mut);flex:1}
button{font:inherit;border-radius:8px;border:1px solid var(--accent);background:var(--accent);
color:var(--accent-ink);padding:8px 14px;cursor:pointer}
#out{width:100%;min-height:120px;font-family:var(--mono);font-size:12px;display:none}
#out.open{display:block}
"""

_JS = """
(function(){
  var data=JSON.parse(document.getElementById('queue-data').textContent);
  var chosen={},notes={},targets={};
  // Read the state the page actually shows (a browser may restore form state on reload), so
  // the paste-back never disagrees with what the reviewer sees.
  document.querySelectorAll('input[type=radio]').forEach(function(r){
    if(r.checked)chosen[r.dataset.pid]=r.value;
    r.addEventListener('change',function(){chosen[r.dataset.pid]=r.value;count();});
  });
  document.querySelectorAll('textarea[data-pid]').forEach(function(t){
    if(t.value)notes[t.dataset.pid]=t.value;
    t.addEventListener('input',function(){notes[t.dataset.pid]=t.value;count();});
  });
  document.querySelectorAll('input[data-merge-for]').forEach(function(m){
    targets[m.dataset.mergeFor]=m.value;
    m.addEventListener('input',function(){targets[m.dataset.mergeFor]=m.value;});
  });
  count();
  function count(){document.getElementById('n').textContent=Object.keys(chosen).length;}
  function blob(){
    var out={schema:data.decisions_schema,corpus:data.corpus,decisions:{}};
    Object.keys(chosen).sort().forEach(function(pid){
      var d={status:chosen[pid]};
      if(notes[pid]&&notes[pid].trim())d.note=notes[pid].trim();
      if(chosen[pid]==='merge'&&targets[pid]&&targets[pid].trim())d.merge_into=targets[pid].trim();
      out.decisions[pid]=d;
    });
    return JSON.stringify(out,null,2);
  }
  document.getElementById('copy').addEventListener('click',function(){
    var box=document.getElementById('out');box.value=blob();box.classList.add('open');
    box.focus();box.select();
    try{document.execCommand('copy');}catch(e){}
  });
})();
"""


def _card(e: dict[str, Any]) -> str:
    pid = e["proposal_id"]
    j = e["judgment"] or {}
    verdict = j.get("verdict") or "UNJUDGED"
    rows = "".join(
        f"<tr><td>{_esc(n.get('label'))}<div class='pid'>{_esc(n.get('iri'))}"
        f"{' · ' + _esc(n.get('match_form')) if n.get('match_form') else ''}</div></td>"
        f"<td>{_esc(n.get('definition', ''))}</td></tr>"
        for n in j.get("nearest") or []
    )
    table = (
        "<table><tr><th>Nearest FOLIO concept</th><th>FOLIO definition</th></tr>"
        f"{rows}</table>" if rows else ""
    )
    guardrail = (
        f"<p class='guardrail'>Guardrail: {_esc(j.get('guardrail'))}. A label collision is "
        "not a duplicate until the definitions agree.</p>" if j.get("guardrail") else ""
    )
    reason = f"<p class='reason'>{_esc(j.get('reasoning'))}</p>" if j.get("reasoning") else ""
    units = ", ".join(
        f"{_esc(u['run'])}/{_esc(u['unit_id'])}" for u in e["provenance"]["units"]
    )
    options = ""
    for value, text in (("approve", "Approve"), ("reject", "Reject"), ("merge", "Merge"),
                        ("needs_work", "Needs work")):
        rec = " rec" if e["recommendation"] == value else ""
        options += (
            f"<label class='opt{rec}'><input type='radio' name='d-{_esc(pid)}' "
            f"value='{value}' data-pid='{_esc(pid)}' autocomplete='off'> {text}</label>"
        )
    merge_default = j.get("target_proposal_id") if j.get("verdict") == "MERGE_WITH" else ""
    merge = (
        f"<label class='merge'>Merge into (proposal ID, used only with Merge) "
        f"<input type='text' data-merge-for='{_esc(pid)}' value='{_esc(merge_default or '')}' "
        f"autocomplete='off' spellcheck='false' placeholder='PC-…'></label>"
    )
    return (
        f"<article class='card' id='{_esc(pid)}'>"
        f"<span class='verdict'>{_esc(verdict)}</span>"
        f"<h2>{_esc(e['proposed_label'])}</h2>"
        f"<div class='pid'>{_esc(pid)} · {e['occurrences']} occurrence(s) · judged by "
        f"{_esc(j.get('judged_by') or 'nobody yet')}</div>"
        f"<div class='prov'>units: {units or 'none recorded'}</div>"
        f"{reason}{guardrail}{table}"
        f"<fieldset><legend>Your decision</legend>{options}</fieldset>"
        f"{merge}"
        f"<textarea data-pid='{_esc(pid)}' aria-label='Reviewer note for {_esc(pid)}' "
        f"maxlength='{MAX_NOTE_CHARS}' autocomplete='off' "
        "placeholder='Optional reviewer note in your own words (never paste source text)'>"
        "</textarea>"
        "</article>"
    )


def render_html(queue: dict[str, Any]) -> str:
    cards = "\n".join(_card(e) for e in queue["entries"])
    data = json.dumps(
        {"decisions_schema": queue["decisions_schema"], "corpus": queue["corpus"]},
        sort_keys=True,
    ).replace("<", "\\u003c")
    counts = queue["counts"]
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Proposal Approval Queue</title>"
        f"<style>{_CSS}</style></head><body>"
        "<header><div class='wrap'><p class='eyebrow'>folio-insights · proposed classes</p>"
        "<h1>Approval queue</h1>"
        f"<p class='meta'>corpus {_esc(queue['corpus'])} · ledger head {queue['ledger_head']} · "
        f"{counts['entries']} to decide · {counts['hidden']} hidden below the occurrence floor</p>"
        "<p>Nothing is pre-selected. Only the cards you decide enter the paste-back. "
        "Apply it with <code>scripts/apply_approvals.py apply</code>.</p>"
        "</div></header>"
        f"<main class='wrap'>{cards}</main>"
        "<div class='bar'><div class='wrap'><span><b id='n'>0</b> decided</span>"
        "<button id='copy' type='button'>Copy decisions</button>"
        "<textarea id='out' readonly aria-label='Decisions paste-back'></textarea></div></div>"
        f"<script type='application/json' id='queue-data'>{data}</script>"
        f"<script>{_JS}</script></body></html>\n"
    )


__all__ = ["DECISIONS_SCHEMA", "QUEUE_SCHEMA", "RECOMMENDATION", "build_queue", "render_html"]
