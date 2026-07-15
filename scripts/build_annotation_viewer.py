"""Build a FOLIO-annotation review viewer for one book chapter.

Reproduces the Ch01 "The Advocate" viewer (docs/evidence/books-ch01-annotations/)
for any chapter processed by the extraction + discovery pipeline. Reads the
chapter's discovery.json, resolves each FOLIO tag's canonical label / definition
/ English surface-forms from the cached FOLIO.owl, computes the same five issue-
class flags, and emits:

    pack.html            standalone, self-contained page (with <!doctype>)
    pack.artifact.html   body-only page for the Artifact tool (no doctype/head)
    manifest.json        compact sidecar for agent ingestion

Flag rules (documented, heuristic — new chapters have no hand-labelled gold):
  country_collision  tag.branch == "Governmental Body"
  altlabel_collision entity_ruler path AND surface == a NON-primary English label
                     of the concept (exact alias) AND far from the primary label
  advocacy_catchall  concept applied to >= CATCHALL_MIN distinct units (the single
                     most over-applied FOLIO node in the chapter)
  weak_match         llm path AND best English label-match < WEAK_LM
  proposed_only      unit with zero FOLIO-mapped (non-empty-IRI) tags

Style + interaction JS are lifted verbatim from the Ch01 reference pack so the
two viewers are visually identical; only the localStorage key + pack label change.

Usage:
  python scripts/build_annotation_viewer.py \
    --discovery output/uat_ta_ch02_v5/discovery.json \
    --owl ~/.folio/cache/github/<hash>.owl \
    --reference docs/evidence/books-ch01-annotations/pack.html \
    --out docs/evidence/books-ch02-annotations \
    --chapter 2 --title "Planning and Preparation" \
    --source-label "15_Ch02_Planning_and_Preparation (7th ed.)" \
    --run uat_ta_ch02_v5 --weighted 0.827 --key fiv-ch02-annot-v1 \
    [--spend output/uat_ta_ch02_v5/spend_report.json]
"""
from __future__ import annotations
import argparse, html, json, re, sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from rapidfuzz import fuzz  # noqa: E402

WEAK_LM = 60          # LLM label-match below this => weak_match (Ch01 convention)
ALTLABEL_PRIM_MAX = 70  # surface must be this far from primary label
CATCHALL_MIN = 30     # min distinct units for a concept to be a catch-all candidate

FLAG_META = {
    "country_collision": ("Country / Gov-body collision",
        "An everyday word matched a FOLIO governmental-body entity by exact alias "
        "(e.g. “justice”→U.S. Dept. of Justice)."),
    "altlabel_collision": ("FOLIO alt-label collision",
        "A common word is a legitimate alternative label of an unrelated FOLIO "
        "concept, so the deterministic ruler bound it (e.g. “charge”→Encumbrance)."),
    "advocacy_catchall": ("Over-applied catch-all node",
        "A single broad FOLIO node absorbs many distinct units — low-information, "
        "a candidate for splitting into child concepts."),
    "weak_match": ("Weak label match (LLM path)",
        "The LLM path mapped a surface to a FOLIO concept whose label string differs "
        "enough to score low — correct and wrong mappings both hide here."),
    "proposed_only": ("Proposed-class only (no FOLIO map)",
        "Every tag on this unit is a proposed new class — FOLIO has no concept, a "
        "coverage / ontology-extension signal rather than an error."),
}
FLAG_ORDER = ["country_collision", "altlabel_collision", "advocacy_catchall",
              "weak_match", "proposed_only"]
UTYPE_CLASS = {"principle": "t-principle", "pitfall": "t-pitfall",
               "procedural_rule": "t-procedural_rule"}


def esc(s: str) -> str:
    return html.escape(s or "", quote=True)


def lm_scores(surface: str, concept: dict):
    """(primary-label match, best English-label match) as 0-100 fuzz ratios."""
    s = surface.lower()
    prim = fuzz.ratio(s, concept["label"].lower()) if concept.get("label") else 0
    labs = concept.get("english_labels") or ([concept["label"]] if concept.get("label") else [])
    best = max((fuzz.ratio(s, l.lower()) for l in labs), default=0)
    return prim, best


