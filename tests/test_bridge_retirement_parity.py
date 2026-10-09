"""Parity tests for the in-repo replacements of the retired folio-enrich sys.path bridges.

Two kinds of tests (see docs/bridge-retirement-2026-10-09.md):

* ``@pytest.mark.integration`` parity tests import folio-enrich's ORIGINAL code through
  the existing path helper (``_ensure_folio_enrich_path``) and assert the vendored
  implementation produces the same outputs. They skip when the checkout is absent.
* Non-integration golden / contract tests freeze the outputs observed in that
  comparison so the behavior stays pinned without a folio-enrich checkout.
"""

from __future__ import annotations

import asyncio
import dataclasses
import sys
import types

import pytest

# ---------------------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def enrich():
    """Make folio-enrich's backend importable, or skip when the checkout is absent."""
    from folio_insights.services.bridge.folio_bridge import _ensure_folio_enrich_path

    try:
        _ensure_folio_enrich_path()
    except FileNotFoundError as exc:
        pytest.skip(f"folio-enrich checkout absent: {exc.args[0].splitlines()[0]}")
    return True


NORMALIZER_TEXTS: dict[str, str] = {
    "legal_prose": (
        "Plaintiff sued under 42 U.S.C. § 1983. The court applied Fed. R. Civ. P. 26(b)(1) "
        "to limit discovery. See Smith v. Jones, 123 F.3d 456 (9th Cir. 1999). Counsel objected."
    ),
    "abbreviations": (
        "Mr. Smith met Dr. Jones at 9 a.m. on Jan. 5. The U.S. Supreme Court denied cert. "
        "Acme Corp., Inc. appealed. It lost."
    ),
    "lists": (
        "Prepare the witness:\n1. Review the documents.\n2. Rehearse direct examination.\n"
        "- Never guess. Always ask for clarification."
    ),
    "unicode": (
        "The café’s résumé was “impeccable” … Ñandú testified. Next, the jury deliberated "
        "— briefly! Was it fair? Perhaps."
    ),
    "questions": (
        "Did the court err? Yes! It did. why? because the record was incomplete. Reversed."
    ),
}

LONG_TEXT = " ".join(
    f"Sentence number {i} explains a rule of evidence under Fed. R. Evid. {400 + i}."
    for i in range(120)
)
MESSY_TEXT = "  Line one   has\tspaces.\n\n\n\nLine  two .  \n   Line three.  "

# Frozen from the enrich-vs-vendored comparison (2026-10-09, enrich origin/main 510a652,
# NuPunkt not installed -> regex splitter, in both implementations).
GOLDEN_SENTENCES: dict[str, list[str]] = {
    "legal_prose": [
        "Plaintiff sued under 42 U.S.C. § 1983.",
        "The court applied Fed.",
        "R.",
        "Civ.",
        "P. 26(b)(1) to limit discovery.",
        "See Smith v.",
        "Jones, 123 F.3d 456 (9th Cir. 1999).",
        "Counsel objected.",
    ],
    "abbreviations": [
        "Mr.",
        "Smith met Dr.",
        "Jones at 9 a.m. on Jan. 5.",
        "The U.S.",
        "Supreme Court denied cert.",
        "Acme Corp., Inc. appealed.",
        "It lost.",
    ],
    "lists": [
        "Prepare the witness:\n1.",
        "Review the documents.\n2.",
        "Rehearse direct examination.\n- Never guess.",
        "Always ask for clarification.",
    ],
    "unicode": [
        "The café’s résumé was “impeccable” … Ñandú testified.",
        "Next, the jury deliberated — briefly!",
        "Was it fair?",
        "Perhaps.",
    ],
    "questions": [
        "Did the court err?",
        "Yes!",
        "It did. why? because the record was incomplete.",
        "Reversed.",
    ],
}
GOLDEN_LONG_CHUNKS = [(0, 2999, 0, 2999), (2855, 5820, 1, 2965), (5662, 8647, 2, 2985)]
GOLDEN_MESSY = (
    "Line one has spaces.\n\nLine two .\nLine three.",
    [["Line one has spaces.", "Line two .", "Line three."]],
)


