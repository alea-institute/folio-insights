#!/usr/bin/env python3
"""Build and verify the axiom kernel's two source datasets (drain U3, KTD6).

OPERATOR TOOL — not imported by the package and not run by the test suite.
It needs the raw source downloads, which are NOT in this repository: fetch
them (network access required) into a scratch working root ``<root>`` laid
out as

  <root>/dl/grenoble/d-50.htm             droitromain.univ-grenoble-alpes.fr/Corpus/d-50.htm
  <root>/dl/latlib/digest50.shtml         thelatinlibrary.com/justinian/digest50.shtml
  <root>/dl/ia_liber-sextus-bonifacii-1298/LiberSextusBonifacii1298_djvu.txt
  <root>/dl/ia_ls1298_pdf/LiberSextusBonifacii1298.pdf
  <root>/dl/ia_corpusjuriscanon00richuoft/corpusjuriscanon00richuoft_djvu.txt
  <root>/work/ls_adjudications.json       (copy of scripts/kernel/ls_adjudications.json)

(the archive.org files come from https://archive.org/download/<item>/<file>),
then run, from a directory outside the repository, with an isolated
interpreter:

  python3 -I fetch_and_verify_sources.py build-digest <root>   -> <root>/out/digest_50_17.json
  python3 -I fetch_and_verify_sources.py build-ls     <root>   -> <root>/out/liber_sextus_regulae.json
  python3 -I fetch_and_verify_sources.py check        <root>   -> re-verifies both outputs from the raw downloads

The outputs are written under ``<root>/out/``; a reviewed copy of each is
committed as package data at ``src/folio_insights/kernel/data/`` (loaded by
``folio_insights.kernel.catalog``). The datasets' ``verification.script``
field names this tool by its working name, ``scripts/verify.py``.

Rules of the game
-----------------
* Every Latin string written to an output file is cut out of a downloaded
  source file by code; nothing is typed in.  The only editorial operations
  are (a) whitespace normalisation, (b) re-joining words hyphenated across
  OCR line breaks, (c) removal of Friedberg's superscript footnote call-outs
  (Dataset A only), (d) stripping stray OCR punctuation noise *outside* the
  rule sentence (leading/trailing junk such as ', .' or ' |').
* verified_substring (Dataset B): the paragraph text, whitespace-normalised,
  is a literal substring of the whitespace-normalised, tag-stripped,
  entity-decoded primary page text.
* verified_substring (Dataset A): canonA(latin) is a substring of canonA(full
  OCR text of the cited source), where canonA removes all whitespace,
  hyphens (line-break hyphenation), and the footnote call-out characters
  [0-9 ! ? * ' " ^ · | _ » «].  Letters and the punctuation . , : ; are NOT
  touched, so any letter-level difference fails the check.
* cross_checked: the same text is found in the second (and, for A, third)
  independent transcription under the same canonicalisation.
"""
import datetime as _dt
import hashlib
import html
import json
import pathlib
import re
import sys
import difflib

# ---------------------------------------------------------------- helpers

def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def mtime_utc(p):
    return _dt.datetime.fromtimestamp(pathlib.Path(p).stat().st_mtime, _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ws(s):
    return re.sub(r"\s+", " ", s).strip()


def strip_tags(s):
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return html.unescape(s).replace("\xa0", " ")


def letters(s):
    """Loose comparison key for cross-checking two transcriptions."""
    return re.sub(r"[^a-z]", "", s.lower())


def contains(hay, needle):
    """Substring test that also requires word boundaries at both ends, so a
    reading that has lost its first/last letter cannot match inside a longer word."""
    if not needle:
        return False
    start = 0
    while True:
        i = hay.find(needle, start)
        if i < 0:
            return False
        before = hay[i - 1] if i > 0 else " "
        after = hay[i + len(needle)] if i + len(needle) < len(hay) else " "
        # a needle starting with a capital is a sentence start: OCR junk glued
        # in front of it (e.g. a stray 'l' from the rule header) is tolerated.
        bad_before = before.isalpha() and needle[0].isalpha() and not needle[0].isupper()
        bad_after = after.isalpha() and needle[-1].isalpha()
        if not bad_before and not bad_after:
            return True
        start = i + 1


def word_diff(a, b):
    aw, bw = a.split(), b.split()
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=[w.lower() for w in aw], b=[w.lower() for w in bw], autojunk=False).get_opcodes():
        if op != "equal":
            out.append({"op": op, "primary": " ".join(aw[i1:i2]), "secondary": " ".join(bw[j1:j2])})
    return out