def enrich(units, idx):
    """Attach resolved concept info + per-tag/per-unit flags. Mutates a copy."""
    # First pass: count concept -> distinct units (for catch-all detection),
    # plus the concept's branch and dominant extraction path (to describe it).
    concept_units = defaultdict(set)
    concept_branch = {}
    concept_paths = defaultdict(Counter)
    for u in units:
        for t in u["folio_tags"]:
            if t.get("iri") and t.get("label"):
                c = idx.get(t["iri"])
                if c and c["label"]:
                    concept_units[c["label"]].add(u["id"])
                    concept_branch.setdefault(c["label"], t.get("branch", ""))
                    concept_paths[c["label"]][t.get("extraction_path", "")] += 1
    catchall_concept, catchall_n = None, 0
    catchall_branch, catchall_path = "", ""
    if concept_units:
        top = max(concept_units.items(), key=lambda kv: len(kv[1]))
        if len(top[1]) >= CATCHALL_MIN:
            catchall_concept, catchall_n = top[0], len(top[1])
            catchall_branch = concept_branch.get(catchall_concept, "")
            paths = concept_paths.get(catchall_concept)
            catchall_path = paths.most_common(1)[0][0] if paths else ""

    out = []
    for u in units:
        tags = []
        uflags = set()
        for t in u["folio_tags"]:
            iri = t.get("iri") or ""
            surface = t.get("label", "")  # discovery stores the SURFACE in .label
            path = t.get("extraction_path", "")
            branch = t.get("branch", "")
            conf = t.get("confidence")
            tag = {"surface": surface, "iri": iri, "path": path, "branch": branch,
                   "confidence": conf, "flags": []}
            if path == "proposed_class" or not iri:
                tag["concept"] = None  # proposed new class
                tag["definition"] = ""
                tag["lm"] = None
                tags.append(tag)
                continue
            c = idx.get(iri, {"label": "", "definition": "", "english_labels": []})
            tag["concept"] = c["label"] or "(unresolved concept)"
            tag["definition"] = c["definition"]
            prim, best = lm_scores(surface, c)
            tag["lm"] = best
            engl = {l.lower() for l in (c.get("english_labels") or [])}
            # flags
            if branch == "Governmental Body":
                tag["flags"].append("country_collision")
            if (path == "entity_ruler" and c["label"]
                    and surface.lower() in engl
                    and surface.lower() != c["label"].lower()
                    and prim < ALTLABEL_PRIM_MAX):
                tag["flags"].append("altlabel_collision")
            if catchall_concept and c["label"] == catchall_concept:
                tag["flags"].append("advocacy_catchall")
            if path == "llm" and best < WEAK_LM:
                tag["flags"].append("weak_match")
            uflags.update(tag["flags"])
            tags.append(tag)
        mapped = [t for t in tags if t["iri"]]
        if not mapped and tags:
            uflags.add("proposed_only")
        out.append({**u, "_tags": tags, "_flags": sorted(uflags),
                    "_sev": len(uflags)})
    return out, {"concept": catchall_concept, "n": catchall_n,
                 "branch": catchall_branch, "path": catchall_path}


def highlight(snippet: str, tags) -> str:
    """Wrap the flagged surface terms in the snippet with <mark>."""
    if not snippet:
        return "<span class='nosnip'>(no source span)</span>"
    surf_flag = {}
    for t in tags:
        for f in t["flags"]:
            if f in ("country_collision", "altlabel_collision", "advocacy_catchall", "weak_match"):
                surf_flag.setdefault(t["surface"], f)
    esc_snip = esc(snippet)
    for surf, flag in sorted(surf_flag.items(), key=lambda x: -len(x[0])):
        if not surf:
            continue
        pat = re.compile(r"(?<![\w>])(" + re.escape(esc(surf)) + r")(?![\w<])", re.IGNORECASE)
        esc_snip = pat.sub(
            lambda m: f"<mark class='hl f-{flag}'>{m.group(1)}</mark>", esc_snip, count=1)
    return esc_snip


