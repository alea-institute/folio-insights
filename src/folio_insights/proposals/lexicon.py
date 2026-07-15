"""FOLIO label lexicon for deterministic dedupe.

Parses the cached FOLIO.owl once into two structures:
  - ``by_iri``:   iri -> {label, definition, english_labels}
  - ``by_norm``:  normalized-label -> [(iri, label, form)]  (all label forms)

``form`` is one of pref/alt/hidden/primary so the dedupe stage can tell a
primary-label hit from an alias hit (the ``charge→Encumbrance`` lesson: an alias
hit is a *candidate* duplicate, still overridable by a human on definition).

No third-party deps beyond the stdlib; the regex scan mirrors
``scripts/folio_resolver.py`` but also emits the normalized-label index.
"""
from __future__ import annotations
import html
import json
import re
from pathlib import Path

_CLASS_RE = re.compile(
    r'<owl:Class rdf:about="(https://folio\.openlegalstandard\.org/[^"]+)">(.*?)</owl:Class>',
    re.DOTALL,
)
_LABEL_RE = re.compile(r'<rdfs:label(?:\s[^>]*)?>(.*?)</rdfs:label>', re.DOTALL)
_DEF_RE = re.compile(r'<skos:definition(?:\s[^>]*)?>(.*?)</skos:definition>', re.DOTALL)
_PREF_RE = re.compile(r'<skos:prefLabel(?:\s[^>]*)?>(.*?)</skos:prefLabel>', re.DOTALL)
_HID_RE = re.compile(r'<skos:hiddenLabel(?:\s[^>]*)?>(.*?)</skos:hiddenLabel>', re.DOTALL)
_ALT_RE = re.compile(
    r'<skos:altLabel(?:\s+xml:lang="([^"]*)")?[^>]*>(.*?)</skos:altLabel>', re.DOTALL)

_NORM_RE = re.compile(r"[^a-z0-9]+")


def normalize(s: str) -> str:
    return _NORM_RE.sub(" ", (s or "").lower()).strip()


def _clean(s: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", s)).strip()


class FolioLexicon:
    def __init__(self, by_iri: dict, by_norm: dict):
        self.by_iri = by_iri
        self.by_norm = by_norm

    def lookup(self, label: str):
        """Return list of (iri, label, form) whose normalized label matches."""
        return self.by_norm.get(normalize(label), [])

    @classmethod
    def from_owl(cls, owl_path: str) -> "FolioLexicon":
        text = Path(owl_path).expanduser().read_text(encoding="utf-8")
        by_iri: dict[str, dict] = {}
        by_norm: dict[str, list] = {}

        def add(norm: str, iri: str, label: str, form: str):
            if not norm:
                return
            by_norm.setdefault(norm, []).append((iri, label, form))

        for m in _CLASS_RE.finditer(text):
            iri, body = m.group(1), m.group(2)
            lm = _LABEL_RE.search(body)
            label = _clean(lm.group(1)) if lm else ""
            dm = _DEF_RE.search(body)
            definition = _clean(dm.group(1)) if dm else ""
            english = set()
            if label:
                english.add(label)
                add(normalize(label), iri, label, "primary")
            for r, form in ((_PREF_RE, "pref"), (_HID_RE, "hidden")):
                for mm in r.finditer(body):
                    v = _clean(mm.group(1))
                    english.add(v)
                    add(normalize(v), iri, label, form)
            for lang, val in _ALT_RE.findall(body):
                if lang == "" or lang.lower().startswith("en"):
                    v = _clean(val)
                    english.add(v)
                    add(normalize(v), iri, label, "alt")
            by_iri[iri] = {
                "label": label, "definition": definition,
                "english_labels": sorted(x for x in english if x),
            }
        return cls(by_iri, by_norm)

    @classmethod
    def load_or_build(cls, owl_path: str, cache_path: str) -> "FolioLexicon":
        owl = Path(owl_path).expanduser()
        cp = Path(cache_path)
        if cp.exists() and cp.stat().st_mtime >= owl.stat().st_mtime:
            data = json.loads(cp.read_text())
            by_norm = {k: [tuple(x) for x in v] for k, v in data["by_norm"].items()}
            return cls(data["by_iri"], by_norm)
        lex = cls.from_owl(str(owl))
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps({"by_iri": lex.by_iri, "by_norm": lex.by_norm}))
        return lex