def _nupunkt_installed() -> bool:
    try:
        import nupunkt  # noqa: F401
    except ImportError:
        return False
    return True


# ---------------------------------------------------------------------------------------
# 1. Normalizer
# ---------------------------------------------------------------------------------------


@pytest.mark.skipif(_nupunkt_installed(), reason="golden values were frozen with the regex splitter")
def test_normalizer_golden_sentences():
    from folio_insights.services.text_normalization import split_sentences

    for key, text in NORMALIZER_TEXTS.items():
        assert split_sentences(text) == GOLDEN_SENTENCES[key], key


@pytest.mark.skipif(_nupunkt_installed(), reason="golden values were frozen with the regex splitter")
def test_normalizer_golden_chunks_and_whitespace():
    from folio_insights.services.text_normalization import chunk_text, normalize_and_chunk

    chunks = chunk_text(LONG_TEXT)
    got = [(c.start_offset, c.end_offset, c.chunk_index, len(c.text)) for c in chunks]
    assert got == GOLDEN_LONG_CHUNKS
    # Overlap: the second chunk starts inside the first one (overlap budget 200 chars).
    assert chunks[1].start_offset < chunks[0].end_offset

    ct = normalize_and_chunk(MESSY_TEXT)
    assert (ct.full_text, [c.sentences for c in ct.chunks]) == GOLDEN_MESSY
    assert ct.source_format.value == "plain_text"


def test_get_normalizer_returns_in_repo_functions_without_sys_path(monkeypatch, tmp_path):
    from folio_insights.config import get_settings
    from folio_insights.services import text_normalization
    from folio_insights.services.bridge.folio_bridge import get_normalizer

    monkeypatch.setattr(get_settings(), "folio_enrich_path", tmp_path / "absent")
    before = list(sys.path)
    normalizer = get_normalizer()
    assert sys.path == before
    assert normalizer == {
        "split_sentences": text_normalization.split_sentences,
        "chunk_text": text_normalization.chunk_text,
        "normalize_and_chunk": text_normalization.normalize_and_chunk,
    }


@pytest.mark.integration
def test_normalizer_parity_with_enrich(enrich):
    from app.models.document import DocumentFormat as EnrichFormat
    from app.services.normalization import normalizer as en

    from folio_insights.services import text_normalization as vn

    texts = [*NORMALIZER_TEXTS.values(), LONG_TEXT, MESSY_TEXT, "", "No terminal punctuation"]
    assert len(texts) >= 5
    for text in texts:
        assert vn.split_sentences(text) == en.split_sentences(text), text[:40]
        assert vn.normalize_whitespace(text) == en.normalize_whitespace(text)
        assert [c.model_dump() for c in vn.chunk_text(text)] == [
            c.model_dump() for c in en.chunk_text(text)
        ]
        for max_chars, overlap in ((200, 50), (80, 0), (1000, 400)):
            assert [c.model_dump() for c in vn.chunk_text(text, max_chars, overlap)] == [
                c.model_dump() for c in en.chunk_text(text, max_chars, overlap)
            ]
        v, e = vn.normalize_and_chunk(text), en.normalize_and_chunk(text)
        assert v.full_text == e.full_text
        assert [c.model_dump() for c in v.chunks] == [c.model_dump() for c in e.chunks]
        assert v.source_format.value == e.source_format.value == EnrichFormat.PLAIN_TEXT.value


# ---------------------------------------------------------------------------------------
# 2. CitationExtractor
# ---------------------------------------------------------------------------------------

CITATION_TEXTS = [
    "See Brown v. Board of Education, 347 U.S. 483 (1954).",
    "Under 42 U.S.C. § 1983, a plaintiff must show state action. Id. at 485.",
    "Counsel should always prepare the witness before a deposition.",
    "Smith, 123 F.3d at 460; see also Jones v. Doe, 99 F. Supp. 2d 1 (D. Mass. 2000).",
    "The café’s résumé cites 5 Harv. L. Rev. 193 (1890) — supra note 3.",
]


