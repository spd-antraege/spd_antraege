# Search Mode Routing Plan

## Context

The retrieval eval showed that production `/api/search` fails with HTTP 500 for `mode=bm25` and `mode=vector`, while default hybrid search works.

The local code path always built the hybrid Haystack pipeline. For `bm25` or `vector`, `run_search` omitted one retriever branch, but the hybrid `RRFJoiner` still required both BM25 and embedding document inputs.

## Plan

1. Keep `build_search_pipeline` as the hybrid BM25 + vector + RRF path.
2. Add a BM25-only pipeline for `mode=bm25`.
3. Add a vector-only pipeline for `mode=vector`.
4. Route `run_search` to the matching pipeline shape.
5. Preserve filter handling for all modes.
6. Add unit tests that verify mode routing without requiring Elasticsearch.

## Acceptance Criteria

- `mode=bm25` does not construct or run the hybrid joiner.
- `mode=vector` does not construct or run the hybrid joiner.
- `mode=hybrid` continues to run both retrievers through RRF.
- Unit tests cover routing and result normalization.
- Production `/api/search?mode=bm25` and `mode=vector` can be rechecked after deployment.