def render_tag(t) -> str:
    if t["concept"] is None:
        conf = "" if t["confidence"] is None else f"{t['confidence']:.2f}"
        return (
            "<div class='tag proposed'><div class='tagtop'>"
            f"<span class='surf'>{esc(t['surface'])}</span><span class='arrow'>→</span>"
            "<span class='concept prop'>proposed new class</span>"
            "<span class='pchip p-proposed_class'>proposed</span>"
            f"<span class=conf>{conf}</span></div><div class='tagmeta'></div></div>")
    pclass = {"entity_ruler": "p-entity_ruler", "llm": "p-llm",
              "heading_context": "p-llm"}.get(t["path"], "")
    plabel = {"entity_ruler": "deterministic", "llm": "LLM",
              "heading_context": "heading", "semantic": "semantic"}.get(t["path"], t["path"])
    conf = "" if t["confidence"] is None else f"{t['confidence']:.2f}"
    lm = "" if t["lm"] is None else f"<span class='lm' title='surface↔concept label-match'>lm {t['lm']:g}</span>"
    short_iri = t["iri"].rsplit("/", 1)[-1]
    badges = ""
    for f in t["flags"]:
        nm, desc = FLAG_META[f]
        badges += f"<span class='fbadge f-{f}' title='{esc(desc)}'>{esc(nm)}</span>"
    defn = f"<div class='def'>{esc(t['definition'])}</div>" if t["definition"] else ""
    return (
        f"<div class='tag'><div class='tagtop'>"
        f"<span class='surf'>{esc(t['surface'])}</span><span class='arrow'>→</span>"
        f"<span class='concept'>{esc(t['concept'])}</span>"
        f"<span class='pchip {pclass}'>{plabel}</span>"
        f"<span class='branch'>{esc(t['branch'])}</span>"
        f"<span class=conf>{conf}</span>{lm}</div>"
        f"<div class='tagmeta'><a class='iri' href='{esc(t['iri'])}' target='_blank' rel='noopener'>{esc(short_iri)}</a>{badges}</div>"
        f"{defn}</div>")


def render_unit(i, u) -> str:
    uid = u["id"]
    idx3 = f"{i:03d}"
    utype = u.get("unit_type", "")
    tclass = UTYPE_CLASS.get(utype, "")
    prim_flag = next((f for f in FLAG_ORDER if f in u["_flags"] and f != "proposed_only"),
                     u["_flags"][0] if u["_flags"] else None)
    unit_cls = f"s-f-{prim_flag}" if prim_flag and prim_flag != "proposed_only" else \
               ("s-f-proposed_only" if "proposed_only" in u["_flags"] else "s-clean")
    ministripe = (f"<span class='ministripe f-{prim_flag}' title='{esc(FLAG_META[prim_flag][0])}'></span>"
                  if prim_flag else "")
    anchor = ("<span class=\"anchor\" title=\"anchor score %.1f\">✓ anchored · %g</span>"
              % (u.get("anchor_score", 0), u.get("anchor_score", 0))) if u.get("anchor_verified") else \
             "<span class=\"anchor\" style=\"color:var(--crit)\">✗ unanchored</span>"
    uconf = ("<span class=\"uconf\" title=\"unit confidence\">conf %.2f</span>" % u["confidence"]) \
            if u.get("confidence") is not None else ""
    snippet = highlight(u.get("source_snippet", ""), u["_tags"])
    tags_html = "".join(render_tag(t) for t in u["_tags"]) or "<span class='nosnip'>(no tags)</span>"
    flags_attr = " ".join(u["_flags"]) if u["_flags"] else "clean"
    epid = f"EP-INSIGHTS-BOOKS-U{i:03d}"
    return f"""    <article class="unit {unit_cls}" data-flags="{flags_attr}" data-sev="{u['_sev']}" id="U{idx3}">
      <div class="unit-head">
        <span class="uidx">{idx3}</span>
        <span class="utype {tclass}">{esc(utype)}</span>
        {ministripe}
        {anchor}
        {uconf}
      </div>
      <div class="unit-body">
        <div class="src">
          <div class="col-lbl">Source span · the book's text</div>
          <p class="snippet">{snippet}</p>
        </div>
        <div class="ext">
          <div class="col-lbl">Extracted knowledge unit</div>
          <p class="etext">{esc(u.get('text',''))}</p>
          <div class="tags">{tags_html}</div>
          <div class="assess" data-uid="{uid}">
        <div class="assess-row">
          <span class="assess-lbl">Your call</span>
          <label class="rb"><input type="radio" name="v-{uid}" value="correct"><span>Correct</span></label>
          <label class="rb"><input type="radio" name="v-{uid}" value="weak"><span>Weak</span></label>
          <label class="rb"><input type="radio" name="v-{uid}" value="wrong"><span>Wrong</span></label>
          <span class="epid">{epid}</span>
        </div>
        <textarea class="note" data-uid="{uid}" placeholder="Notes on this unit… (saved locally)"></textarea>
      </div>
        </div>
      </div>
    </article>"""