class _FakeToken:
    def __init__(self, start: int, end: int) -> None:
        self.start, self.end = start, end


def _make_fake_eyecite():
    """A stand-in ``eyecite`` module: finds the literal 'U.S.' reporter cites by regex.

    Lets the extraction/mapping logic of both implementations be compared without the
    real library (which is not a folio-insights dependency)."""
    import re

    class FullCaseCitation:
        def __init__(self, text, start, end):
            self._text, self.token = text, _FakeToken(start, end)

        def matched_text(self):
            return self._text

        def corrected_citation_full(self):
            return self._text.replace("  ", " ") + " [normalized]"

    class IdCitation:
        def __init__(self, text, start, end):
            self._text, self.token = text, _FakeToken(start, end)

        def matched_text(self):
            return self._text

        def corrected_citation(self):
            return self._text

    def get_citations(text):
        out = []
        for m in re.finditer(r"\d+ (?:U\.S\.|F\.3d|F\. Supp\. 2d|Harv\. L\. Rev\.) \d+", text):
            out.append(FullCaseCitation(m.group(0), m.start(), m.end()))
        for m in re.finditer(r"\bId\.", text):
            out.append(IdCitation(m.group(0), m.start(), m.end()))
        return out

    return types.SimpleNamespace(get_citations=get_citations)


def _dump_citations(individuals) -> list[dict]:
    """Model dump minus the random uuid ``id`` (and enrich's extra ``feedback`` list)."""
    out = []
    for ind in individuals:
        d = ind.model_dump()
        d.pop("id", None)
        d.pop("feedback", None)
        out.append(d)
    return out


def _run(coro):
    return asyncio.run(coro)


def test_citation_extractor_without_libraries_returns_nothing(monkeypatch):
    """Today's behavior: eyecite/citeurl are not installed, so no citations are found."""
    from folio_insights.services.citation_extraction import CitationExtractor

    monkeypatch.setitem(sys.modules, "eyecite", None)  # import -> ImportError
    monkeypatch.setitem(sys.modules, "citeurl", None)
    for text in CITATION_TEXTS:
        assert _run(CitationExtractor().extract(text)) == []


def test_citation_extractor_golden_with_stub_eyecite(monkeypatch):
    from folio_insights.services.citation_extraction import CitationExtractor

    monkeypatch.setitem(sys.modules, "eyecite", _make_fake_eyecite())
    monkeypatch.setitem(sys.modules, "citeurl", None)
    got = _dump_citations(_run(CitationExtractor().extract(CITATION_TEXTS[1])))
    assert got == [
        {
            "name": "Id.",
            "mention_text": "Id.",
            "individual_type": "legal_citation",
            "span": {"start": 60, "end": 63, "text": "Id.", "sentence_text": None},
            "class_links": [
                {
                    "annotation_id": None,
                    "folio_iri": None,
                    "folio_label": "Caselaw",
                    "branch": "",
                    "relationship": "instance_of",
                    "confidence": 0.92,
                }
            ],
            "confidence": 0.92,
            "source": "eyecite",
            "normalized_form": None,
            "url": None,
            "lineage": [
                {
                    "stage": "individual_extraction",
                    "action": "created",
                    "detail": "eyecite: IdCitation",
                    "confidence": 0.92,
                    "timestamp": "",
                    "reasoning": "",
                }
            ],
        }
    ]
    got0 = _dump_citations(_run(CitationExtractor().extract(CITATION_TEXTS[0])))
    assert [(c["mention_text"], c["normalized_form"], c["class_links"][0]["folio_label"])
            for c in got0] == [("347 U.S. 483", "347 U.S. 483 [normalized]", "Caselaw")]


