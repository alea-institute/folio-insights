"""FOLIO label lexicon for deterministic proposal dedupe.

Two indexes:

* ``by_iri``: IRI -> ``{label, definition, english_labels}``;
* ``by_norm``: normalized label -> ``[(iri, primary label, form)]`` across
  every label form.

``form`` is ``primary`` (``rdfs:label``), ``pref``, ``alt`` or ``hidden``. Dedupe
treats only a ``primary`` hit as a duplicate. Any other form is an alias, and
an alias hit stays a distinct proposal for definition-level review. A label
collision can join semantically unrelated concepts: the historical case was the
proposal "charge" against the FOLIO concept "Encumbrance".

Stdlib only. The OWL scan is a regex pass over RDF/XML; rdflib is too slow to
re-parse FOLIO on every run.
"""
from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from folio_insights.proposals.registry import normalize_label

_CLASS_RE = re.compile(
    r'<owl:Class rdf:about="(https://folio\.openlegalstandard\.org/[^"]+)">(.*?)</owl:Class>',
    re.DOTALL,
)
_LABEL_RE = re.compile(r"<rdfs:label(?:\s[^>]*)?>(.*?)</rdfs:label>", re.DOTALL)
_DEF_RE = re.compile(r"<skos:definition(?:\s[^>]*)?>(.*?)</skos:definition>", re.DOTALL)
_PREF_RE = re.compile(r"<skos:prefLabel(?:\s[^>]*)?>(.*?)</skos:prefLabel>", re.DOTALL)
_HID_RE = re.compile(r"<skos:hiddenLabel(?:\s[^>]*)?>(.*?)</skos:hiddenLabel>", re.DOTALL)
_ALT_RE = re.compile(
    r'<skos:altLabel(?:\s+xml:lang="([^"]*)")?[^>]*>(.*?)</skos:altLabel>', re.DOTALL
)

PRIMARY = "primary"
LABEL_FORMS = (PRIMARY, "pref", "alt", "hidden")


def _clean(s: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", s)).strip()


class FolioLexicon:
    """Normalized-label index over FOLIO concepts."""

    def __init__(
        self,
        by_iri: Mapping[str, Mapping[str, Any]],
        by_norm: Mapping[str, Iterable[tuple[str, str, str]]],
    ) -> None:
        self.by_iri: dict[str, dict[str, Any]] = {k: dict(v) for k, v in by_iri.items()}
        self.by_norm: dict[str, list[tuple[str, str, str]]] = {
            k: [tuple(x) for x in v] for k, v in by_norm.items()  # type: ignore[misc]
        }

    def lookup(self, label: str) -> list[tuple[str, str, str]]:
        """Every ``(iri, primary label, form)`` whose normalized form matches."""
        return list(self.by_norm.get(normalize_label(label), []))

    def primary_labels(self) -> dict[str, tuple[str, str]]:
        """normalized primary label -> ``(iri, label)`` (first IRI wins, sorted)."""
        out: dict[str, tuple[str, str]] = {}
        for norm in sorted(self.by_norm):
            for iri, label, form in sorted(self.by_norm[norm]):
                if form == PRIMARY:
                    out.setdefault(norm, (iri, label))
        return out

    def definition(self, iri: str) -> str:
        return str(self.by_iri.get(iri, {}).get("definition", ""))

    # ---- constructors -------------------------------------------------

    @classmethod
    def from_concepts(cls, concepts: Iterable[Mapping[str, Any]]) -> FolioLexicon:
        """Build from ``{iri, label, definition?, pref?, alt?, hidden?}`` records
        (the alias fields are lists of strings). Used by tests and callers that
        already hold concepts in memory."""
        by_iri: dict[str, dict[str, Any]] = {}
        by_norm: dict[str, list[tuple[str, str, str]]] = {}
        for c in concepts:
            iri, label = str(c["iri"]), str(c.get("label", ""))
            english: set[str] = set()
            forms: list[tuple[str, str]] = [(label, PRIMARY)] if label else []
            for form in ("pref", "alt", "hidden"):
                forms += [(str(v), form) for v in c.get(form, []) or []]
            for surface, form in forms:
                english.add(surface)
                norm = normalize_label(surface)
                if norm:
                    by_norm.setdefault(norm, []).append((iri, label, form))
            by_iri[iri] = {
                "label": label,
                "definition": str(c.get("definition", "")),
                "english_labels": sorted(x for x in english if x),
            }
        return cls(by_iri, by_norm)

    @classmethod
    def from_owl(cls, owl_path: str | Path) -> FolioLexicon:
        text = Path(owl_path).expanduser().read_text(encoding="utf-8")
        concepts = []
        for m in _CLASS_RE.finditer(text):
            iri, body = m.group(1), m.group(2)
            lm = _LABEL_RE.search(body)
            dm = _DEF_RE.search(body)
            concepts.append({
                "iri": iri,
                "label": _clean(lm.group(1)) if lm else "",
                "definition": _clean(dm.group(1)) if dm else "",
                "pref": [_clean(x) for x in _PREF_RE.findall(body)],
                "hidden": [_clean(x) for x in _HID_RE.findall(body)],
                "alt": [
                    _clean(val)
                    for lang, val in _ALT_RE.findall(body)
                    if lang == "" or lang.lower().startswith("en")
                ],
            })
        return cls.from_concepts(concepts)

    @classmethod
    def from_json(cls, path: str | Path) -> FolioLexicon:
        """Load the ``{by_iri, by_norm}`` cache format."""
        data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
        return cls(data["by_iri"], data["by_norm"])

    def to_json(self, path: str | Path) -> None:
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps({"by_iri": self.by_iri, "by_norm": self.by_norm}, sort_keys=True),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> FolioLexicon:
        """A FOLIO ``.owl`` file, or a JSON cache written by ``to_json``."""
        p = Path(path).expanduser()
        return cls.from_json(p) if p.suffix.lower() == ".json" else cls.from_owl(p)


__all__ = ["LABEL_FORMS", "PRIMARY", "FolioLexicon"]