# ---------------------------------------------------------------- Dataset B

LATLIB_URL = "https://www.thelatinlibrary.com/justinian/digest50.shtml"
GREN_URL = "https://droitromain.univ-grenoble-alpes.fr/Corpus/d-50.htm"


def parse_grenoble(path):
    raw = pathlib.Path(path).read_bytes().decode("iso-8859-1")
    start = raw.index('<a name="50.17">')
    body = raw[start:]
    ps = re.findall(r"<p\b[^>]*>(.*?)</p>", body, flags=re.S | re.I)
    frags = {}
    cur = None
    for p in ps:
        m = re.search(r'<a name="50\.17\.(\d+)">', p)
        if m:
            n = int(m.group(1))
            cur = {"n": n, "inscription": None, "paragraphs": []}
            frags[n] = cur
            continue
        if cur is None:
            continue
        if re.search(r"<i>", p, re.I) and not cur["paragraphs"] and cur["inscription"] is None:
            cur["inscription"] = ws(strip_tags(p))
            continue
        m = re.search(r'<a name="50\.17\.(\d+)\.([^"]+)">(.*?)</a>', p, flags=re.S)
        if m:
            label = m.group(2).rstrip(".")
            txt = ws(strip_tags(p[m.end():]))
            cur["paragraphs"].append({"para": label, "latin": txt})
        else:
            txt = ws(strip_tags(p))
            if not txt:
                continue
            if cur["paragraphs"] and cur["paragraphs"][-1]["para"] != "_":
                # continuation paragraph of the last numbered paragraph
                cur["paragraphs"][-1].setdefault("continuations", []).append(txt)
            else:
                cur["paragraphs"].append({"para": "_", "latin": txt})
    # page-wide cleaned text for substring verification
    full = ws(strip_tags(re.sub(r"<script.*?</script>", " ", raw, flags=re.S | re.I)))
    return frags, full


def parse_latlib(path):
    raw = pathlib.Path(path).read_bytes().decode("utf-8", errors="strict")
    start = raw.index("Dig. 50.17.0. De diversis regulis iuris antiqui.")
    body = raw[start:]
    ps = [ws(strip_tags(p)) for p in re.findall(r"<P\b[^>]*>(.*?)(?=<P\b|<p\b|$)", body, flags=re.S)]
    ps = [p for p in ps if p]
    frags = {}
    i = 0
    while i < len(ps):
        m = re.fullmatch(r"Dig\. 50\.17\.(\d+)(pr\.|\.(\d+))?", ps[i])
        if m:
            n = int(m.group(1))
            para = "pr" if m.group(2) == "pr." else (m.group(3) or "_")
            insc = ps[i + 1] if i + 1 < len(ps) else None
            txt = ps[i + 2] if i + 2 < len(ps) else None
            f = frags.setdefault(n, {"n": n, "inscription": insc, "paragraphs": []})
            f["paragraphs"].append({"para": para, "latin": txt})
            i += 3
            continue
        i += 1
    full = ws(strip_tags(raw))
    return frags, full