def test_citation_detection_skipped_and_logged_once_without_backends(monkeypatch, caplog):
    """No eyecite/citeurl: the classifier never builds the extractor and logs the reason once."""
    import logging

    from folio_insights.models.knowledge_unit import KnowledgeType, KnowledgeUnit, Span
    from folio_insights.pipeline.stages.knowledge_classifier import KnowledgeClassifierStage
    from folio_insights.services import citation_extraction
    from folio_insights.services.bridge import folio_bridge

    real_find_spec = citation_extraction.importlib.util.find_spec
    monkeypatch.setattr(
        citation_extraction.importlib.util,
        "find_spec",
        lambda name, *a, **k: None if name in ("eyecite", "citeurl") else real_find_spec(name),
    )
    citation_extraction.citation_backends_available.cache_clear()

    def _must_not_build():
        raise AssertionError("extractor built although no citation backend is installed")

    monkeypatch.setattr(folio_bridge, "get_citation_extractor", _must_not_build)
    units = [
        KnowledgeUnit(
            text="See 347 U.S. 483.",
            original_span=Span(start=0, end=17, source_file="x"),
            unit_type=KnowledgeType.ADVICE,
            source_file="x",
        )
        for _ in range(5)
    ]
    stage = KnowledgeClassifierStage()
    try:
        with caplog.at_level(logging.INFO, logger="folio_insights"):
            _run(stage._detect_citations(units))
            _run(stage._detect_citations(units))
        assert citation_extraction.citation_backends_available() == (False, False)
        assert sum("citation detection is disabled" in r.message for r in caplog.records) == 1
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert all(u.unit_type == KnowledgeType.ADVICE for u in units)
    finally:
        citation_extraction.citation_backends_available.cache_clear()


def test_get_citation_extractor_returns_in_repo_class(monkeypatch, tmp_path):
    from folio_insights.config import get_settings
    from folio_insights.services.bridge.folio_bridge import get_citation_extractor
    from folio_insights.services.citation_extraction import CitationExtractor

    monkeypatch.setattr(get_settings(), "folio_enrich_path", tmp_path / "absent")
    before = list(sys.path)
    assert get_citation_extractor() is CitationExtractor
    assert sys.path == before


@pytest.mark.integration
@pytest.mark.parametrize("eyecite_mode", ["absent", "stub", "real"])
def test_citation_extractor_parity_with_enrich(enrich, monkeypatch, eyecite_mode):
    from app.services.individual.citation_extractor import CitationExtractor as EnrichExtractor

    from folio_insights.services.citation_extraction import CitationExtractor

    if eyecite_mode == "absent":
        monkeypatch.setitem(sys.modules, "eyecite", None)
        monkeypatch.setitem(sys.modules, "citeurl", None)
    elif eyecite_mode == "stub":
        monkeypatch.setitem(sys.modules, "eyecite", _make_fake_eyecite())
        monkeypatch.setitem(sys.modules, "citeurl", None)
    else:
        pytest.importorskip("eyecite")

    found = 0
    for text in CITATION_TEXTS:
        v = _dump_citations(_run(CitationExtractor().extract(text)))
        e = _dump_citations(_run(EnrichExtractor().extract(text)))
        assert v == e, text
        found += len(v)
    if eyecite_mode != "absent":
        assert found > 0


# ---------------------------------------------------------------------------------------
# 3. FolioService
# ---------------------------------------------------------------------------------------

FOLIO_PROBE_LABELS = [
    "deposition", "Deposition Practice", "motion to dismiss", "summary judgment",
    "contract", "Agreement", "tort", "negligence", "statute of limitations", "appeal",
    "trial", "jury", "witness", "evidence", "hearsay", "cross-examination",
    "discovery", "interrogatories", "subpoena", "settlement", "mediation",
    "arbitration", "litigation", "plaintiff", "defendant", "attorney", "judge",
    "court", "complaint", "damages", "injunction", "pleadings", "class action",
    "Minnesota", "patent", "trademark", "employment law", "real estate",
    "criminal law", "bankruptcy",
]


