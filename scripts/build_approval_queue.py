"""Build the human approval-queue artifact — Stage C.

Renders the proposed-class registry as an actionable, round-trippable decision
page in the folio-insights house style: per-entry proposal + draft definition +
evidence spans + judge verdict + nearest-FOLIO-concept comparison table, with
Approve / Reject / Merge / Needs-work affordances (judge recommendation pre-
selected) and a Copy-answers stable-ID JSON paste-back (execCommand fallback —
navigator.clipboard is blocked in artifact iframes).

Emits:
  approval-queue.html            standalone (with <!doctype>)
  approval-queue.artifact.html   body-only for the Artifact tool

Usage:
  python scripts/build_approval_queue.py \
    --registry data/governance/proposed_class_registry.json \
    --out data/governance
"""
from __future__ import annotations
import argparse
import html
import json
from pathlib import Path

VERDICT_LABEL = {
    "NOVEL": "Novel", "DUPLICATE_OF": "Duplicate", "SYNONYM_OF": "Synonym",
    "MERGE_WITH": "Merge", "NEEDS_WORK": "Needs work", None: "Unjudged",
}
# judge verdict -> recommended human pre-select
VERDICT_TO_DECISION = {
    "NOVEL": "approve", "DUPLICATE_OF": "reject", "SYNONYM_OF": "reject",
    "MERGE_WITH": "merge", "NEEDS_WORK": "needs_work", None: None,
}