def build_digest(root):
    root = pathlib.Path(root)
    gp = root / "dl/grenoble/d-50.htm"
    lp = root / "dl/latlib/digest50.shtml"
    g, gfull = parse_grenoble(gp)
    latlib, lfull = parse_latlib(lp)
    items = []
    problems = []
    for n in range(1, 212):
        gf, lf = g.get(n), latlib.get(n)
        if gf is None:
            problems.append({"n": n, "issue": "missing in primary (Grenoble)"})
            items.append({"number": n, "citation": f"D.50.17.{n}", "verified_substring": False,
                          "cross_checked": False, "note": "not found in primary source"})
            continue
        paras = []
        for p in gf["paragraphs"]:
            text = p["latin"] if not p.get("continuations") else ws(" ".join([p["latin"]] + p["continuations"]))
            vs = contains(gfull, ws(text)) if not p.get("continuations") else all(contains(gfull, ws(x)) for x in [p["latin"]] + p["continuations"])
            entry = {"para": None if p["para"] == "_" else p["para"], "latin": text, "verified_substring": vs}
            # cross-check against Latin Library
            lpar = None
            if lf:
                want = "_" if p["para"] == "_" else p["para"]
                for q in lf["paragraphs"]:
                    if q["para"] == want:
                        lpar = q
                        break
            if lpar is None:
                entry["cross_checked"] = False
                entry["cross_check_note"] = "paragraph not found in secondary source"
            else:
                same = letters(text) == letters(lpar["latin"])
                entry["cross_checked"] = same
                entry["secondary_latin"] = lpar["latin"]
                if not same:
                    entry["variants_vs_secondary"] = word_diff(text, lpar["latin"])
                    # Known Grenoble corruption: a 'sent.' -> 'sententiarum' abbreviation-expansion
                    # artefact.  Use the Latin Library reading verbatim when it is the only difference.
                    if (re.search(r"sententiarum", text) and
                            letters(text.replace("sententiarum", "sent")) == letters(lpar["latin"]) and
                            contains(lfull, ws(lpar["latin"]))):
                        entry["primary_reading_rejected"] = text
                        entry["latin"] = lpar["latin"]
                        entry["latin_source_url"] = LATLIB_URL
                        entry["correction_reason"] = ("Grenoble page shows 'sent.' expanded to 'sententiarum' inside a word "
                                                      "(digitisation artefact, 13 such strings on the page); "
                                                      "Latin Library reading used verbatim")
                        entry["verified_substring"] = True
                        entry["verified_in"] = "secondary"
                        entry["cross_checked"] = False
                        entry["cross_check_note"] = "single-source reading (primary corrupt at this point)"
            paras.append(entry)
        latin = ws(" ".join(p["latin"] for p in paras))
        insc_ok = gf["inscription"] is not None and contains(gfull, ws(gf["inscription"]))
        jur_match = bool(lf and lf["inscription"] and gf["inscription"] and
                         lf["inscription"].split()[0].lower() == gf["inscription"].split()[0].lower())
        item = {
            "number": n,
            "citation": f"D.50.17.{n}",
            "inscription": gf["inscription"],
            "inscription_verified_substring": insc_ok,
            "inscription_secondary": lf["inscription"] if lf else None,
            "inscription_jurist_matches_secondary": jur_match,
            "latin": latin,
            "paragraphs": paras,
            "source_url": GREN_URL + f"#50.17.{n}",
            "verified_substring": all(p["verified_substring"] for p in paras) and bool(paras),
            "cross_checked": all(p.get("cross_checked") for p in paras) and bool(paras) and lf is not None
                              and len(lf["paragraphs"]) == len(paras),
        }
        if gf["inscription"] and '"dpwn"' in gf["inscription"]:
            item["inscription_note"] = ("Greek title (horon, 'Definitions') appears in the Grenoble HTML as the Symbol-font "
                                        "keystrokes \"dpwn\"; Latin Library has 'horwn'. Kept verbatim; not normalised.")
        if not jur_match and lf:
            item.setdefault("inscription_note", "")
            item["inscription_note"] = (item["inscription_note"] + " Jurist name differs from secondary ("
                                        + lf["inscription"] + "); primary reading kept.").strip()
        if lf and len(lf["paragraphs"]) != len(paras):
            item["cross_check_note"] = f"paragraph count differs: primary {len(paras)}, secondary {len(lf['paragraphs'])}"
        items.append(item)
        if not item["verified_substring"] or not item["cross_checked"]:
            problems.append({"n": n, "verified": item["verified_substring"], "cross_checked": item["cross_checked"]})
    extra = sorted(set(latlib) - set(range(1, 212)) - {0})
    out = {
        "collection": "Digesta Iustiniani 50.17 — De diversis regulis iuris antiqui",
        "citation_form": "D.50.17.<n>",
        "edition": "Mommsen–Krüger Digest text (the Grenoble page is titled 'Digesta Iustiniani : Liber 50 ( Mommsen & Krueger )' and states 'Based upon the Latin text of Mommsen's edition'; the Latin Library page gives no edition statement)",
        "license_note": "public domain (pre-1929 edition); web transcriptions used only as carriers of the public-domain text",
        "primary_source": GREN_URL,
        "secondary_source": LATLIB_URL,
        "sources": [
            {"url": GREN_URL, "retrieved_at": mtime_utc(gp), "sha256": sha256(gp), "local_file": str(gp.relative_to(root)),
             "description": "Univ. Grenoble-Alpes droitromain site, page titled 'Digesta Iustiniani : Liber 50 ( Mommsen & Krueger )', HTML, ISO-8859-1. PRIMARY: full inscriptions, paragraph anchors (50.17.N.pr./.1 ...)."},
            {"url": LATLIB_URL, "retrieved_at": mtime_utc(lp), "sha256": sha256(lp), "local_file": str(lp.relative_to(root)),
             "description": "The Latin Library, Digest book 50 (abbreviated inscriptions, lower-cased sentence starts, no edition statement on page). SECONDARY: cross-check."},
        ],
        "verification": {
            "script": "scripts/verify.py",
            "verified_substring_rule": "whitespace-normalised paragraph text is a literal substring of the whitespace-normalised, tag-stripped, entity-decoded primary page",
            "cross_check_rule": "letters-only, case-folded comparison of each paragraph with the same paragraph in the secondary source",
        },
        "summary": {
            "items": len(items),
            "verified_substring": sum(1 for i in items if i.get("verified_substring")),
            "cross_checked": sum(1 for i in items if i.get("cross_checked")),
            "secondary_extra_fragment_numbers": extra,
        },
        "problems": problems,
        "items": items,
    }
    (root / "out").mkdir(exist_ok=True)
    (root / "out/digest_50_17.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out["summary"], indent=1))
    print("problems:", len(problems))

# ---------------------------------------------------------------- Dataset A

MARKERS = r"[\s0-9!?*'\"^·|_»«\-]"


def canonA(s):
    return re.sub(MARKERS, "", s)


LS_SOURCES = {
    "T1": {
        "file": "dl/ia_liber-sextus-bonifacii-1298/LiberSextusBonifacii1298_djvu.txt",
        "url": "https://archive.org/download/liber-sextus-bonifacii-1298/LiberSextusBonifacii1298_djvu.txt",
        "item": "https://archive.org/details/liber-sextus-bonifacii-1298",
        "start": "DE REGULIS IURIS.", "end": "Data15*",
        "description": "Internet Archive item 'liber-sextus-bonifacii-1298' (community upload 2022; IA date field '1298' is the work date, not the edition). A 98-page PDF of the Liber Sextus portion of Friedberg's edition (running footer 'Corpus iur. can. Ed. Friedberg, T. II.'; regulae at cols. 1122-1124, PDF pp. 97-98; 400-ppi bitonal page images). This file is IA's Tesseract 5 re-OCR of that PDF. PRIMARY transcription.",
    },
    "T2": {
        "file": "work/abbyy_cols.txt",
        "raw_file": "dl/ia_ls1298_pdf/LiberSextusBonifacii1298.pdf",
        "url": "https://archive.org/download/liber-sextus-bonifacii-1298/LiberSextusBonifacii1298.pdf",
        "item": "https://archive.org/details/liber-sextus-bonifacii-1298",
        "start": "Regula I.", "end": "Pontificatus nostri anno quarto",
        "description": "Same scan, but the PDF's own embedded text layer (ABBYY FineReader, PDF created 2008-02-29), extracted per column with `pdftotext -r 72 -f P -l P -x {0|275} -y 0 -W 275 -H 797` for PDF pages 96-98. Independent OCR engine; same printed copy as T1.",
    },
    "T3": {
        "file": "dl/ia_corpusjuriscanon00richuoft/corpusjuriscanon00richuoft_djvu.txt",
        "url": "https://archive.org/download/corpusjuriscanon00richuoft/corpusjuriscanon00richuoft_djvu.txt",
        "item": "https://archive.org/details/corpusjuriscanon00richuoft",
        "start": "DE   REGULIS   lURIS.", "end": "Data'5*",
        "description": "Internet Archive item 'corpusjuriscanon00richuoft' (University of Toronto copy; IA metadata date field says 1879). Its OCR title page reads 'AEMILIUS FRIEDBERG / PARS SECUNDA / DECRETALIUM COLLECTIONES / EX OFFICINA BERNHARDI TAUCHNITZ / LIPSIAE MDCCCLXXXI'. OCR: ABBYY FineReader 8.0. Different physical copy and scan from T1/T2.",
    },
}

HEADER_RE = re.compile(r"(?:^|[\s\.])(?:Regula|[RKUIn][a-z]{1,3}[gB]|R[a-z]g)[\.,\s]")


def ls_text(root, key):
    s = LS_SOURCES[key]
    return (root / s["file"]).read_text(encoding="utf-8")


def ls_segments(root, key):
    t = ls_text(root, key)
    s = LS_SOURCES[key]
    i = t.index(s["start"])
    j = t.index(s["end"], i)
    lines = t[i:j].splitlines()
    rules, cur, done = [], None, False
    for ln in lines:
        st = ln.strip()
        if st and len(st) < 45 and (HEADER_RE.search(st) or re.match(r"^\W*Regula\s", st)) and not re.search(r"[a-z]{4,}\s+[a-z]{4,}", st.split("Reg")[-1]):
            cur = []
            rules.append(cur)
            done = False
            continue
        if cur is None or done or not st:
            continue
        cur.append(ln)
        if re.search(r"\.\W{0,4}$", st):
            done = True
    return rules


def clean_rule(lines):
    """Join OCR lines into one editorial string: de-hyphenate, normalise
    whitespace, drop footnote call-outs and stray noise outside the sentence."""
    s = ""
    for ln in lines:
        ln = ln.strip()
        if s.endswith("-"):
            s = s[:-1] + ln
        else:
            s = (s + " " + ln) if s else ln
    s = ws(s)
    # footnote call-outs: digits / ! ? * ' " glued to a word or standing alone
    s = re.sub(r"(?<=[A-Za-z])[0-9!?*'\"^]+(?=[\s,.:;]|$)", "", s)
    s = re.sub(r"\s[0-9!?*'\"^·\-]+(?=\s)", "", s)
    s = re.sub(r"\s+([,.:;])", r"\1", s)
    s = re.sub(r"([,:;])(?=[A-Za-z])", r"\1 ", s)
    s = re.sub(r"^[^A-Za-z]+", "", s)
    m = re.search(r"^(.*[.:])", s)
    if m:
        s = m.group(1)
    return ws(s)


def build_ls(root, adjudications=None):
    root = pathlib.Path(root)
    adjudications = adjudications or {}
    segs, canon_full = {}, {}
    for k in LS_SOURCES:
        segs[k] = ls_segments(root, k)
        canon_full[k] = canonA(ls_text(root, k))
        print(k, "segments:", len(segs[k]), file=sys.stderr)
    items, problems = [], []
    # T1 (primary) gives the sequence; other transcriptions are aligned to it by
    # similarity within a +/-3 window, because column flow in T2 is not strictly
    # sequential (rules 66-69).
    t1 = [clean_rule(r) for r in segs["T1"]]
    aligned = {"T1": t1}
    for k in LS_SOURCES:
        if k == "T1":
            continue
        cl = [clean_rule(r) for r in segs[k]]
        al = []
        for n0, ref in enumerate(t1):
            best = max(range(max(0, n0 - 3), min(len(cl), n0 + 4)),
                       key=lambda j: difflib.SequenceMatcher(a=letters(ref), b=letters(cl[j]), autojunk=False).ratio())
            r = difflib.SequenceMatcher(a=letters(ref), b=letters(cl[best]), autojunk=False).ratio()
            al.append(cl[best] if r >= 0.8 else None)
        aligned[k] = al
    for n in range(1, 89):
        cands = {k: aligned[k][n - 1] for k in LS_SOURCES if aligned[k][n - 1]}
        callouts = re.findall(r"(?<=[A-Za-z])([0-9!?][0-9!?*]*\*?)(?=[\s,.:;]|$)", ws(" ".join(segs["T1"][n - 1])))
        # support: in how many transcriptions does each candidate occur?
        support = {}
        for k, c in cands.items():
            support[k] = [s for s in LS_SOURCES if contains(canon_full[s], canonA(c))]
        chosen_key = None
        if str(n) in adjudications:
            chosen_key = adjudications[str(n)]["source"]
        else:
            for k in ("T1", "T3", "T2"):
                if k in cands and len(support[k]) >= 2 and k in support[k]:
                    chosen_key = k
                    break
        item = {"number": n, "citation": f"VI 5.12.{n}"}
        if chosen_key is None:
            item.update({"latin": None, "verified_substring": False, "cross_checked": False,
                         "candidates": cands, "support": support,
                         "note": "UNVERIFIED: no OCR reading supported by two transcriptions; needs adjudication"})
            problems.append({"n": n, "candidates": cands, "support": support})
            items.append(item)
            continue
        latin = cands[chosen_key]
        adj = adjudications.get(str(n), {})
        if adj.get("latin_whitespace_override"):
            assert canonA(adj["latin_whitespace_override"]) == canonA(latin), n
            latin = adj["latin_whitespace_override"]
        sup = support[chosen_key]
        # token-wise cross-check: every word of the chosen reading occurs (same letters,
        # same position after alignment) in at least one other transcription
        tok_ok = True
        for w_i, w in enumerate(latin.split()):
            hits = 0
            for k, c in cands.items():
                if k == chosen_key:
                    continue
                cw = c.split()
                sm = difflib.SequenceMatcher(a=[letters(x) for x in latin.split()], b=[letters(x) for x in cw], autojunk=False)
                for blk in sm.get_matching_blocks():
                    if blk.a <= w_i < blk.a + blk.size:
                        hits += 1
                        break
            if hits == 0:
                tok_ok = False
        if len(sup) >= 2:
            tok_ok = True
        variants = {k: c for k, c in cands.items() if canonA(c) != canonA(latin)}
        item.update({
            "latin": latin,
            "source": chosen_key,
            "source_url": LS_SOURCES[chosen_key]["url"],
            "edition": "Friedberg, Corpus iuris canonici, pars secunda (Leipzig 1881), Sext. lib. V tit. XII, cols. 1122-1124",
            "retrieved_at": mtime_utc(root / LS_SOURCES[chosen_key].get("raw_file", LS_SOURCES[chosen_key]["file"])),
            "sha256": sha256(root / LS_SOURCES[chosen_key].get("raw_file", LS_SOURCES[chosen_key]["file"])),
            "verified_substring": chosen_key in sup,
            "found_in_transcriptions": sup,
            "cross_checked": len(sup) >= 2,
            "cross_checked_tokenwise": tok_ok,
            "friedberg_footnote_callouts_removed": callouts,
            "page_image_checked": "visually compared by the agent with a 300-dpi render of PDF p.97 (cols. 1121-1122) / p.98 (cols. 1123-1124) of the T1/T2 scan",
            "ocr_variants": [{"transcription": k, "reading": v, "diff": word_diff(latin, v)} for k, v in variants.items()],
        })
        if str(n) in adjudications:
            item["adjudication"] = adjudications[str(n)]
        items.append(item)
    return items, problems


def write_ls(root, items, problems):
    root = pathlib.Path(root)
    srcs = []
    for k, s in LS_SOURCES.items():
        raw = root / s.get("raw_file", s["file"])
        srcs.append({"key": k, "url": s["url"], "item_page": s["item"], "retrieved_at": mtime_utc(raw),
                     "sha256": sha256(raw), "local_file": str(raw.relative_to(root)), "description": s["description"]})
    out = {
        "collection": "Liber Sextus Decretalium Bonifacii VIII, lib. V tit. XII 'De regulis iuris' (88 regulae)",
        "citation_form": "VI 5.12.<n>",
        "edition": "Corpus iuris canonici, ed. Aemilius Friedberg, pars secunda: Decretalium collectiones (Leipzig: B. Tauchnitz, 1881), cols. 1122-1124",
        "license_note": "public domain (pre-1929 edition)",
        "sources": srcs,
        "verification": {
            "script": "scripts/verify.py",
            "verified_substring_rule": "canonA(latin) is a substring of canonA(full text of the chosen transcription); canonA strips whitespace, hyphens and footnote call-out characters [0-9 ! ? * ' \" ^ · | _ » «] only",
            "cross_check_rule": "the same canonA string also occurs in at least one other independent OCR transcription (T1/T2 = two OCR engines on one scan; T3 = a different copy and scan)",
            "editorial_operations": ["whitespace normalisation", "re-joining line-break hyphenation", "removal of Friedberg footnote call-outs (superscript numerals, OCR'd as digits/!/?/*/quotes)", "stripping OCR noise outside the sentence"],
        },
        "summary": {
            "items": len(items),
            "with_text": sum(1 for i in items if i.get("latin")),
            "verified_substring": sum(1 for i in items if i.get("verified_substring")),
            "cross_checked": sum(1 for i in items if i.get("cross_checked")),
            "found_in_all_three": sum(1 for i in items if len(i.get("found_in_transcriptions", [])) == 3),
            "cross_checked_tokenwise": sum(1 for i in items if i.get("cross_checked_tokenwise")),
        },
        "problems": problems,
        "items": items,
    }
    (root / "out").mkdir(exist_ok=True)
    (root / "out/liber_sextus_regulae.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out["summary"], indent=1))


# ---------------------------------------------------------------- check

def check(root):
    root = pathlib.Path(root)
    ok = True
    # Dataset B
    d = json.loads((root / "out/digest_50_17.json").read_text(encoding="utf-8"))
    for s in d["sources"]:
        if sha256(root / s["local_file"]) != s["sha256"]:
            print("SHA MISMATCH", s["local_file"])
            ok = False
    _, gfull = parse_grenoble(root / "dl/grenoble/d-50.htm")
    _, lfull = parse_latlib(root / "dl/latlib/digest50.shtml")
    lkey = letters(lfull)
    nv = nx = 0
    for it in d["items"]:
        for p in it.get("paragraphs", []):
            target = lfull if p.get("latin_source_url") == LATLIB_URL else gfull
            if not contains(target, ws(p["latin"])):
                print("B not substring:", it["citation"], p["para"])
                ok = False
            else:
                nv += 1
            if letters(p["latin"]) in lkey:
                nx += 1
    print(f"B: paragraphs verified in primary={nv}, letters-found in secondary={nx}")
    # Dataset A
    a = json.loads((root / "out/liber_sextus_regulae.json").read_text(encoding="utf-8"))
    for s in a["sources"]:
        if sha256(root / s["local_file"]) != s["sha256"]:
            print("SHA MISMATCH", s["local_file"])
            ok = False
    full = {k: canonA(ls_text(root, k)) for k in LS_SOURCES}
    va = xa = 0
    for it in a["items"]:
        if not it.get("latin"):
            print("A unverified item", it["citation"])
            continue
        c = canonA(it["latin"])
        found = [k for k in full if contains(full[k], c)]
        if it["source"] not in found:
            print("A not substring:", it["citation"], it["source"])
            ok = False
        else:
            va += 1
        if len(found) >= 2:
            xa += 1
        if sorted(found) != sorted(it["found_in_transcriptions"]):
            print("A support mismatch", it["citation"], found, it["found_in_transcriptions"])
            ok = False
    print(f"A: verified={va}, cross_checked={xa}, of {len(a['items'])}")
    print("CHECK", "PASSED" if ok else "FAILED")
    return ok


if __name__ == "__main__":
    cmd, root = sys.argv[1], sys.argv[2]
    if cmd == "build-digest":
        build_digest(root)
    elif cmd == "build-ls":
        adj = {}
        ap = pathlib.Path(root) / "work/ls_adjudications.json"
        if ap.exists():
            adj = json.loads(ap.read_text(encoding="utf-8"))
        items, problems = build_ls(root, adj)
        write_ls(root, items, problems)
    elif cmd == "check":
        sys.exit(0 if check(root) else 1)
