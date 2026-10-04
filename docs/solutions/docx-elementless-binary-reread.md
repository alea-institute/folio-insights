---
title: Elementless bridge ingest re-read the raw .docx file and fed container bytes to the pipeline
date: 2026-10-04
tags: [ingestion, docx, bridge, boundary-detection, binary, folio-insights]
severity: high
area: pipeline/ingestion
symptom: "Structured elements start with a ZIP header (PK\\x03\\x04); boundary detection stalls on a few giant binary 'paragraphs'"
status: fixed
related: [boundary-tier3-serial-llm-stall.md]
---

# Elementless ingest re-read the raw binary file (binary re-read)

_Re-authored with the code on 2026-10-04 (proposed-class governance plan, U3) from a learning
on the unmerged `feat/proposed-class-governance` branch._

## Problem

`IngestionStage` routes `.docx`, `.pdf` and similar files to folio-enrich's ingestors through
the bridge. The Word ingestor returns the extracted text but an empty element list. The
stage's fallback for elementless results then re-read the original file with `read_text`. For
a `.docx`, which is a ZIP container, that yields the container bytes. Those became a handful
of enormous garbage paragraphs, which boundary detection then tried to refine.

## Root cause

The fallback used the file on disk instead of the text the bridge had already extracted.
That is right for Markdown (plain text on disk, re-read to recover heading levels) and wrong
for every binary format.

## Fix

When the bridge returns no elements, Markdown is still re-read from disk; every other format
builds paragraph elements from the bridge-extracted `text`
(`src/folio_insights/pipeline/stages/ingestion.py`).

## Lesson

When an extractor returns `(text, elements)` and the elements are empty, recover from the
returned text. Re-reading the original file silently defeats the extractor for every binary
format.

## Tests

`tests/test_extraction_safeguards.py::test_elementless_docx_uses_bridge_text_not_raw_bytes`.