def esc(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


CSS = """
:root{--paper:#f4f2ec;--panel:#fbfaf6;--ink:#1b2530;--ink2:#3b4756;--mut:#6a7482;
--line:#e0dccf;--line2:#d0ccbe;--accent:#1f6f6b;--accent2:#155551;--nov:#2f7d4f;
--dup:#b3402f;--syn:#b3792f;--mrg:#6d5aa8;--nw:#3f6597;
--nov-bg:#e6efe3;--dup-bg:#f6e4df;--syn-bg:#f6ecd9;--mrg-bg:#ece8f5;--nw-bg:#e2ebf5;
--serif:"Iowan Old Style","Palatino Linotype","Book Antiqua",Palatino,Georgia,serif;
--sans:ui-sans-serif,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
--mono:ui-monospace,"SF Mono","JetBrains Mono",Menlo,Consolas,monospace;
--shadow:0 1px 2px rgba(27,37,48,.06),0 4px 14px rgba(27,37,48,.05);}
@media (prefers-color-scheme:dark){:root{--paper:#12161b;--panel:#191f27;--ink:#e7e3d9;
--ink2:#c3c0b6;--mut:#8b93a0;--line:#2a323c;--line2:#37404c;--accent:#43a49c;--accent2:#5bb8b0;
--nov:#6db98a;--dup:#e2725c;--syn:#d99b4e;--mrg:#a493d6;--nw:#7ea3d6;
--nov-bg:#1a241a;--dup-bg:#2e1e1a;--syn-bg:#2c2517;--mrg-bg:#221f2c;--nw-bg:#182430;
--shadow:0 1px 2px rgba(0,0,0,.3),0 6px 18px rgba(0,0,0,.28);}}
:root[data-theme="light"]{--paper:#f4f2ec;--panel:#fbfaf6;--ink:#1b2530;--ink2:#3b4756;--mut:#6a7482;--line:#e0dccf;--line2:#d0ccbe;--accent:#1f6f6b;--accent2:#155551;--nov:#2f7d4f;--dup:#b3402f;--syn:#b3792f;--mrg:#6d5aa8;--nw:#3f6597;--nov-bg:#e6efe3;--dup-bg:#f6e4df;--syn-bg:#f6ecd9;--mrg-bg:#ece8f5;--nw-bg:#e2ebf5;}
:root[data-theme="dark"]{--paper:#12161b;--panel:#191f27;--ink:#e7e3d9;--ink2:#c3c0b6;--mut:#8b93a0;--line:#2a323c;--line2:#37404c;--accent:#43a49c;--accent2:#5bb8b0;--nov:#6db98a;--dup:#e2725c;--syn:#d99b4e;--mrg:#a493d6;--nw:#7ea3d6;--nov-bg:#1a241a;--dup-bg:#2e1e1a;--syn-bg:#2c2517;--mrg-bg:#221f2c;--nw-bg:#182430;}
*{box-sizing:border-box}
.gq{background:var(--paper);color:var(--ink);font-family:var(--sans);line-height:1.5;font-size:15px;padding-bottom:96px;min-height:100vh;-webkit-font-smoothing:antialiased}
.wrap{max-width:1080px;margin:0 auto;padding:0 22px}
.gq a{color:var(--accent);text-decoration:none}.gq a:hover{text-decoration:underline}
.masthead{border-bottom:2px solid var(--line2);background:linear-gradient(180deg,color-mix(in srgb,var(--accent) 7%,var(--paper)),var(--paper))}
.eyebrow{font-family:var(--mono);font-size:11.5px;letter-spacing:.16em;text-transform:uppercase;color:var(--accent2);margin:0 0 8px}
.mast-h{font-family:var(--serif);font-weight:600;font-size:clamp(24px,4vw,36px);line-height:1.1;margin:0;letter-spacing:-.01em}
.mast-sub{color:var(--ink2);max-width:70ch;margin:12px 0 0;font-size:15px}
.metabar{display:flex;flex-wrap:wrap;gap:8px 18px;margin:16px 0 2px;font-family:var(--mono);font-size:12px;color:var(--mut)}
.metabar b{color:var(--ink2)}
.tiles{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:26px 0}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;box-shadow:var(--shadow)}
.tnum{font-family:var(--serif);font-size:26px;font-weight:600;font-variant-numeric:tabular-nums}
.tlbl{font-weight:600;font-size:12.5px;margin-top:2px}.tsub{color:var(--mut);font-size:11px;margin-top:2px;font-family:var(--mono)}
.toolbar{position:sticky;top:0;z-index:30;background:color-mix(in srgb,var(--paper) 92%,transparent);backdrop-filter:blur(8px);border-bottom:1px solid var(--line);padding:11px 0;margin:8px 0 20px}
.chips{display:flex;flex-wrap:wrap;gap:9px;align-items:center}
.chip{display:inline-flex;align-items:center;gap:7px;border:1px solid var(--line2);background:var(--panel);color:var(--ink2);border-radius:999px;padding:6px 12px;font-size:12.5px;font-weight:600;cursor:pointer}
.chip[aria-pressed="true"]{background:color-mix(in srgb,var(--accent) 13%,var(--paper));border-color:var(--accent);color:var(--ink)}
.chip .ct{font-family:var(--mono);font-size:11px;color:var(--mut)}
.stream{display:grid;gap:14px}
.card{background:var(--panel);border:1px solid var(--line);border-left:4px solid var(--vc,var(--line2));border-radius:12px;box-shadow:var(--shadow);overflow:hidden}
.v-NOVEL{--vc:var(--nov);--vbg:var(--nov-bg)}.v-DUPLICATE_OF{--vc:var(--dup);--vbg:var(--dup-bg)}
.v-SYNONYM_OF{--vc:var(--syn);--vbg:var(--syn-bg)}.v-MERGE_WITH{--vc:var(--mrg);--vbg:var(--mrg-bg)}
.v-NEEDS_WORK,.v-none{--vc:var(--nw);--vbg:var(--nw-bg)}
.chead{display:flex;flex-wrap:wrap;align-items:center;gap:10px;padding:12px 16px;border-bottom:1px solid var(--line);background:color-mix(in srgb,var(--vc,var(--panel)) 6%,var(--panel))}
.pid{font-family:var(--mono);font-size:11px;color:var(--mut)}
.plabel{font-family:var(--serif);font-size:19px;font-weight:600}
.vbadge{font-family:var(--mono);font-size:10px;letter-spacing:.06em;text-transform:uppercase;font-weight:700;color:#fff;background:var(--vc);padding:3px 9px;border-radius:999px}
.occ{margin-left:auto;font-family:var(--mono);font-size:11.5px;color:var(--mut)}
.cbody{padding:14px 16px}
.ddef{font-size:14px;color:var(--ink2);margin:0 0 12px;padding:10px 12px;background:var(--paper);border:1px solid var(--line);border-radius:9px}
.sect-lbl{font-family:var(--mono);font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--mut);margin:0 0 6px}
.reason{font-size:13.5px;color:var(--ink2);border-left:3px solid var(--vc);padding:2px 0 2px 11px;margin:0 0 12px}
.guardrail{font-size:12.5px;color:var(--dup);font-weight:600;margin:0 0 12px}
table.cmp{width:100%;border-collapse:collapse;font-size:12.5px;margin:0 0 12px}
table.cmp th,table.cmp td{border:1px solid var(--line);padding:7px 9px;text-align:left;vertical-align:top}
table.cmp th{font-family:var(--mono);font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--mut);background:var(--paper)}
.ev{font-size:12.5px;color:var(--ink2);margin:0 0 4px}
.ev .prov{font-family:var(--mono);font-size:10.5px;color:var(--mut)}
.decide{margin-top:12px;padding-top:11px;border-top:1px solid var(--line)}
.drow{display:flex;flex-wrap:wrap;align-items:center;gap:8px 10px;margin-bottom:8px}
.dlbl{font-family:var(--mono);font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--mut)}
.rb{display:inline-flex;align-items:center;gap:5px;font-size:12.5px;cursor:pointer;border:1px solid var(--line2);border-radius:999px;padding:3px 11px 3px 8px;user-select:none}
.rb input{accent-color:var(--accent);margin:0}
.rb:has(input:checked){border-color:var(--accent);background:color-mix(in srgb,var(--accent) 12%,var(--paper))}
.rb.rec::after{content:"★ rec";font-family:var(--mono);font-size:9px;color:var(--accent2);margin-left:2px}
.note{width:100%;min-height:36px;border:1px solid var(--line2);border-radius:8px;padding:8px 10px;font-family:var(--sans);font-size:13px;background:var(--paper);color:var(--ink);resize:vertical}
.note:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
.card[hidden]{display:none}
.actionbar{position:fixed;left:0;right:0;bottom:0;z-index:40;background:color-mix(in srgb,var(--panel) 96%,transparent);backdrop-filter:blur(10px);border-top:1px solid var(--line2);box-shadow:0 -4px 20px rgba(27,37,48,.08)}
.actionbar .wrap{display:flex;align-items:center;gap:12px;padding:12px 22px}
.abtext{font-size:12.5px;color:var(--mut);font-family:var(--mono)}.abtext b{color:var(--ink2)}
.spacer{flex:1}
.act{font-family:var(--sans);font-weight:600;font-size:13.5px;border-radius:9px;padding:9px 16px;cursor:pointer;border:1px solid var(--line2);background:var(--paper);color:var(--ink)}
.act.primary{background:var(--accent);border-color:var(--accent);color:#fff}.act.primary:hover{background:var(--accent2)}
.preview{max-width:1080px;margin:0 auto;padding:0 22px 12px;display:none}.preview.open{display:block}
.preview textarea{width:100%;min-height:130px;font-family:var(--mono);font-size:11.5px;border:1px solid var(--line2);border-radius:8px;padding:10px;background:var(--paper);color:var(--ink2)}
.section-lbl{font-family:var(--mono);font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--mut);margin:24px 0 14px;display:flex;align-items:center;gap:12px}
.section-lbl::after{content:"";flex:1;height:1px;background:var(--line2)}
@media (max-width:820px){.tiles{grid-template-columns:repeat(2,1fr)}}
"""

JS_TMPL = """
(function(){
  var KEY='__KEY__';
  var root=document.getElementById('gq-root');
  function load(){try{return JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){return{}}}
  function save(s){try{localStorage.setItem(KEY,JSON.stringify(s))}catch(e){}}
  var state=load();
  root.querySelectorAll('.decide input[type=radio]').forEach(function(r){
    var pid=r.closest('.decide').getAttribute('data-pid');
    if(state.dec&&state.dec[pid]===r.value)r.checked=true;
    r.addEventListener('change',function(){state.dec=state.dec||{};state.dec[pid]=r.value;save(state);count()});
  });
  root.querySelectorAll('textarea.note').forEach(function(t){
    var pid=t.getAttribute('data-pid');
    if(state.note&&state.note[pid])t.value=state.note[pid];
    t.addEventListener('input',function(){state.note=state.note||{};state.note[pid]=t.value;save(state);count()});
  });
  // filters
  var active=new Set(),chips=root.querySelectorAll('.chip[data-v]'),allChip=root.querySelector('.chip.all');
  function apply(){
    root.querySelectorAll('.card').forEach(function(c){
      if(active.size===0){c.hidden=false;return;}
      c.hidden=!active.has(c.getAttribute('data-v'));
    });
    chips.forEach(function(c){c.setAttribute('aria-pressed',active.has(c.getAttribute('data-v')))});
    allChip.setAttribute('aria-pressed',active.size===0);
    document.getElementById('viscount').textContent=root.querySelectorAll('.card:not([hidden])').length;
  }
  chips.forEach(function(c){c.addEventListener('click',function(){var v=c.getAttribute('data-v');if(active.has(v))active.delete(v);else active.add(v);apply();})});
  allChip.addEventListener('click',function(){active.clear();apply();});
  apply();
  function count(){
    var n=state.dec?Object.keys(state.dec).length:0;
    var m=0;if(state.note)Object.keys(state.note).forEach(function(k){if(state.note[k]&&state.note[k].trim())m++});
    document.getElementById('decided').textContent=n;document.getElementById('noted').textContent=m;
  }
  count();
  function blob(){
    var o={registry:'__REG__',schema:'proposed-class-approvals/v1',decisions:{}};
    if(state.dec)Object.keys(state.dec).forEach(function(pid){o.decisions[pid]={status:state.dec[pid]}});
    if(state.note)Object.keys(state.note).forEach(function(pid){if(state.note[pid]&&state.note[pid].trim()){o.decisions[pid]=o.decisions[pid]||{};o.decisions[pid].note=state.note[pid].trim();}});
    return JSON.stringify(o,null,2);
  }
  function copyText(txt){var done=false;try{var ta=document.createElement('textarea');ta.value=txt;ta.style.position='fixed';ta.style.top='-9999px';document.body.appendChild(ta);ta.focus();ta.select();done=document.execCommand('copy');document.body.removeChild(ta);}catch(e){done=false;}if(!done&&navigator.clipboard){navigator.clipboard.writeText(txt).catch(function(){});}return done;}
  var cb=document.getElementById('copyBtn');
  cb.addEventListener('click',function(){var t=blob();var ok=copyText(t);document.getElementById('previewText').value=t;cb.textContent=ok?'✓ Copied':'Copied (see preview)';setTimeout(function(){cb.textContent='Copy decisions'},2200);});
  var pv=document.getElementById('preview');
  document.getElementById('previewBtn').addEventListener('click',function(){pv.classList.toggle('open');if(pv.classList.contains('open'))document.getElementById('previewText').value=blob();});
})();
"""


def render_card(e: dict) -> str:
    j = e.get("judge") or {}
    verdict = j.get("verdict")
    vclass = f"v-{verdict}" if verdict else "v-none"
    pid = e["proposal_id"]
    prov = e.get("provenance", {})
    prov_txt = (f"{', '.join(prov.get('books', []))} · Ch {', '.join(prov.get('chapters', []))} "
                f"· {e.get('occurrences', 0)}× · runs {', '.join(prov.get('runs', []))}")
    # nearest comparison table
    nearest = j.get("nearest") or []
    cmp_rows = ""
    for n in nearest:
        cmp_rows += (f"<tr><td><a href='{esc(n.get('iri',''))}' target='_blank' rel='noopener'>"
                     f"{esc(n.get('label',''))}</a><div class='pid'>{esc((n.get('iri') or '').rsplit('/',1)[-1])}"
                     f"{' · '+esc(n.get('match_form')) if n.get('match_form') else ''}</div></td>"
                     f"<td>{esc(n.get('definition',''))}</td></tr>")
    cmp_table = (f"<div class='sect-lbl'>Nearest FOLIO concept(s) — compare on definition</div>"
                 f"<table class='cmp'><tr><th>Concept</th><th>Definition</th></tr>{cmp_rows}</table>"
                 if cmp_rows else "")
    # evidence
    ev = ""
    for s in e.get("supporting_units", [])[:4]:
        ex = s.get("source_text_excerpt", "")
        if ex:
            ev += (f"<div class='ev'>“{esc(ex)}”<span class='prov'> — {esc(s.get('book',''))} Ch"
                   f"{esc(s.get('chapter',''))} · {esc(s.get('unit_id','')[:8])}</span></div>")
    ev_block = f"<div class='sect-lbl'>Supporting source spans</div>{ev}" if ev else ""
    guardrail = (f"<p class='guardrail'>⚠ {esc(j.get('guardrail'))} — this is an alias/label collision; "
                 f"confirm on the definition before rejecting as a duplicate.</p>"
                 if j.get("guardrail") else "")
    reason = f"<p class='reason'>{esc(j.get('reasoning',''))}</p>" if j.get("reasoning") else \
             "<p class='reason'>Survivor of deterministic dedupe — no exact/alias FOLIO match; judged novel/near by Claude.</p>"
    rec = VERDICT_TO_DECISION.get(verdict)
    opts = [("approve", "Approve"), ("reject", "Reject"), ("merge", "Merge"), ("needs_work", "Needs work")]
    radios = ""
    for val, lbl in opts:
        cls = "rb rec" if val == rec else "rb"
        chk = " checked" if val == rec else ""
        radios += (f"<label class='{cls}'><input type='radio' name='d-{esc(pid)}' value='{val}'{chk}>"
                   f"<span>{lbl}</span></label>")
    vlabel = VERDICT_LABEL.get(verdict, "Unjudged")
    judged_by = esc(j.get("judged_by", "—"))
    return f"""    <article class="card {vclass}" data-v="{verdict or 'none'}" id="{esc(pid)}">
      <div class="chead">
        <span class="vbadge">{esc(vlabel)}</span>
        <span class="plabel">{esc(e['proposed_label'])}</span>
        <span class="pid">{esc(pid)} · judged by {judged_by}</span>
        <span class="occ">{prov_txt}</span>
      </div>
      <div class="cbody">
        <div class="ddef"><b>Draft definition.</b> {esc(e.get('draft_definition',''))}</div>
        {reason}
        {guardrail}
        {cmp_table}
        {ev_block}
        <div class="decide" data-pid="{esc(pid)}">
          <div class="drow"><span class="dlbl">Your decision</span>{radios}</div>
          <textarea class="note" data-pid="{esc(pid)}" placeholder="Notes / refined definition / target IRI… (saved locally)"></textarea>
        </div>
      </div>
    </article>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--key", default="gq-proposed-class-v1")
    ap.add_argument("--min-occ", type=int, default=3,
                    help="retrieval-floor NOVELs below this occurrence count are "
                         "left in the registry but not rendered as cards")
    args = ap.parse_args()

    reg = json.loads(Path(args.registry).read_text())
    all_entries = reg["proposals"]
    # Focus the queue on entries that need a human decision: everything the LLM or
    # deterministic stage actively judged, plus recurring floor-NOVELs (a proposal
    # seen >=min_occ times or across >1 chapter is a real FOLIO-gap candidate). The
    # long tail of single-mention floor-NOVELs stays in the registry file.
    def keep(e):
        j = e.get("judge") or {}
        if j.get("judged_by") != "claude-code:retrieval-floor":
            return True
        return e.get("occurrences", 0) >= args.min_occ or \
            len(set(e.get("provenance", {}).get("chapters", []))) > 1
    entries = [e for e in all_entries if keep(e)]
    hidden = len(all_entries) - len(entries)
    shown = len(entries)
    # order: survivors/novel first (need most attention), then merges, then dup/alias
    order = {"NOVEL": 0, None: 1, "NEEDS_WORK": 2, "MERGE_WITH": 3, "SYNONYM_OF": 4, "DUPLICATE_OF": 5}
    entries = sorted(entries, key=lambda e: (order.get((e.get("judge") or {}).get("verdict"), 9),
                                             -e.get("occurrences", 0), e["proposed_label"].lower()))

    from collections import Counter
    vc = Counter((e.get("judge") or {}).get("verdict") for e in entries)
    alias = sum(1 for e in entries if (e.get("judge") or {}).get("guardrail"))

    tiles = (
        f"<div class='tile'><div class='tnum'>{len(entries)}</div><div class='tlbl'>In this queue</div><div class='tsub'>of {len(all_entries):,} in registry</div></div>"
        f"<div class='tile' style='border-left:3px solid var(--nov)'><div class='tnum'>{vc.get('NOVEL',0)+vc.get(None,0)}</div><div class='tlbl'>Novel / survivors</div><div class='tsub'>need your eyes</div></div>"
        f"<div class='tile' style='border-left:3px solid var(--dup)'><div class='tnum'>{vc.get('DUPLICATE_OF',0)}</div><div class='tlbl'>Duplicate</div><div class='tsub'>{alias} alias-guarded</div></div>"
        f"<div class='tile' style='border-left:3px solid var(--syn)'><div class='tnum'>{vc.get('SYNONYM_OF',0)}</div><div class='tlbl'>Synonym</div><div class='tsub'>of a FOLIO concept</div></div>"
        f"<div class='tile' style='border-left:3px solid var(--mrg)'><div class='tnum'>{vc.get('MERGE_WITH',0)}</div><div class='tlbl'>Merge</div><div class='tsub'>proposal↔proposal</div></div>"
    )

    chips = (f"<button class='chip all' aria-pressed='true'>All <span class='ct' id='viscount'>{len(entries)}</span></button>")
    for v, lbl in [("NOVEL", "Novel"), ("none", "Survivor"), ("NEEDS_WORK", "Needs work"),
                   ("MERGE_WITH", "Merge"), ("SYNONYM_OF", "Synonym"), ("DUPLICATE_OF", "Duplicate")]:
        key = None if v == "none" else v
        n = vc.get(key, 0)
        chips += f"<button class='chip' data-v='{v}'>{lbl}<span class='ct'>{n}</span></button>"

    cards = "\n\n".join(render_card(e) for e in entries)

    body = f"""<div class="gq" id="gq-root">
  <header class="masthead">
    <div class="wrap" style="padding-top:28px;padding-bottom:22px">
      <p class="eyebrow">folio-insights · Proposed-Class Governance · human approval queue</p>
      <h1 class="mast-h">Proposed FOLIO classes — approval queue</h1>
      <p class="mast-sub">Every concept the pipeline surfaced that FOLIO has no home for, deduped
      deterministically and judged (definition-level) against the nearest existing concepts. Approve the
      genuinely novel ones into the ontology-extension backlog; reject the duplicates; merge the variants.
      The judge's recommendation is pre-selected — override freely. Choices save locally; Copy decisions
      pastes a stable-ID JSON back into the chat. This queue focuses on the {shown} entries that need a
      call — every judged dedup plus recurring novel proposals; the {hidden:,} single-mention floor-novels
      stay in the registry file for later.</p>
      <div class="metabar">
        <span><b>Registry:</b> {esc(Path(args.registry).name)}</span>
        <span><b>Judging:</b> deterministic + Claude-side ($0 app-side)</span>
        <span><b>Guardrail:</b> alias hits verify on definition (charge→Encumbrance lesson)</span>
      </div>
    </div>
  </header>
  <div class="wrap">
    <div class="tiles">{tiles}</div>
  </div>
  <div class="toolbar"><div class="wrap chips">{chips}</div></div>
  <div class="wrap"><div class="stream">
{cards}
  </div></div>
  <div class="actionbar">
    <div class="preview" id="preview"><textarea id="previewText" readonly aria-label="paste-back preview"></textarea></div>
    <div class="wrap">
      <span class="abtext"><b id="decided">0</b> decisions · <b id="noted">0</b> notes · saved to this browser</span>
      <span class="spacer"></span>
      <button class="act" id="previewBtn">Preview</button>
      <button class="act primary" id="copyBtn">Copy decisions</button>
    </div>
  </div>
</div>"""

    js = JS_TMPL.replace("__KEY__", args.key).replace("__REG__", esc(Path(args.registry).name))
    artifact = f"{body}\n<style>{CSS}</style>\n<script>{js}</script>"
    standalone = (f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">\n"
                  f"<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
                  f"<title>Proposed FOLIO classes — approval queue</title></head>"
                  f"<body style=\"margin:0\">\n{artifact}\n</body></html>")
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "approval-queue.html").write_text(standalone, encoding="utf-8")
    (outdir / "approval-queue.artifact.html").write_text(artifact, encoding="utf-8")
    print(json.dumps({"entries": len(entries), "verdicts": dict(vc), "alias_guarded": alias}))


if __name__ == "__main__":
    main()