@pytest.fixture(scope="module")
def folio_pair(enrich, tmp_path_factory):
    """(vendored, enrich) services, both loaded from folio-python's local OWL cache.

    The vendored service gets an empty, insights-owned lemma cache dir; enrich's registry
    singleton uses enrich's own lemma cache (whatever this box holds)."""
    from app.services.folio.folio_service import FolioService

    from folio_insights.services.folio_ontology import FolioOntologyService

    vendored = FolioOntologyService(lemma_cache_dir=tmp_path_factory.mktemp("lemmas"))
    original = FolioService.get_instance()
    try:
        vendored.get_all_labels()
        original.get_all_labels()
    except Exception as exc:  # pragma: no cover - environment without the FOLIO OWL
        pytest.skip(f"FOLIO ontology not loadable here: {exc!r}")
    return vendored, original


def _concept_dict(concept) -> dict:
    return dataclasses.asdict(concept) if concept is not None else None


def _index_view(labels) -> dict:
    return {k: (v.concept.iri, v.label_type, v.matched_label) for k, v in labels.items()}


def _fresh_pair(folio_pair, tmp_path, lemma_map):
    """Fresh vendored + enrich services over the SAME folio-python graph and lemma map."""
    from app.services.folio.folio_service import FolioService
    from app.services.ontology.spec import FOLIO_SPEC

    from folio_insights.services.folio_ontology import FolioOntologyService

    vendored, original = folio_pair
    v = FolioOntologyService(folio=vendored._get_folio(), lemma_cache_dir=tmp_path)
    v._lemma_map = dict(lemma_map)
    e = FolioService(FOLIO_SPEC)
    e._folio = vendored._get_folio()
    e._build_branch_map()
    e._lemma_map = dict(lemma_map)
    return v, e


@pytest.mark.integration
def test_folio_label_index_parity_without_lemmas(folio_pair, tmp_path):
    """Index-building parity with the lemma tier empty on both sides."""
    v, e = _fresh_pair(folio_pair, tmp_path, {})
    vi, ei = _index_view(v.get_all_labels()), _index_view(e.get_all_labels())
    assert len(vi) == len(ei) > 15000
    assert vi == ei
    assert v.get_concept_count() == e.get_concept_count()


@pytest.mark.integration
def test_folio_label_index_parity_with_same_lemma_map(folio_pair, tmp_path):
    """Lemma-tier indexing parity: feed both sides enrich's own lemma map."""
    _, original = folio_pair
    lemma_map = original._compute_label_lemmas()
    if not lemma_map:
        pytest.skip("enrich has no lemma map on this box (no spaCy, no enrich lemma cache)")
    v, _ = _fresh_pair(folio_pair, tmp_path, lemma_map)
    vi, ei = _index_view(v.get_all_labels()), _index_view(original.get_all_labels())
    assert vi == ei
    assert any(t.startswith("lemma_") for _, t, _ in vi.values())


@pytest.mark.integration
def test_folio_lemma_computation_parity(folio_pair, tmp_path, monkeypatch):
    """Lemma COMPUTATION from scratch (no caches) on both sides.

    Without spaCy (not a folio-insights dependency) both compute an empty map, so the
    lemma tier is empty, as in enrich. With spaCy installed both compute the same map."""
    from app.services.folio import folio_service as enrich_fs

    monkeypatch.setattr(enrich_fs, "_LEMMA_CACHE_DIR", tmp_path / "enrich")
    v, e = _fresh_pair(folio_pair, tmp_path / "insights", {})
    v._lemma_map = e._lemma_map = None
    v_map, e_map = v._compute_label_lemmas(), e._compute_label_lemmas()
    assert v_map == e_map
    try:
        import spacy  # noqa: F401
    except ImportError:
        assert v_map == {}
        assert not any(t.startswith("lemma_") for _, t, _ in _index_view(v.get_all_labels()).values())