def build_findings(stats, examples, catchall, total_units, total_prop_tags):
    """Return HTML for the five findings, adapted to this chapter's data."""
    catchall_concept, catchall_n = catchall["concept"], catchall["n"]
    ca_branch, ca_path = catchall.get("branch", ""), catchall.get("path", "")
    geo = ca_branch in ("Location", "Forums and Venues", "Governmental Body")
    via_heading = ca_path == "heading_context"

    def esc_ex(s): return esc(s)
    f = stats
    cc_ex = examples.get("country_collision")
    al_ex = examples.get("altlabel_collision")
    wm_ex = examples.get("weak_match")
    po_ex = examples.get("proposed_only")
    cc_txt = (f"<b>“{esc_ex(cc_ex[0])}”→{esc_ex(cc_ex[1])}</b>" if cc_ex else "—")
    al_txt = (f"<b>“{esc_ex(al_ex[0])}”</b> resolves to <b>{esc_ex(al_ex[1])}</b>" if al_ex else "—")
    wm_txt = (f"<b>{esc_ex(wm_ex[0])}→{esc_ex(wm_ex[1])}</b> (label-match {wm_ex[2]:g})" if wm_ex else "—")
    po_txt = ", ".join(f"<b>{esc_ex(x)}</b>" for x in examples.get("proposed_labels", [])[:4]) or "—"

    findings = [
        ("st-fail", "fail", "001", "country_collision",
         f"{f['country_collision_tags']} tags across {f['country_collision']} units",
         "Everyday words collide with FOLIO governmental-body entities",
         "The residual from BUG B9. Abstract words are matched to real U.S. government "
         "entities by exact-alias lookup, which the label verifier passes because the alias "
         f"genuinely belongs to the FOLIO concept. Worst offender here: {cc_txt}. These need "
         "definition-level (not label-level) disambiguation — the deterministic ruler path is "
         "equally exposed."),
        ("st-fail", "fail", "002", "altlabel_collision",
         f"{f['altlabel_collision']} units carry ≥1 alt-label collision",
         "Common words map to FOLIO alt-labels of unrelated concepts",
         "The canonical residual class named in the brief. Common trial-advocacy words are "
         "legitimate FOLIO <i>alternative labels</i> of unrelated concepts, so the "
         f"deterministic entity-ruler binds them confidently: {al_txt}. Because the surface "
         "truly is an alt-label, no label verification can reject it — an ontology-"
         "disambiguation gap, not a pipeline bug."),
        ("st-fail" if (catchall_concept and geo) else "st-borderline",
         "fail" if (catchall_concept and geo) else "borderline", "003", "advocacy_catchall",
         (f"{f['advocacy_catchall_tags']} tags → 1 node, across {f['advocacy_catchall']} units"
          if catchall_concept else "no dominant catch-all node this chapter"),
         (f"A mis-derived {esc(ca_branch)} node — “{esc(catchall_concept)}” — is propagated to {catchall_n} units"
          if (catchall_concept and geo) else
          f"One node — “{esc(catchall_concept)}” — absorbs {catchall_n} units"
          if catchall_concept else "No single node dominates this chapter"),
         ((f"A single geographic / venue concept (<i>“{esc(catchall_concept)}”</i>, branch "
           f"<b>{esc(ca_branch)}</b>) is attached to {catchall_n} distinct units"
           + (" — chiefly via the <b>heading-context</b> path, which maps a section heading to a "
              "FOLIO concept and then propagates it to every unit beneath that heading. When the "
              "heading term collides with a place name this becomes systemic noise (a US "
              "trial-advocacy planning chapter does not concern this locale). This four-path "
              "heading-context propagation is new since the Ch01-v5 output and is the largest "
              "single source of mismapping in this chapter." if via_heading else
              " — a homonym/collision, not a fair mapping. Worth definition-level disambiguation."))
          if (catchall_concept and geo) else
          f"A single over-broad node (<i>“{esc(catchall_concept)}”</i>) becomes a magnet for "
          "many distinct units. It is rarely <i>wrong</i>, but it is low-information: it flattens "
          "distinct ideas into one bucket and drags discoverability (RUB-12/13). Candidate for "
          "splitting into child concepts."
          if catchall_concept else
          "No FOLIO concept is applied to an outlier number of units in this chapter — the "
          "mapping spread is comparatively even.")),
        ("st-borderline", "borderline", "004", "weak_match",
         f"{f['weak_match']} units with a weak (&lt;{WEAK_LM}) LLM label match",
         "LLM-path mappings score low — correct and wrong both hide here",
         "The LLM path maps surface roles to FOLIO canonicals whose strings differ enough to "
         f"score low: e.g. {wm_txt}. Several are arguably <i>correct</i> — the label-match "
         "metric, not the mapping, is what's weak. But genuine errors live in the same band. "
         "This is the blind spot the label verifier cannot resolve; definition-level judging "
         "is required."),
        ("st-info", "info", "005", "proposed_only",
         f"{f['proposed_only']} of {total_units} units are proposed-only · {total_prop_tags} proposed tags total",
         f"{f['proposed_only']} units land entirely in proposed-class (FOLIO has no concept)",
         "Not errors — a coverage signal. Concepts like " + po_txt + " have no FOLIO match and "
         "are correctly demoted to proposed new classes rather than force-fit. Worth Damien's eyes "
         "as an ontology-extension backlog: this is where the chapter asks FOLIO to grow."),
    ]
    out = []
    for st, chip, num, flag, count, h3, body in findings:
        out.append(f"""    <div class="finding {st}" id="EP-{num}">
      <div class="fhead">
        <span class="fchip {st}">{chip}</span>
        <a class="fanchor" href="#EP-{num}">EP-INSIGHTS-BOOKS-ANNOT-{num}</a>
        <span class="fcount">{count}</span>
        <button class="jump" data-flag="{flag}">Filter stream →</button>
      </div>
      <h3>{h3}</h3>
      <p class="fbody">{body}</p>
      <textarea class="note fnote" data-uid="EP-{num}" placeholder="Your assessment of this issue… (saved locally)"></textarea>
    </div>""")
    return "\n".join(out)


