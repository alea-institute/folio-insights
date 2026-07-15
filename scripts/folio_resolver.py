"""Fast FOLIO OWL resolver: IRI -> {label, definition, english_labels}.

Streams the FOLIO.owl (RDF/XML) with a regex per-class scan (rdflib is too slow
for repeated use). Extracts rdfs:label, skos:definition, and the English-ish
surface forms (label + prefLabel + hiddenLabel + en* altLabels) used for
label-match scoring and alt-label-collision detection.
"""
from __future__ import annotations
import re, json, html
from functools import lru_cache
from pathlib import Path

_CLASS_RE = re.compile(
    r'<owl:Class rdf:about="(https://folio\.openlegalstandard\.org/[^"]+)">(.*?)</owl:Class>',
    re.DOTALL,
)
_LABEL_RE = re.compile(r'<rdfs:label(?:\s[^>]*)?>(.*?)</rdfs:label>', re.DOTALL)
_DEF_RE = re.compile(r'<skos:definition(?:\s[^>]*)?>(.*?)</skos:definition>', re.DOTALL)
_PREF_RE = re.compile(r'<skos:prefLabel(?:\s[^>]*)?>(.*?)</skos:prefLabel>', re.DOTALL)
_HID_RE = re.compile(r'<skos:hiddenLabel(?:\s[^>]*)?>(.*?)</skos:hiddenLabel>', re.DOTALL)
# altLabels: capture lang + value; keep English / no-lang ones
_ALT_RE = re.compile(
    r'<skos:altLabel(?:\s+xml:lang="([^"]*)")?[^>]*>(.*?)</skos:altLabel>', re.DOTALL)


def _clean(s: str) -> str:
    return html.unescape(re.sub(r'\s+', ' ', s)).strip()


def build_resolver(owl_path: str) -> dict:
    text = Path(owl_path).read_text(encoding="utf-8")
    out: dict[str, dict] = {}
    for m in _CLASS_RE.finditer(text):
        iri, body = m.group(1), m.group(2)
        lm = _LABEL_RE.search(body)
        label = _clean(lm.group(1)) if lm else ""
        dm = _DEF_RE.search(body)
        definition = _clean(dm.group(1)) if dm else ""
        eng = set()
        if label:
            eng.add(label)
        for r in (_PREF_RE, _HID_RE):
            for mm in r.finditer(body):
                eng.add(_clean(mm.group(1)))
        for lang, val in _ALT_RE.findall(body):
            if lang == "" or lang.lower().startswith("en"):
                eng.add(_clean(val))
        out[iri] = {
            "label": label,
            "definition": definition,
            "english_labels": sorted(x for x in eng if x),
        }
    return out


def load_or_build(owl_path: str, cache_path: str) -> dict:
    cp = Path(cache_path)
    if cp.exists() and cp.stat().st_mtime >= Path(owl_path).stat().st_mtime:
        return json.loads(cp.read_text())
    res = build_resolver(owl_path)
    cp.write_text(json.dumps(res))
    return res


if __name__ == "__main__":
    import sys
    owl, cache = sys.argv[1], sys.argv[2]
    r = load_or_build(owl, cache)
    print("concepts:", len(r))
    doj = r.get("https://folio.openlegalstandard.org/R0DB70442Cf8b73D9275F14a")
    print("DOJ label:", doj["label"])
    print("DOJ english_labels:", doj["english_labels"])
    print("DOJ def[:60]:", doj["definition"][:60])