@pytest.mark.integration
def test_folio_search_and_lookup_parity(folio_pair):
    vendored, original = folio_pair
    assert len(FOLIO_PROBE_LABELS) >= 30
    compared_iris: set[str] = set()
    for label in FOLIO_PROBE_LABELS:
        for top_k in (5, 1):
            v = vendored.search_by_label(label, top_k=top_k)
            e = original.search_by_label(label, top_k=top_k)
            assert [(c.iri, s) for c, s in v] == [(c.iri, s) for c, s in e], label
            assert [_concept_dict(c) for c, _ in v] == [_concept_dict(c) for c, _ in e], label
            compared_iris.update(c.iri for c, _ in v)
        assert [c.iri for c in vendored.search_by_prefix(label)] == [
            c.iri for c in original.search_by_prefix(label)
        ]
    assert len(compared_iris) >= 30
    for iri in sorted(compared_iris) + ["https://folio.openlegalstandard.org/NOPE", ""]:
        assert _concept_dict(vendored.get_concept(iri)) == _concept_dict(original.get_concept(iri))


@pytest.mark.integration
def test_folio_service_feeds_deterministic_ruler(folio_pair):
    """B5 canary on the in-repo service: the pinned ruler emits a real FOLIO IRI."""
    from folio_insights.services.bridge.folio_bridge import verify_deterministic_bridge

    vendored, _ = folio_pair
    ruler = verify_deterministic_bridge()()
    ruler.load_patterns(vendored.get_all_labels())
    iris = [m.entity_id for m in ruler.find_matches("The parties scheduled a deposition.")]
    assert any(iri.startswith("https://folio.openlegalstandard.org/") for iri in iris), iris


class _FakeOwl:
    def __init__(self, iri, label, alts=(), preferred_label=None, deprecated=False, hidden=""):
        self.iri, self.label, self.alternative_labels = iri, label, list(alts)
        self.preferred_label = preferred_label
        self.deprecated, self.hidden_label = deprecated, hidden
        self.sub_class_of, self.definition = [], f"def of {label}"


class _FakeBranch:
    def __init__(self, name):
        self.name = name


class _FakeFolio:
    def __init__(self, classes, branches):
        self.classes = classes
        self._branches = branches
        self._by_iri = {c.iri: c for c in classes}

    def get_folio_branches(self):
        return self._branches

    def get_parents(self, iri):
        return []

    def __getitem__(self, iri):
        return self._by_iri[iri]

    def search_by_label(self, label, include_alt_labels=True):
        return [(c, 100.0) for c in self.classes if c.label.lower() == label.lower()]


def test_folio_ontology_label_index_rules(monkeypatch, tmp_path):
    """Exclusion and priority rules of the vendored index, without the live ontology."""
    from folio_insights.services.folio_ontology import FolioOntologyService

    keep = _FakeOwl("https://f/A", "Deposition", alts=["Depo", "Witness"])
    other = _FakeOwl("https://f/B", "Witness", alts=["Depo"])
    sandbox = _FakeOwl("https://f/C", "Area Thing")
    dupe = _FakeOwl("https://f/D", "Thing DUPE")
    zzz = _FakeOwl("https://f/E", "ZZZ: placeholder")
    old = _FakeOwl("https://f/F", "Old", deprecated=True)
    pref = _FakeOwl("https://f/G", "rdfs label", preferred_label="SKOS Pref", hidden="hid")
    folio = _FakeFolio(
        [keep, other, sandbox, dupe, zzz, old, pref],
        {_FakeBranch("AREA_OF_LAW"): [sandbox], _FakeBranch("EVENT"): [keep]},
    )
    svc = FolioOntologyService(folio=folio, lemma_cache_dir=tmp_path)
    labels = svc.get_all_labels()
    assert {k: (v.concept.iri, v.label_type) for k, v in labels.items()} == {
        "deposition": ("https://f/A", "preferred"),
        "depo": ("https://f/A", "alternative"),  # first alternative wins a tie
        "witness": ("https://f/B", "preferred"),  # preferred out-ranks an alternative
        "rdfs label": ("https://f/G", "preferred"),
        "skos pref": ("https://f/G", "preferred"),
        "hid": ("https://f/G", "hidden"),
    }
    assert labels["deposition"].concept.branch == "Event"
    assert svc.get_concept("https://f/A").preferred_label == "Deposition"
    assert svc.get_concept("https://f/missing") is None
    [(hit, score)] = svc.search_by_label("witness")
    assert (hit.iri, score) == ("https://f/B", 100.0)


