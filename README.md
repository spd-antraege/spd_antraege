# SPD Anträge

Search and analyze SPD Parteitagsanträge (motions/proposals) across all 16 German state associations.

**Search:** https://spd-antraege.de

## Overview

- **48,000+ documents** indexed across **16 Landesverbände** — all German SPD state associations
- **Haystack v2 pipelines** (indexing, search, RAG, extraction) with Elasticsearch
- **Hybrid search** (BM25 with title boosting + vector + reciprocal rank fusion)
- **Three public interfaces** at spd-antraege.de: Astro frontend, REST API (`/api/`), MCP server (`/mcp/`)
- **MCP server** with 15 tools — public Streamable HTTP, works with any MCP-compatible AI assistant

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│ Scrapers (5 types)                                                  │
│                                                                     │
│   cvtx         Berlin, Brandenburg, Hamburg, Bayern, RLP            │
│   MediaWiki    Schleswig-Holstein                                   │
│   Antragsgrün  Thüringen                                          │
│   PDF+Mistral  NRW, BaWü, Hessen, MV, Sachsen, SA, Bremen, Bund   │
│   PDF (regex)  Niedersachsen                                       │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Haystack Pipeline                                                   │
│   normalize → split (5 sentences) → embed (MiniLM 384d) → write    │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Elasticsearch (48,000+ chunks)                                      │
│   BM25 (title^3 boost) + dense vectors → reciprocal rank fusion     │
└──────────┬─────────────────┬────────────────────┬───────────────────┘
           │                 │                    │
           ▼                 ▼                    ▼
      spd-antraege.de    /api/ (REST)       /mcp/ (MCP)
     Astro + shadcn/ui    FastAPI         Streamable HTTP
