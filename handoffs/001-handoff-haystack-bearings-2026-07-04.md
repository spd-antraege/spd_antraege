# Handoff 001 — Haystack System Bearings (2026-07-04)

Orientation session, no code changes. This documents the current state of the
Haystack search stack so a fresh terminal can pick up retrieval work without
re-exploring.

## Session state

- Branch `main`, clean except untracked `uv.lock` (decide: commit or gitignore).
- Last five commits are all retrieval hardening: eval MVP (`b35877f`),
  search-mode routing fix (`fc19963`), production verification (`cce34c7`),
  derived-parquet indexing (`d2594cc`, see `planning/004_haystack_derived_parquet_ingestion.md`).
- No `.agent/next_plan.md` — nothing was queued at last rotation.

## Architecture map

Two search stacks coexist:

- **Production: Haystack + Elasticsearch.** Raw `.md` motions in `corpus/<state>/`
  or normalized parquets in `data/derived/<state>/antraege.parquet` → indexing
  pipeline → ES index `spd-motions` (~48k chunks, 16 Landesverbände) →
  search/RAG pipelines → FastAPI at `/api` (`src/spdbe/server.py` mounts
  API + MCP + Astro frontend).
- **Legacy: LanceDB** in `src/spdbe/search.py` (`HybridSearch`/`FederatedSearch`).
  Only used by `tests/test_search.py` and old MCP paths, not by `/api/search`.

Pipelines (all embed with `paraphrase-multilingual-MiniLM-L12-v2`, 384-dim cosine):

- **Indexing** `src/spdbe/haystack/pipelines/indexing.py:29` —
  MotionNormalizer → DocumentSplitter (sentence, len 5, overlap 1, de) →
  embedder → ES writer. Parquet variants at `indexing.py:295-373` run one
  shared pipeline over all discovered parquets (`spdbe haystack index-derived`).
- **Search** `pipelines/search.py:26` — hybrid = BoostedBM25 (title^3) +
  vector retriever fused via RRF (k=60). `run_search` (`search.py:141`)
  routes mode bm25/vector/hybrid, applies ES filters, dedups by `kuerzel`.
- **RAG** `pipelines/rag.py:51` — hybrid retrieval → German prompt →
  OpenAIGenerator pointed at Anthropic API, default `claude-sonnet-4-5-20250929`.
- **Extraction** `pipelines/extraction.py:21` — MetadataExtractor
  (Haiku, escalates to Sonnet) → TaxonomyClassifier
  (`data/taxonomy/topics.yaml`) → ES writer.

Custom components in `src/spdbe/haystack/components/`: MotionNormalizer
(frontmatter, stable IDs, boilerplate stripping), BoostedBM25Retriever
(multi_match, title^3, fuzziness AUTO), RRFJoiner, MetadataExtractor,
TaxonomyClassifier.

CLI: `spdbe haystack index | search | index-parquet | index-derived | rag |
build-boilerplate | export-yaml`.

Config: `ES_HOST` (default localhost:9200), `ES_INDEX` (default `spd-motions`),
`ANTHROPIC_API_KEY` for RAG/extraction.

## Known inconsistencies (candidate next work)

1. **`POST /api/rag` bypasses the Haystack RAG pipeline.** It runs hybrid
   search, pulls full texts from ES, and calls the Anthropic SDK directly
   (`src/spdbe/api.py:251`). `pipelines/rag.py` is only reachable via CLI.
   Two divergent RAG implementations that will drift.
2. **Custom ES mapping is dead config.** `document_store.py:11-79` defines a
   `german_political` analyzer and explicit mappings (incl. dense_vector 384),
   but `create_document_store` (`:95`) never passes them — the index uses the
   Haystack integration defaults.
3. **RAG retrieval quality differs from search.** `rag.py` uses plain
   `ElasticsearchBM25Retriever`, search uses BoostedBM25 with title boost.

## Test coverage

Good units: components, converters, mode routing
(`tests/test_haystack_components.py::TestSearchModeRouting`), parquet indexing
(`tests/test_haystack_indexing.py`). Gaps: no live-ES integration test for
`run_search`/`run_rag`, no MetadataExtractor test, FastAPI routes untested.

## Next concrete step

Pick one of the inconsistencies above; recommended: unify RAG by making
`/api/rag` call `run_rag` from `pipelines/rag.py` (or explicitly retire
`rag.py` and document why the inline implementation wins). Verify with
`pytest` locally, `pytest -m integration` needs ES running.