def test_folio_ontology_uses_own_lemma_cache(monkeypatch, tmp_path):
    import pickle

    from folio_insights.services import folio_ontology
    from folio_insights.services.folio_ontology import FolioOntologyService

    monkeypatch.setattr(folio_ontology, "get_owl_content_hash", lambda: "abc123")
    (tmp_path / "labels_abc123_v1.pkl").write_bytes(pickle.dumps({"agreements": "agreement"}))
    folio = _FakeFolio([_FakeOwl("https://f/A", "Agreements")], {})
    labels = FolioOntologyService(folio=folio, lemma_cache_dir=tmp_path).get_all_labels()
    assert labels["agreement"].label_type == "lemma_preferred"
    assert labels["agreement"].matched_label == "Agreements"


def test_folio_ontology_default_lemma_cache_is_insights_owned():
    from folio_insights.services.folio_ontology import FolioOntologyService

    path = FolioOntologyService(folio=_FakeFolio([], {}))._lemma_cache_path()
    assert ".folio-insights" in path.parts and ".folio-enrich" not in path.parts


def test_folio_ontology_failed_load_is_memoized_with_cooldown(monkeypatch):
    from folio_insights.services import folio_ontology
    from folio_insights.services.folio_ontology import (
        FolioLoadUnavailableError,
        FolioOntologyService,
    )

    clock = [1000.0]
    monkeypatch.setattr(folio_ontology.time, "monotonic", lambda: clock[0])
    attempts = []
    svc = FolioOntologyService(load_retry_seconds=300)

    def failing_load():
        attempts.append(clock[0])
        raise OSError("offline: cannot fetch FOLIO.owl")

    monkeypatch.setattr(svc, "_load_folio", failing_load)
    with pytest.raises(OSError):
        svc.search_by_label("deposition")
    for _ in range(5):  # within the cooldown: no new fetch attempt, immediate error
        clock[0] += 10
        with pytest.raises(FolioLoadUnavailableError, match="not retrying"):
            svc.get_concept("https://f/A")
    assert attempts == [1000.0]

    clock[0] = 1000.0 + 301  # cooldown over: one retry, which now succeeds
    good = _FakeFolio([_FakeOwl("https://f/A", "Deposition")], {})
    monkeypatch.setattr(svc, "_load_folio", lambda: attempts.append(clock[0]) or good)
    assert svc.get_concept("https://f/A").preferred_label == "Deposition"
    assert len(attempts) == 2


def test_get_folio_service_is_in_repo_singleton_without_sys_path(monkeypatch, tmp_path):
    from folio_insights.config import get_settings
    from folio_insights.services.bridge.folio_bridge import get_folio_service
    from folio_insights.services.folio_ontology import FolioOntologyService

    monkeypatch.setattr(get_settings(), "folio_enrich_path", tmp_path / "absent")
    before = list(sys.path)
    svc = get_folio_service()  # lazy: does not load the ontology yet
    assert isinstance(svc, FolioOntologyService)
    assert svc is get_folio_service()
    for attr in ("get_all_labels", "search_by_label", "get_concept"):
        assert callable(getattr(svc, attr))
    assert sys.path == before


# ---------------------------------------------------------------------------------------
# 4. EmbeddingService
# ---------------------------------------------------------------------------------------