```

## Frontend

Astro static site with React + Tailwind CSS + shadcn/ui components. Three tabs:

- **Suche** — hybrid search with collapsible filters (Landesverband, year range, mode), results table, click-to-view motion detail
- **Fragen (RAG)** — ask questions answered by Claude with source citations from the corpus
- **Info** — project overview and stats

```bash
cd frontend
npm install
npx astro dev        # dev server
npx astro build      # static build → dist/
```

The backend serves `frontend/dist/` as static files — no separate frontend server needed in production.

## The Corpus

All 16 Landesverbände indexed in Elasticsearch. 48,154 document chunks from ~6,000 motions.

| Landesverband | Chunks | Technology | PDFs |
|---------------|--------|------------|------|
| Berlin | 18,297 | cvtx | — |
| Schleswig-Holstein | 10,235 | mediawiki | — |
| Brandenburg | 5,060 | cvtx | — |
| Hamburg | 4,549 | cvtx | — |
| Rheinland-Pfalz | 3,644 | cvtx | — |
| Bund | 1,441 | pdf | 6 |
| NRW | 1,251 | pdf (LLM) | 7 |
| Baden-Württemberg | 697 | pdf (LLM) | 5 |
| Hessen | 608 | pdf (LLM) | 5 |
| Thüringen | 483 | antragsgruen | — |
| Sachsen-Anhalt | 451 | pdf (LLM) | 3 |
| Bayern | 421 | cvtx | — |
| Mecklenburg-Vorpommern | 378 | pdf (LLM) | 7 |
| Sachsen | 300 | pdf (LLM) | 2 |
| Bremen | 183 | pdf (LLM) | 1 |
| Niedersachsen | 156 | pdf | 1 |

Source portals use five technologies: cvtx (WordPress plugin), MediaWiki API, Antragsgrün REST API, PDF Antragsbücher parsed with Mistral Small (LLM), and regex-based PDF parsing.

## Why Haystack

The project went through several iterations: RAGFlow, then Dify (with custom Python chunking) for RAG, plus a custom BM25 + LanceDB hybrid search. These worked for Berlin but didn't scale to 16 states:

- **No pipeline serialization.** RAG config was inline code, not reproducible.
- **Tight coupling.** Switching embedding models or vector stores meant rewriting glue code.

[Haystack v2](https://github.com/deepset-ai/haystack) solved these:

- [**DocumentSplitter**](https://github.com/deepset-ai/haystack/blob/main/haystack/components/preprocessors/document_splitter.py) with sentence-based sliding window replaced custom chunking code.
- [**elasticsearch-haystack**](https://github.com/deepset-ai/haystack-core-integrations/tree/main/integrations/elasticsearch) replaced LanceDB — BM25 + dense vector in one index, production-grade.
- **Pipeline serialization** to YAML makes configs reproducible and shareable.

## Structure

```
spd_antraege/
├── frontend/            # Astro + React + shadcn/ui (static build)
├── corpus/berlin/       # 4,200+ Berlin source markdown files
├── src/spdbe/           # Python package (search, API, MCP, extraction)
│   └── haystack/        # Haystack v2 components + pipelines
├── scraper/             # Multi-state scraper (cvtx, mediawiki, PDF)
│   ├── configs/         # Per-state YAML configs
│   └── parsers/         # PDF, cvtx, mediawiki, antragsgruen parsers
├── data/                # Taxonomy, derived parquets, vectors
├── docs/                # Per-state scraper documentation
├── evals/               # Evaluation fixtures
├── configs/             # Pipeline configuration
└── tests/               # Test suite
```

## Key Components

### Haystack v2 Pipelines (`src/spdbe/haystack/`)

4 custom components wrapping existing logic as [Haystack](https://haystack.deepset.ai/) v2 components:

| Component | What it does |
|-----------|-------------|
| `MotionNormalizer` | Parse .md files, normalize dates/submitters, strip markdown, remove boilerplate |
| `MetadataExtractor` | Claude-based extraction of topics, actors, demands, strategy, style |
| `TaxonomyClassifier` | Validate against 184-topic taxonomy, track unmatched signals |
| `RRFJoiner` | Reciprocal Rank Fusion for combining BM25 + embedding results |

4 pipelines (all serializable to YAML):

| Pipeline | Flow |
|----------|------|
| **Indexing** | MotionNormalizer -> DocumentSplitter -> Embedder -> Elasticsearch |
| **Search** | BM25Retriever + EmbeddingRetriever -> RRFJoiner |
| **RAG** | Search -> PromptBuilder (German) -> Anthropic Generator |
| **Extraction** | MetadataExtractor -> TaxonomyClassifier -> Elasticsearch |

```bash
# Index the corpus
spdbe haystack index --input corpus/berlin/ --verbose

# Search
spdbe haystack search "Mietpreisbremse" --landesverband berlin

# Export pipeline as YAML
spdbe haystack export-yaml --pipeline indexing
```

### Hybrid Search (`src/spdbe/search.py`)
Legacy search: BM25 + vector (MiniLM via LanceDB) + reciprocal rank fusion. Still works as fallback for local-only use.

### Public Interfaces (`src/spdbe/server.py`)

Three interfaces served by a single uvicorn process:

| Interface | URL | Description |
|-----------|-----|-------------|
| **Frontend** | `https://spd-antraege.de/` | Astro + shadcn/ui search interface |
| **REST API** | `https://spd-antraege.de/api/` | FastAPI — search, motion detail, RAG, states, health |
| **MCP Server** | `https://spd-antraege.de/mcp/` | Streamable HTTP — any MCP-compatible client |

Connect your AI assistant to the public MCP server:
```json
{"mcpServers": {"spd-antraege": {"type": "url", "url": "https://spd-antraege.de/mcp/"}}}
```

15 MCP tools: corpus_search, graph_query, topic_map, actor_profile, beschlusslage, coalition_finder, failure_analysis, red_line_check, person_lookup, and more.

### Scraping (`scraper/`)

Multi-state scraper pipeline. Each state has a YAML config in `scraper/configs/`.

```bash
# List all states
python -m scraper.pipeline --list

# Scrape a state
python -m scraper.pipeline nrw

# Scrape all states
python -m scraper.pipeline --all

# Index into Elasticsearch
spdbe haystack index-parquet data/derived/nrw/antraege.parquet
```

## Secrets & Environment

**This is a public repo. No secrets are stored in the codebase.**

