# Synthetic measurement inputs, revision synthetic-v1

`readme.json` transcribes the eight invented README excerpts and independently
authored atomic expectations. The source title retains the README's citation
markup; source text is the verbatim blockquote body without Markdown quote
prefixes. Offsets are half-open Python Unicode character positions in that text.
Spans serialize only `start` and `end`. Use `span.source_slice(source.text)` to
derive their exact supporting text in memory from the digest-validated snapshot.
Serialized excerpt fields (`quote`, `snippet`, `excerpt`, `passage`, `source_text`)
are rejected by the span schema, including empty values.
A rule and its elements may share a complete supporting sentence. Different
occurrences of an identical phrase retain different offsets and item IDs.
Links use document-local item IDs and the five closed relation names from R10.

`evaluation.json` contains eight additional invented document groups, two per
R11 genre. These are evaluator-transfer candidates, **not a secret holdout in
this readable repository**. The orchestrator copies them into restricted
evaluator custody and seals a group-level split in U9. Anyone exposed to these
labels must be excluded from tuning for that split (KTD6). No partition is marked
held-out here. README examples remain public tuning/regression inputs.
Example 6 is synthetic know-how, subgenre `jury-instruction-reference`.
Neither suite is real-corpus evidence.

Gold is marked `draft`: these are author expectations, not measured extraction
output, judge-cross-checked gold, a Damien anchor, or proof of exhaustive tag
recall. U4/U9 must cross-check them, and KTD2's pooled tag adjudication must
complete before definitive tag scoring. Article positions and playbook advice
retain their source attribution; they are not recast as binding legal rules.

`ontology.json` records the 68 selected concepts plus all named superclass
ancestors (165 classes total), copied from the locally available FOLIO OWL
snapshot with SHA-256:

`b6ed82e6d17b7cb1d468453e4111ec08ca091d72a6849be2b58dd37692cb6ef9`

Source: [FOLIO, ALEA Institute](https://github.com/alea-institute/FOLIO),
CC-BY-4.0. This is a recorded subset, not the complete ontology. Each record
retains its actual IRI, English `rdfs:label`, English `skos:altLabel` and
`skos:prefLabel` aliases, and named `rdfs:subClassOf` edges. Anonymous OWL
restrictions are not superclass identities. The referenced OWL Thing root is
included. No README table IRI or branch assignment was used to create the
expectations or ontology records.

`concepts_sha256` hashes the UTF-8 JSON representation of the ordered concepts
list with sorted object keys, no whitespace, and `ensure_ascii=False`. Both gold
suites pin that slice digest and the full OWL digest. The loader verifies the
slice, closure, every selected label, and its path to the specified ancestor.
Resolution prefers an exact canonical label (case-insensitive), then an
unambiguous alternate label; unknown or ambiguous selections fail. Only this
deterministic code returns IRIs. Resolution establishes existence and ancestry;
semantic tag correctness still needs independent adjudication.

Use `folio_insights.measurement.gold.load_gold()` for README gold and pass
`data/measurement/synthetic/evaluation.json` for the transfer suite. Source and
item IDs are stable within a gold revision; item IDs are scoped to a document.
Revisions to the ontology or gold require new pinned evaluator inputs and a
baseline re-run, as required by KTD1/KTD7. No scorer, judge, seal, or extraction
behavior is implemented by these fixtures.