EMBEDDING_PAIRS = [
    ("The witness lied under oath.", "The deponent committed perjury."),
    ("Summary judgment was granted.", "The court granted the motion for summary judgment."),
    ("Bananas are yellow.", "The statute of limitations expired."),
    ("Cross-examination", "Direct examination"),
    ("Café résumé “quoted”", "Ñandú"),
    ("", "Empty strings embed too."),
]
EMBEDDING_LABELS = ["deposition", "summary judgment", "hearsay", "negligence", "contract"]


def test_embedding_service_contract_with_stub_model(monkeypatch):
    import numpy as np

    from folio_insights.services import embedding as emb_mod
    from folio_insights.services.boundary import semantic

    class _Model:
        def encode(self, texts, normalize_embeddings=True):
            vecs = np.array([[t.count("a"), t.count("b"), 1.0] for t in texts], dtype=float)
            return vecs / np.linalg.norm(vecs, axis=1, keepdims=True)

    monkeypatch.setattr(semantic, "_get_model", lambda name="all-MiniLM-L6-v2": _Model())
    svc = emb_mod.EmbeddingService()
    assert svc.model_name == "all-MiniLM-L6-v2"
    assert svc.index_size == 0 and svc.search("anything") == []
    assert svc.search_batch(["a", "b"]) == [[], []]
    assert svc.similarity_batch([]) == []
    sims = svc.similarity_batch([("aa", "aa"), ("a", "bbbbbbbb")])
    assert sims[0] == pytest.approx(1.0) and sims[1] < 1.0
    assert svc.similarity("aa", "aa") == pytest.approx(1.0)
    svc.index_labels(["aaa", "b", "aaaa"], [{"iri": "x"}, {"iri": "y"}, {"iri": "z"}])
    assert svc.index_size == 3
    top = svc.search("aaa", top_k=2)
    assert top[0].label == "aaa" and top[0].metadata == {"iri": "x"} and len(top) == 2


def test_get_embedding_service_is_empty_in_repo_singleton(monkeypatch, tmp_path):
    from folio_insights.config import get_settings
    from folio_insights.services.bridge.folio_bridge import get_embedding_service
    from folio_insights.services.embedding import EmbeddingService

    monkeypatch.setattr(get_settings(), "folio_enrich_path", tmp_path / "absent")
    before = list(sys.path)
    svc = get_embedding_service()
    assert isinstance(svc, EmbeddingService)
    assert svc is get_embedding_service()
    assert svc.index_size == 0  # as with enrich's get_instance(): no label index
    assert sys.path == before


@pytest.mark.integration
def test_embedding_parity_with_enrich(enrich):
    from app.services.embedding.service import EmbeddingService as EnrichEmbeddingService

    from folio_insights.services.embedding import EmbeddingService

    try:
        original = EnrichEmbeddingService()  # == get_instance()'s construction
        e_sims = original.similarity_batch(EMBEDDING_PAIRS)
    except Exception as exc:  # pragma: no cover - model not downloadable here
        pytest.skip(f"sentence-transformers model unavailable: {exc!r}")
    vendored = EmbeddingService()
    v_sims = vendored.similarity_batch(EMBEDDING_PAIRS)
    assert v_sims == pytest.approx(e_sims, abs=1e-4)
    for a, b in EMBEDDING_PAIRS:
        assert vendored.similarity(a, b) == pytest.approx(original.similarity(a, b), abs=1e-4)

    assert vendored.index_size == original.index_size == 0
    meta = [{"iri": f"https://f/{i}"} for i in range(len(EMBEDDING_LABELS))]
    vendored.index_labels(list(EMBEDDING_LABELS), [dict(m) for m in meta])
    original.index_labels(list(EMBEDDING_LABELS), [dict(m) for m in meta])
    for query, _ in EMBEDDING_PAIRS:
        v, e = vendored.search(query, top_k=3), original.search(query, top_k=3)
        assert [r.label for r in v] == [r.label for r in e]
        assert [r.metadata for r in v] == [r.metadata for r in e]
        assert [r.score for r in v] == pytest.approx([r.score for r in e], abs=1e-4)
