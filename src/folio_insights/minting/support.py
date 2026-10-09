"""Claim support: is a unit's distilled text backed by the source passage it anchors to?

The anchor (``minting.eligibility``) proves only that the unit's snippet or span is a
real passage of the source. It says nothing about the unit's TEXT, which the distiller
rewrites after anchoring and which becomes the shard's ``triple.object``. The v1 books
run showed what that gap costs: a fluent claim citing "Rule 26" (0 occurrences in the
book) anchored to a passage about something else (``docs/evidence/books/
DE-RISK-FINDINGS.md``). This module closes it with a DETERMINISTIC gate that runs before
any LLM call and needs no model:

1. **Fabrication-sensitive specifics** (``unsupported_specifics``). Every specific the
   claim states must occur in the verified passage:

   * ``citation`` -- rule, statute and section citations ("Rule 26(a)(2)(B)",
     "§ 1983", "FRE 702", "Fed. R. Civ. P. 56", "28 U.S.C. § 1332", "Section 12",
     "509 U.S. 579"), compared in a canonical form (family, title, locator). A claim may
     cite less precisely than the passage ("Rule 26" is supported by "Rule 26(a)(1)"),
     never more precisely; "Rule 702" is supported by "FRE 702", and "FRE 702" by "Rule
     702" only when the passage names the Rules of Evidence.
   * ``case_name`` -- "X v. Y": the folded "x v y" phrase must occur in the passage.
   * ``date`` -- month-name, ISO and m/d/y dates: same month and day (and year, when the
     claim gives one).
   * ``money`` / ``percentage`` -- "$1,000", "$5 million", "500 dollars", "15%",
     "fifteen percent": the same amount of the same kind.
   * ``number`` -- every other number, in digits or words ("14", "fourteen",
     "twenty-one", "two hundred"): the same value anywhere in the passage. The word
     "one" alone is not read as a number (it is far more often a pronoun).
   * ``proper_noun`` -- a run of two or more capitalized words ("Merrell Dow", "Acme
     Corporation", "Supreme Court of Minnesota"), less a sentence-initial function word:
     the folded phrase must occur in the passage.

   Missing specifics refuse the claim; the detail names the CLASSES that failed, never
   the text, so a report never repeats source or unit prose.

2. **Lexical support** (``claim_unsupported``). Recall of the claim's content tokens
   (casefolded, stopwords removed, reduced by a small deterministic suffix stripper)
   against the passage's must reach ``SupportPolicy.min_recall`` (default
   ``DEFAULT_MIN_RECALL`` = 0.6). A faithful compression keeps the passage's words; an
   invented or loosely paraphrased claim does not.

3. **Optional entailment** (``claim_not_entailed``). With ``SupportPolicy.nli`` set, an
   ``EntailmentScorer`` (default: the cross-encoder of ``validation.nli``, loaded
   lazily) must rate passage => claim at ``nli_threshold`` or above. It runs only for a
   claim that passed 1 and 2. A requested scorer that cannot load refuses the whole run
   (``SupportUnavailable``); it is never skipped silently.

Normalization everywhere: NFC, casefold, curly quotes and dashes folded, every run of
non-alphanumeric characters folded to one space (citations keep their own canonical
form). Everything here is pure, stdlib-only and deterministic.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, runtime_checkable

UNSUPPORTED_SPECIFICS = "unsupported_specifics"
CLAIM_UNSUPPORTED = "claim_unsupported"
CLAIM_NOT_ENTAILED = "claim_not_entailed"
SUPPORT_CODES: tuple[str, ...] = (UNSUPPORTED_SPECIFICS, CLAIM_UNSUPPORTED, CLAIM_NOT_ENTAILED)

DEFAULT_MIN_RECALL = 0.6
DEFAULT_NLI_THRESHOLD = 0.5

#: The specific classes, in the order they are extracted from a claim.
SPECIFIC_CLASSES: tuple[str, ...] = (
    "citation", "case_name", "date", "money", "percentage", "number", "proper_noun",
)

METHOD_LEXICAL = "specifics+lexical"
METHOD_NLI = "specifics+lexical+nli"


# ── normalization ────────────────────────────────────────────────────────

_FOLD_MAP = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "‑": "-", " ": " ",
})
_NON_ALNUM = re.compile(r"[^0-9a-z§%$]+")


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", (text or "").translate(_FOLD_MAP))


def fold(text: str) -> str:
    """NFC, casefold, and every run of punctuation / whitespace folded to one space."""
    return " ".join(_NON_ALNUM.sub(" ", nfc(text).casefold()).split())


def _contains_phrase(haystack_folded: str, phrase: str) -> bool:
    needle = fold(phrase)
    return bool(needle) and f" {needle} " in f" {haystack_folded} "


# ── stemming and stopwords ───────────────────────────────────────────────

STOPWORDS: frozenset[str] = frozenset("""
a about above after again against all am an and any are as at be because been before
being below between both but by can could did do does doing down during each either
every few for from further had has have having he her here hers herself him himself his
how i if in into is it its itself just let me might more most must my myself nor of off
on once only or other ought our ours ourselves out over own per same shall she should so
some such than that the their theirs them themselves then there these they this those
through thus to too under until up upon us very via was we were what when where whether
which while who whom whose why will with within without would you your yours yourself
yourselves also may one ones another s t
""".split())

#: Suffixes the stripper removes, longest first. Both sides go through the same
#: function, so the stems need only be consistent, not linguistically correct.
_SUFFIXES: tuple[str, ...] = (
    "izations", "ization", "ations", "ation", "ements", "ement", "ments", "ment",
    "nesses", "ness", "ingly", "edly", "ities", "ity", "ings", "ing", "ions", "ion",
    "ies", "ied", "ers", "ed", "ly", "es", "s",
)


def stem(token: str) -> str:
    """A small deterministic suffix stripper (no dependency; consistent, not exact)."""
    word = token.casefold()
    if len(word) <= 3 or word.isdigit():
        return word
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            if suffix in ("ies", "ied"):
                word = word[: -len(suffix)] + "y"
            elif suffix == "s" and word.endswith(("ss", "us", "is")):
                break
            else:
                word = word[: -len(suffix)]
            break
    if len(word) > 4 and word[-1] == word[-2] and word[-1] not in "aeiouls":
        word = word[:-1]  # "stopp" -> "stop", keep "witness" / "fall"
    if len(word) > 4 and word.endswith("e"):
        word = word[:-1]  # "examine" / "examin(ation)" -> "examin"
    return word


def content_stems(text: str) -> frozenset[str]:
    """The claim-support vocabulary of ``text``: folded tokens, no stopwords, stemmed."""
    return frozenset(
        stem(tok) for tok in fold(text).split()
        if tok not in STOPWORDS and (len(tok) > 1 or tok.isdigit()) and tok not in ("§", "%", "$")
    )


# ── numbers ──────────────────────────────────────────────────────────────

_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19,
}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
         "eighty": 80, "ninety": 90}
_SCALES = {"hundred": 100, "thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}
_NUMBER_WORDS = frozenset(_UNITS) | frozenset(_TENS) | frozenset(_SCALES)


def _words_value(words: Sequence[str]) -> int | None:
    total = current = 0
    seen = False
    for word in words:
        if word in _UNITS:
            current += _UNITS[word]
        elif word in _TENS:
            current += _TENS[word]
        elif word == "hundred":
            current = (current or 1) * 100
        elif word in _SCALES:
            total += (current or 1) * _SCALES[word]
            current = 0
        else:
            return None
        seen = True
    return total + current if seen else None


_DIGITS = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
_SCALE_RE = r"(?:\s*(?:thousand|million|billion|[kKmMbB]n?)\b)?"


def _decimal(raw: str) -> Decimal | None:
    try:
        return Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None


def _scale(word: str) -> int:
    word = word.strip().casefold()
    if word in ("thousand", "k"):
        return 1_000
    if word in ("million", "m", "mn"):
        return 1_000_000
    if word in ("billion", "b", "bn"):
        return 1_000_000_000
    return 1


# ── citations ────────────────────────────────────────────────────────────

_LOC = r"\d+[A-Za-z]?(?:[.\-]\d+[A-Za-z]?)*(?:\s?\([A-Za-z0-9]{1,4}\))*"
_FED_FAMILIES: tuple[tuple[str, str, str], ...] = (
    # (family, pattern for the rules' name, keyword proving the family in a passage)
    ("fre", r"(?:F\.?\s?R\.?\s?E\.?|Fed(?:eral)?\.?\s+R(?:ules?)?\.?\s+(?:of\s+)?Evid(?:ence)?\.?)",
     "evidence"),
    ("frcp", r"(?:F\.?\s?R\.?\s?C\.?\s?P\.?|Fed(?:eral)?\.?\s+R(?:ules?)?\.?\s+(?:of\s+)?"
             r"Civ(?:il)?\.?\s+P(?:roc(?:edure)?)?\.?)", "civil"),
    ("frcrp", r"(?:F\.?\s?R\.?\s?Cr(?:im)?\.?\s?P\.?|Fed(?:eral)?\.?\s+R(?:ules?)?\.?\s+(?:of\s+)?"
              r"Crim(?:inal)?\.?\s+P(?:roc(?:edure)?)?\.?)", "criminal"),
    ("frap", r"(?:F\.?\s?R\.?\s?A\.?\s?P\.?|Fed(?:eral)?\.?\s+R(?:ules?)?\.?\s+(?:of\s+)?"
             r"App(?:ellate)?\.?\s+P(?:roc(?:edure)?)?\.?)", "appellate"),
)
_FED_KEYWORD = {family: keyword for family, _, keyword in _FED_FAMILIES}
_CITATION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("usc", re.compile(rf"\b(\d+)\s+U\.?\s?S\.?\s?C\.?(?:\s?A\.?)?\s*(?:§+|[Ss]ec(?:tion|\.)?)\s*({_LOC})")),
    *((family, re.compile(rf"\b{name}\s*(?:R(?:ule)?\.?\s*)?({_LOC})"))
      for family, name, _ in _FED_FAMILIES),
    ("reporter", re.compile(
        r"\b(\d+)\s+(U\.\s?S\.|S\.\s?Ct\.|L\.\s?Ed\.(?:\s?2d)?|F\.\s?Supp\.(?:\s?[23]d)?"
        r"|F\.\s?App'x|F\.(?:\s?(?:2d|3d|4th))?|N\.W\.(?:\s?2d)?)\s+(\d+)\b")),
    ("§", re.compile(rf"(?:§+|\b[Ss]ec(?:tion|\.)\s)\s*({_LOC})")),
    ("rule", re.compile(rf"\b[Rr]ules?\s+({_LOC})")),
)


@dataclass(frozen=True, order=True)
class Citation:
    family: str
    title: str
    locator: str


def _canon_locator(raw: str) -> str:
    return re.sub(r"\s+", "", raw).casefold()


def _extract_citations(text: str) -> tuple[list[Citation], str]:
    """The text's citations, and the text with them masked out (for later classes)."""
    found: list[Citation] = []
    masked = text
    for family, pattern in _CITATION_PATTERNS:
        def _take(match: re.Match[str], family: str = family) -> str:
            if family == "usc":
                found.append(Citation("usc", match.group(1), _canon_locator(match.group(2))))
            elif family == "reporter":
                reporter = re.sub(r"[\s.]+", "", match.group(2)).casefold()
                found.append(Citation("reporter", f"{match.group(1)}{reporter}",
                                      match.group(3)))
            else:
                found.append(Citation(family, "", _canon_locator(match.group(1))))
            return " " * len(match.group(0))

        masked = pattern.sub(_take, masked)
    return found, masked


