---
title: Elementless bridge ingest re-read the raw .docx as text and fed ZIP binary to the pipeline
date: 2026-07-07
tags: [ingestion, docx, bridge, boundary-detection, binary, folio-insights, books-uat]
severity: high
area: pipeline/ingestion
symptom: "structure_parser checkpoint elements begin with PK\\x03\\x04 (ZIP header); boundary detection stalls >11 min on 13 giant 'paragraph' elements of binary garbage"
---

## Problem

folio-insights' `IngestionStage` routes `.docx`/`.pdf`/etc. to folio-enrich's
ingestors via the bridge (`ingestion_bridge.detect_and_ingest`). folio-enrich's
`WordIngestor` returns **extracted text but an empty `elements` list**. The
stage's "supplement if the bridge returned no elements" fallback then did:

```python
if not elements:
    raw_content = file_path.read_text(encoding="utf-8", errors="replace")
    ... _parse_plaintext_elements(raw_content)
```

For a `.docx` (a ZIP container) `file_path.read_text()` reads **raw ZIP bytes**
(`PK\x03\x04…`). Those binary "paragraphs" flow downstream: structure_parser
emitted 13 giant elements (one 53k chars), and boundary detection routed every
one into Tier-2/3, stalling for >11 minutes on binary noise (see
`boundary-tier3-serial-llm-stall.md`). The B2 WordIngestor fix correctly
produced 119,594 chars of *text* — but that text was being thrown away and the
raw file re-read instead.

## Root cause

The elementless fallback re-read the file from disk instead of using the
**text the bridge had already extracted**. Correct for markdown (text on disk,
re-read to recover heading levels) but catastrophic for binary container
formats.

## Fix

Build fallback paragraph elements from the **bridge-extracted `text`**, never by
re-reading the raw file — except markdown, which is genuinely text on disk:

```python
if not elements:
    if ext == ".md":
        elements = _parse_markdown_elements(file_path.read_text(...))
    else:
        elements = _parse_plaintext_elements(text)   # bridge text, not raw bytes
```

The chapter's text carries `\n\n` paragraph breaks, so `_parse_plaintext_elements`
yields clean paragraph elements; boundary detection then produced 373 real units
in ~4.7s.

## Lesson

When a bridge returns `(text, elements)` and elements are empty, the recovery
source is the returned text — re-reading the original file silently defeats the
extractor for every binary format. A single "is this text binary?" assertion at
the ingestion boundary (reject `\x00` / `PK\x03\x04` before it becomes a unit)
would have tripped this immediately.
