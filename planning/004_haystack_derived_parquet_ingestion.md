# Haystack Derived Parquet Ingestion

## Context

Several state corpora are available only as normalized parquet files under `data/derived/*/antraege.parquet`.
The existing Haystack CLI could index one parquet file at a time with `index-parquet`, but loading all derived state corpora required a manual loop and rebuilt the indexing pipeline for each file.

## Decision

Add a multi-parquet indexing path that:

- discovers `*/antraege.parquet` files under a derived data directory,
- converts each row to a Haystack `Document` with normalized metadata,
- runs one splitter/embedder/writer pipeline over the combined document list,
- exposes the flow through `spdbe haystack index-derived`.

The existing single-file `index-parquet` command remains supported and now uses the same document conversion helper as the multi-file path.

## Verification Boundary

Focused tests cover parquet discovery, row-to-document conversion, and multi-file pipeline input without requiring a live Elasticsearch instance or embedding model.

An actual indexing run still requires Elasticsearch on `ES_HOST` and the Haystack optional dependencies.