def _locator_covers(claimed: str, stated: str) -> bool:
    """A claim may cite less precisely than the passage, never more precisely."""
    return stated == claimed or stated.startswith(claimed + "(")


def _citation_supported(claim: Citation, passage: Sequence[Citation], passage_folded: str) -> bool:
    for cite in passage:
        if not _locator_covers(claim.locator, cite.locator):
            continue
        if claim.family == cite.family and claim.title == cite.title:
            return True
        if claim.family == "rule" and (cite.family in _FED_KEYWORD or cite.family == "rule"):
            return True
        if (claim.family in _FED_KEYWORD and cite.family == "rule"
                and _contains_phrase(passage_folded, _FED_KEYWORD[claim.family])):
            return True
        if claim.family == "§" and cite.family == "usc":
            return True
    return False


# ── case names, dates, quantities, proper nouns ──────────────────────────

_CAP = r"[A-Z][\w'&.\-]*"
_PARTY = rf"{_CAP}(?:\s+(?:of|the|and|&|for|de|{_CAP}))*"
_CASE_RE = re.compile(rf"({_PARTY})\s+v(?:s)?\.?\s+({_PARTY})")

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH = (r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?"
          r"|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?")
_DATE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("mdy", re.compile(rf"\b{_MONTH}\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b")),
    ("dmy", re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTH},?(?:\s+(\d{{4}}))?\b")),
    ("my", re.compile(rf"\b{_MONTH},?\s+(\d{{4}})\b")),
    ("iso", re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")),
    ("slash", re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")),
)


@dataclass(frozen=True)
class DateRef:
    year: int | None
    month: int
    day: int | None


def _year(raw: str | None) -> int | None:
    if not raw:
        return None
    value = int(raw)
    return value + 2000 if value < 100 else value


def _extract_dates(text: str) -> tuple[list[DateRef], str]:
    found: list[DateRef] = []
    masked = text
    for kind, pattern in _DATE_PATTERNS:
        def _take(m: re.Match[str], kind: str = kind) -> str:
            if kind == "mdy":
                found.append(DateRef(_year(m.group(3)), _MONTHS[m.group(1)[:3].casefold()],
                                     int(m.group(2))))
            elif kind == "dmy":
                found.append(DateRef(_year(m.group(3)), _MONTHS[m.group(2)[:3].casefold()],
                                     int(m.group(1))))
            elif kind == "my":
                found.append(DateRef(_year(m.group(2)), _MONTHS[m.group(1)[:3].casefold()], None))
            elif kind == "iso":
                found.append(DateRef(int(m.group(1)), int(m.group(2)), int(m.group(3))))
            else:
                found.append(DateRef(_year(m.group(3)), int(m.group(1)), int(m.group(2))))
            return " " * len(m.group(0))

        masked = pattern.sub(_take, masked)
    return found, masked


def _date_supported(claim: DateRef, passage: Sequence[DateRef]) -> bool:
    return any(
        d.month == claim.month
        and (claim.day is None or d.day == claim.day)
        and (claim.year is None or d.year == claim.year)
        for d in passage
    )


@dataclass(frozen=True)
class Quantity:
    kind: str  # "money" | "percentage" | "number"
    value: Decimal


_NUMWORD = "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True))
_WORDNUM = rf"(?:(?:{_NUMWORD})(?:[\s\-]+(?:and\s+)?(?:{_NUMWORD}))*)"
_QUANTITY_RE = re.compile(
    rf"(?P<cur>\$|\bUSD\s?)?\s*(?:(?P<digits>{_DIGITS})|\b(?P<words>{_WORDNUM})\b)"
    rf"(?P<scale>{_SCALE_RE})"
    r"(?P<unit>\s*%|\s*(?:percent|per\s?cent)\b|\s*(?:dollars?|USD)\b)?",
    re.IGNORECASE,
)


def _extract_quantities(text: str) -> list[Quantity]:
    found: list[Quantity] = []
    for m in _QUANTITY_RE.finditer(text):
        if m.group("digits"):
            value = _decimal(m.group("digits"))
        else:
            words = [w for w in re.split(r"[\s\-]+", m.group("words").casefold()) if w != "and"]
            if words == ["one"]:
                continue  # "one" alone is far more often a pronoun than a number
            raw = _words_value(words)
            value = Decimal(raw) if raw is not None else None
        if value is None:
            continue
        value *= _scale(m.group("scale") or "")
        unit = (m.group("unit") or "").strip().casefold()
        if m.group("cur") or unit.startswith(("dollar", "usd")):
            kind = "money"
        elif unit:
            kind = "percentage"
        else:
            kind = "number"
        found.append(Quantity(kind, value.normalize()))
    return found


def _strip_leading_function_words(phrase: str) -> str:
    words = phrase.split()
    while words and words[0].casefold() in STOPWORDS:
        words.pop(0)
    return " ".join(words)


def _extract_case_names(text: str) -> tuple[list[str], str]:
    found: list[str] = []

    def _take(m: re.Match[str]) -> str:
        first = _strip_leading_function_words(m.group(1))
        if first:
            found.append(f"{first} v {m.group(2)}")
        return " " * len(m.group(0))

    return found, _CASE_RE.sub(_take, text)


_TOKEN_RE = re.compile(r"[A-Za-z][\w'&\-]*|[.!?;:]|\S")
_CONNECTORS = frozenset({"of", "the", "and", "&", "for", "de", "la", "von", "van", "del"})


def _extract_proper_nouns(text: str) -> list[str]:
    """Runs of >= 2 capitalized words, connectors allowed inside, sentence-initial
    function words dropped."""
    tokens = _TOKEN_RE.findall(text)
    found: list[str] = []
    run: list[str] = []
    sentence_start = True
    run_started_sentence = False

    def flush() -> None:
        nonlocal run
        while run and run[-1].casefold() in _CONNECTORS:
            run.pop()
        words = list(run)
        if words and run_started_sentence and words[0].casefold() in STOPWORDS:
            words = words[1:]
        caps = [w for w in words if w[:1].isupper()]
        if len(caps) >= 2:
            found.append(" ".join(words))
        run = []

    for token in tokens:
        if token[:1].isupper() and token[:1].isalpha():
            if not run:
                run_started_sentence = sentence_start
            run.append(token)
        elif run and token.casefold() in _CONNECTORS:
            run.append(token)
        else:
            flush()
        sentence_start = token in (".", "!", "?", ";", ":")
    flush()
    return found


# ── the result and the policy ────────────────────────────────────────────


@runtime_checkable
class EntailmentScorer(Protocol):
    """Probability that each (premise, hypothesis) pair is an entailment."""

    @property
    def name(self) -> str: ...

    def entailment_probabilities(self, pairs: Sequence[tuple[str, str]]) -> list[float]: ...


class SupportUnavailable(RuntimeError):
    """An entailment check was requested but its scorer cannot run."""


class CrossEncoderEntailmentScorer:
    """``validation.nli``'s cross-encoder, read for its ENTAILMENT label (lazy)."""

    ENTAILMENT_LABEL_INDEX = 1  # label order: contradiction, entailment, neutral

    def __init__(self, model_name: str | None = None) -> None:
        from folio_insights.validation.nli import NLI_MODEL_NAME, CrossEncoderNliScorer

        self._inner = CrossEncoderNliScorer(model_name or NLI_MODEL_NAME)

    @property
    def name(self) -> str:
        return f"nli-entailment:{self._inner.model_name}"

    def ensure_available(self) -> None:
        """Load the model now, so a run that asked for entailment fails before it starts."""
        import importlib.util

        if importlib.util.find_spec("sentence_transformers") is None:
            raise SupportUnavailable("sentence-transformers is not installed")
        try:
            self._inner._get_model()
        except Exception as exc:  # noqa: BLE001 - any load failure means "unavailable"
            raise SupportUnavailable(f"the NLI model could not be loaded "
                                     f"({type(exc).__name__})") from None

    def entailment_probabilities(self, pairs: Sequence[tuple[str, str]]) -> list[float]:
        from folio_insights.validation.nli import _softmax

        if not pairs:
            return []
        model = self._inner._get_model()
        return [_softmax([float(v) for v in row])[self.ENTAILMENT_LABEL_INDEX]
                for row in model.predict(list(pairs))]


@dataclass(frozen=True)
class SupportPolicy:
    """How strictly a claim must be supported by its passage.

    ``min_recall`` is the lexical floor; ``nli`` turns the entailment check on, with
    ``nli_threshold`` its floor and ``scorer`` the injectable scorer (default: the
    cross-encoder, built lazily by ``resolve_scorer``).
    """

    min_recall: float = DEFAULT_MIN_RECALL
    nli: bool = False
    nli_threshold: float = DEFAULT_NLI_THRESHOLD
    scorer: EntailmentScorer | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        for name in ("min_recall", "nli_threshold"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be within [0, 1]; got {value}")

    @property
    def method(self) -> str:
        return METHOD_NLI if self.nli else METHOD_LEXICAL

    def resolve_scorer(self) -> SupportPolicy:
        """This policy with a ready scorer (``SupportUnavailable`` when it cannot run).

        A no-op without ``nli``. A supplied scorer is checked with its own
        ``ensure_available`` when it has one."""
        if not self.nli:
            return self
        scorer = self.scorer if self.scorer is not None else CrossEncoderEntailmentScorer()
        ensure = getattr(scorer, "ensure_available", None)
        if callable(ensure):
            ensure()
        return SupportPolicy(self.min_recall, True, self.nli_threshold, scorer)


@dataclass(frozen=True)
class SupportResult:
    """What the support check measured (no text, so it is safe in any report)."""

    ratio: float
    min_recall: float
    specifics_checked: int
    classes_checked: tuple[str, ...]
    missing_classes: tuple[str, ...]
    method: str
    entailment: float | None = None
    nli_threshold: float | None = None
    scorer: str | None = None

    @property
    def lexical_ok(self) -> bool:
        return self.ratio >= self.min_recall

    @property
    def entailed(self) -> bool | None:
        if self.entailment is None or self.nli_threshold is None:
            return None
        return self.entailment >= self.nli_threshold

    def failures(self) -> list[tuple[str, str]]:
        """``(code, detail)`` for every failed check, in check order."""
        out: list[tuple[str, str]] = []
        if self.missing_classes:
            out.append((UNSUPPORTED_SPECIFICS,
                        "specifics in the claim do not occur in the verified passage: "
                        + ", ".join(self.missing_classes)))
        if not self.lexical_ok:
            out.append((CLAIM_UNSUPPORTED,
                        f"content-token recall {self.ratio:.4f} against the verified passage "
                        f"is below the floor {self.min_recall:.2f}"))
        if self.entailed is False:
            out.append((CLAIM_NOT_ENTAILED,
                        f"entailment {self.entailment:.4f} of the claim by the verified "
                        f"passage is below {self.nli_threshold:.2f} ({self.scorer})"))
        return out

    @property
    def supported(self) -> bool:
        return not self.failures()

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "method": self.method,
            "ratio": round(self.ratio, 4),
            "min_recall": self.min_recall,
            "specifics_checked": self.specifics_checked,
            "classes_checked": list(self.classes_checked),
            "missing_classes": list(self.missing_classes),
            "supported": self.supported,
        }
        if self.entailment is not None:
            out["entailment"] = round(self.entailment, 4)
            out["nli_threshold"] = self.nli_threshold
            out["scorer"] = self.scorer
        return out


# ── the checks ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Specifics:
    """The fabrication-sensitive specifics of one text, by class."""

    citations: tuple[Citation, ...] = ()
    case_names: tuple[str, ...] = ()
    dates: tuple[DateRef, ...] = ()
    quantities: tuple[Quantity, ...] = ()
    proper_nouns: tuple[str, ...] = ()

    def count(self) -> int:
        return (len(self.citations) + len(self.case_names) + len(self.dates)
                + len(self.quantities) + len(self.proper_nouns))

    def classes(self) -> tuple[str, ...]:
        present = {
            "citation": bool(self.citations), "case_name": bool(self.case_names),
            "date": bool(self.dates), "proper_noun": bool(self.proper_nouns),
            **{kind: False for kind in ("money", "percentage", "number")},
        }
        for q in self.quantities:
            present[{"money": "money", "percentage": "percentage"}.get(q.kind, "number")] = True
        return tuple(c for c in SPECIFIC_CLASSES if present[c])


def extract_specifics(text: str) -> Specifics:
    """Every specific of ``text``; each span is consumed by the first class that claims it."""
    text = nfc(text)
    citations, rest = _extract_citations(text)
    cases, rest = _extract_case_names(rest)
    dates, rest = _extract_dates(rest)
    quantities = _extract_quantities(rest)
    nouns = _extract_proper_nouns(rest)
    return Specifics(tuple(citations), tuple(cases), tuple(dates), tuple(quantities),
                     tuple(nouns))


def missing_specific_classes(claim: str, passage: str) -> tuple[Specifics, tuple[str, ...]]:
    """The claim's specifics and the classes of those the passage does not support."""
    wanted = extract_specifics(claim)
    passage = nfc(passage)
    folded = fold(passage)
    stated_cites, _ = _extract_citations(passage)
    stated_dates, _ = _extract_dates(passage)
    stated = _extract_quantities(passage)
    # A plain number is supported by the same value anywhere in the passage (a year
    # inside a date, a section number inside a citation, a spelled-out count).
    any_values = {q.value for q in stated}
    for d in stated_dates:
        any_values.update(Decimal(v) for v in (d.year, d.month, d.day) if v is not None)
    by_kind = {(q.kind, q.value) for q in stated}

    missing: set[str] = set()
    for cite in wanted.citations:
        if not _citation_supported(cite, stated_cites, folded):
            missing.add("citation")
    for case in wanted.case_names:
        if not _contains_phrase(folded.replace(" vs ", " v "), case):
            missing.add("case_name")
    for date in wanted.dates:
        if not _date_supported(date, stated_dates):
            missing.add("date")
    for q in wanted.quantities:
        if q.kind == "number":
            if q.value not in any_values:
                missing.add("number")
        elif (q.kind, q.value) not in by_kind:
            missing.add(q.kind)
    for noun in wanted.proper_nouns:
        if not _contains_phrase(folded, noun):
            missing.add("proper_noun")
    return wanted, tuple(c for c in SPECIFIC_CLASSES if c in missing)


def lexical_recall(claim: str, passage: str) -> float:
    """Share of the claim's content stems that occur in the passage (0.0 for no stems)."""
    wanted = content_stems(claim)
    if not wanted:
        return 0.0
    return len(wanted & content_stems(passage)) / len(wanted)


def check_support(claim: str, passage: str, policy: SupportPolicy | None = None) -> SupportResult:
    """Measure how well ``passage`` supports ``claim`` (module docstring).

    The entailment scorer runs only when the deterministic checks passed and the policy
    asks for it; a policy with ``nli`` but no scorer raises ``SupportUnavailable``
    (resolve it first with ``SupportPolicy.resolve_scorer``).
    """
    policy = policy or SupportPolicy()
    specifics, missing = missing_specific_classes(claim, passage)
    ratio = round(lexical_recall(claim, passage), 6)
    entailment = None
    if policy.nli:
        if policy.scorer is None:
            raise SupportUnavailable("an entailment check was requested without a scorer")
        if not missing and ratio >= policy.min_recall:
            try:
                (entailment,) = policy.scorer.entailment_probabilities([(passage, claim)])
                entailment = float(entailment)
            except Exception as exc:
                raise SupportUnavailable(
                    f"the entailment scorer failed ({type(exc).__name__})") from None
            if not math.isfinite(entailment) or not 0.0 <= entailment <= 1.0:
                raise SupportUnavailable("the entailment scorer returned an invalid probability")
    return SupportResult(
        ratio=ratio,
        min_recall=policy.min_recall,
        specifics_checked=specifics.count(),
        classes_checked=specifics.classes(),
        missing_classes=missing,
        method=policy.method,
        entailment=entailment,
        nli_threshold=policy.nli_threshold if policy.nli else None,
        scorer=policy.scorer.name if (policy.nli and policy.scorer is not None) else None,
    )


def unsupported_specifics_only(claim: str, passage: str) -> tuple[str, ...]:
    """The missing specific classes alone (for fields where lexical overlap is not
    expected, such as an abstracted ``sense``)."""
    return missing_specific_classes(claim, passage)[1]


__all__ = [
    "CLAIM_NOT_ENTAILED",
    "CLAIM_UNSUPPORTED",
    "DEFAULT_MIN_RECALL",
    "DEFAULT_NLI_THRESHOLD",
    "SPECIFIC_CLASSES",
    "SUPPORT_CODES",
    "STOPWORDS",
    "UNSUPPORTED_SPECIFICS",
    "Citation",
    "CrossEncoderEntailmentScorer",
    "EntailmentScorer",
    "Specifics",
    "SupportPolicy",
    "SupportResult",
    "SupportUnavailable",
    "check_support",
    "content_stems",
    "extract_specifics",
    "fold",
    "lexical_recall",
    "missing_specific_classes",
    "stem",
    "unsupported_specifics_only",
]