def extract_css_js(reference: str):
    txt = Path(reference).read_text(encoding="utf-8")
    css = re.search(r"<style>(.*?)</style>", txt, re.DOTALL).group(1)
    js = re.search(r"<script>(.*?)</script>", txt, re.DOTALL).group(1)
    return css, js


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--discovery", required=True)
    ap.add_argument("--owl", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--chapter", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--source-label", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--weighted", type=float, required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--spend", default=None)
    args = ap.parse_args()

    from folio_resolver import load_or_build  # noqa
    idx_cache = str(Path(args.owl).with_suffix(".index.json"))
    idx = load_or_build(str(Path(args.owl).expanduser()), idx_cache)

    disc = json.loads(Path(args.discovery).read_text())
    # Accept either discovery.json (knowledge_units) or extraction.json (units);
    # the per-unit tag data the viewer needs is identical in both.
    units = disc.get("knowledge_units") or disc["units"]
    enriched, catchall = enrich(units, idx)
    catchall_concept, catchall_n = catchall["concept"], catchall["n"]

    # stats
    stats = {k: 0 for k in FLAG_ORDER}
    tag_counts = {"country_collision_tags": 0, "advocacy_catchall_tags": 0}
    path_counts = Counter()
    distinct_iris = set()
    total_tags = 0
    prop_tags = 0
    examples = {}
    prop_labels = []
    for u in enriched:
        for fl in u["_flags"]:
            stats[fl] += 1
        for t in u["_tags"]:
            total_tags += 1
            path_counts[t["path"]] += 1
            if t["iri"]:
                distinct_iris.add(t["iri"])
            if t["concept"] is None:
                prop_tags += 1
                prop_labels.append(t["surface"])
            if "country_collision" in t["flags"]:
                tag_counts["country_collision_tags"] += 1
                examples.setdefault("country_collision", (t["surface"], t["concept"]))
            if "advocacy_catchall" in t["flags"]:
                tag_counts["advocacy_catchall_tags"] += 1
            if "altlabel_collision" in t["flags"]:
                examples.setdefault("altlabel_collision", (t["surface"], t["concept"]))
            if "weak_match" in t["flags"]:
                examples.setdefault("weak_match", (t["surface"], t["concept"], t["lm"]))
    # proposed labels for finding 5: most common
    examples["proposed_labels"] = [w for w, _ in Counter(prop_labels).most_common(6)]

    fstats = dict(stats)
    fstats.update(tag_counts)
    total_units = len(enriched)
    anchored = sum(1 for u in enriched if u.get("anchor_verified"))

    css, js = extract_css_js(args.reference)
    js = js.replace("fiv-ch01-annot-v1", args.key)
    js = js.replace("EP-INSIGHTS-BOOKS-ANNOT (Ch01 The Advocate, v5, rubric extraction-quality-v1.0)",
                    f"EP-INSIGHTS-BOOKS-ANNOT (Ch{int(args.chapter):02d} {args.title}, {args.run}, rubric extraction-quality-v1.0)")

    spend_txt = "$0 (built from existing output)"
    if args.spend and Path(args.spend).exists():
        sp = json.loads(Path(args.spend).read_text())
        pre = "~" if sp.get("derived") else ""
        note = f" — {sp['derived']}" if isinstance(sp.get("derived"), str) else ""
        spend_txt = (f"{pre}${sp['estimated_cost_usd']:.3f} app-side "
                     f"({sp['llm_calls']:,} LLM calls, {sp['total_tokens']:,} tokens, "
                     f"{sp['price_model']}){note}")

    findings_html = build_findings(fstats, examples, catchall,
                                   total_units, prop_tags)

    chips = (f"<button class=\"chip all\" aria-pressed=\"true\">All units "
             f"<span class=\"ct\" id=\"viscount\">{total_units}</span></button>")
    for fl in FLAG_ORDER:
        chips += (f"<button class='chip f-{fl}' data-flag='{fl}'><span class='dot'></span>"
                  f"{esc(FLAG_META[fl][0])}<span class='ct'>{stats[fl]}</span></button>")

    tiles = (
        f"<div class='tile'><div class='tnum'>{total_units}</div><div class='tlbl'>Knowledge units</div>"
        f"<div class='tsub'>extracted from Ch{int(args.chapter):02d}</div></div>"
        f"<div class='tile'><div class='tnum'>{total_tags:,}</div><div class='tlbl'>FOLIO tags</div>"
        f"<div class='tsub'>{path_counts['entity_ruler']} determ · {path_counts['llm']} LLM"
        + (f" · {path_counts['heading_context']} heading" if path_counts.get('heading_context') else "")
        + f" · {path_counts['proposed_class']} proposed</div></div>"
        f"<div class='tile'><div class='tnum'>{len(distinct_iris)}</div><div class='tlbl'>Distinct concepts</div>"
        f"<div class='tsub'>unique FOLIO IRIs used</div></div>"
        f"<div class='tile'><div class='tnum'>{anchored}/{total_units}</div><div class='tlbl'>Anchor gate</div>"
        f"<div class='tsub'>units source-verified</div></div>")

    stream = "\n\n".join(render_unit(i + 1, u) for i, u in enumerate(enriched))

    ch = int(args.chapter)
    body = f"""<div class="fiv" id="fiv-root">
  <header class="masthead">
    <div class="wrap" style="padding-top:30px;padding-bottom:24px">
      <p class="eyebrow">folio-insights · Book Extraction UAT · chapter annotation</p>
      <h1 class="mast-h">Chapter {ch} — <span style="color:var(--accent2)">{esc(args.title)}</span><br>FOLIO annotation review</h1>
      <p class="mast-sub">Every knowledge unit the pipeline pulled from this chapter of the
      trial-advocacy treatise, shown against the book's own source text with its FOLIO concept mapping,
      definition, and provenance — so the residual mapping problems are findable before any full-book spend.</p>
      <div class="metabar">
        <span><b>Chapter:</b> {esc(args.source_label)}</span>
        <span><b>Run:</b> {esc(args.run)}</span>
        <span><b>Rubric:</b> extraction-quality-v1.0 — v5 pipeline (post-B9)</span>
        <span><b>App-side spend:</b> {esc(spend_txt)}</span>
      </div>
    </div>
  </header>

  <div class="wrap pad">
    <div class="tiles">{tiles}</div>
  </div>

  <div class="wrap">
    <p class="section-lbl">Issues most worth your eyes</p>
    <div class="findings">
{findings_html}</div>
  </div>

  <div class="wrap" style="margin-top:34px" id="stream-top">
    <p class="section-lbl">The annotated chapter — <span style="text-transform:none;letter-spacing:0;color:var(--ink2)">{total_units} units in document order</span></p>
  </div>
  <div class="toolbar">
    <div class="wrap chips">
      {chips}
    </div>
  </div>
  <div class="wrap">
    <div class="stream">
{stream}</div>
  </div>

  <div class="actionbar">
    <div class="preview" id="preview"><textarea id="previewText" readonly aria-label="paste-back preview"></textarea></div>
    <div class="wrap">
      <span class="abtext"><b id="assessed">0</b> verdicts · <b id="noted">0</b> notes · saved to this browser</span>
      <span class="spacer"></span>
      <button class="act" id="previewBtn">Preview</button>
      <button class="act primary" id="copyBtn">Copy answers</button>
    </div>
  </div>
</div>"""

    title = f"Ch{ch:02d} {args.title} — FOLIO annotation review"
    artifact_html = f"{body}\n<style>{css}</style>\n<script>{js}</script>"
    standalone = (f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">\n"
                  f"<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
                  f"<title>{esc(title)}</title></head><body style=\"margin:0\">\n\n"
                  f"{artifact_html}\n</body></html>")

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "pack.html").write_text(standalone, encoding="utf-8")
    (outdir / "pack.artifact.html").write_text(artifact_html, encoding="utf-8")

    # manifest sidecar
    manifest = {
        "pack": "EP-INSIGHTS-BOOKS-ANNOT",
        "title": title, "run": args.run, "rubric": "extraction-quality-v1.0",
        "app_side_spend": spend_txt,
        "meta": {
            "total_units": total_units, "total_tags": total_tags,
            "path_counts": dict(path_counts), "distinct_iris": len(distinct_iris),
            "anchor_verified": anchored, "flag_counts": dict(stats),
            "catchall_concept": catchall_concept, "catchall_units": catchall_n,
            **tag_counts,
        },
        "units": [{
            "id": u["id"], "epid": f"EP-INSIGHTS-BOOKS-U{i+1:03d}",
            "span": [u.get("original_span", {}).get("start"), u.get("original_span", {}).get("end")],
            "unit_type": u.get("unit_type"), "flags": u["_flags"],
            "tags": [{"surface": t["surface"], "iri": t["iri"], "concept": t["concept"],
                      "branch": t["branch"], "path": t["path"], "lm": t["lm"],
                      "flags": t["flags"]} for t in u["_tags"]],
        } for i, u in enumerate(enriched)],
    }
    (outdir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(json.dumps({"out": str(outdir), "units": total_units, "tags": total_tags,
                      "flags": dict(stats), "catchall": [catchall_concept, catchall_n],
                      "distinct_iris": len(distinct_iris)}, indent=2))


if __name__ == "__main__":
    main()
