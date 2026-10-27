# Federal statutes and regulations: tuning gold draft

This U12 package contains six acquired tuning selections and 98 draft atomic
propositions. Each source appears once in `text/`, addressed by its SHA-256.
Proposition support uses half-open Unicode code-point offsets into that selection.
`origin_span` retains the selection's coordinates in the evaluator's canonical
source; `request.span` uses the exported selection's coordinates.

`manifest.json` follows U10's tuning export shape. It contains no original download
bytes, held-out records, or judge rationales. Gold remains `draft`; this package is
unsealed. The score label remains **judge agreement, unanchored**. No extraction
score, independent cross-check, complete pooled tag set, or human anchor is claimed.

`ontology.json` pins the author-selected FOLIO classes and their complete named
ancestor closure from the locally cached OWL snapshot (CC BY 4.0, ALEA Institute).
`resolved-tags.json` records deterministic identities and ancestor paths for every
label/branch selection used here. Identity resolution establishes that the tags
exist in FOLIO; the judges must still assess their meaning and propose missing tags
under KTD2. The snapshot digest differs from the synthetic suite's pinned version;
freeze compatible evaluator inputs and re-baseline rather than compare across that
version change.

The selections retain their acquisition spelling and boundaries, including a PDF
word break in `fed-sr-01` and the incomplete enumeration at the end of `fed-sr-06`.
Gold covers only the retained material. It does not infer omitted conditions or
claim a complete section. The holder-notice provisions in `fed-sr-07` are annotated
as required notice contents, preserving their legal context.

The orchestrator owns independent Codex/Claude cross-check coverage, pooled-tag
adjudication, disagreement resolutions, and sealing. This worker authored held-out
gold in evaluator custody and must not tune candidates for this split (KTD6).
Keep the acquisition backup and draft history when adjudicating. U10 sealing needs
a fresh tuning-output directory; seal the cross-checked version to a new directory
before replacing this draft export.

Offline cell verification (U5's package entry point is not yet merged):

```sh
"$FOLIO_PYTHON" -m folio_insights.measurement.cli corpus verify \
  --evaluator-root "/home/damienriehl/Coding Projects/folio-insights/output/measurement/corpus/federal/statutes-regulations" \
  --jurisdiction federal --genre statutes-regulations --require-documents 8
```

The sanitized batch status and pending live prerequisites are recorded in
`data/measurement/receipts/corpus/federal-statutes-regulations.json`.
