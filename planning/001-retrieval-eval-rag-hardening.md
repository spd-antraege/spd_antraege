# Retrieval Eval and RAG Hardening Plan

## Context

The production service has real indexed corpus access: `/api/health` reports 48,154 documents, `/api/states` reports all 16 state associations, `/api/rag` returns sourced answers, and the public MCP endpoint exposes `corpus_search`.

The setup is still not trustworthy enough for confident policy research because some paths are broken or under-specified:

- Local Elasticsearch is not running by default.
- Local MCP fallback only finds data when `PIS_DATA_DIR=data` is set.
- Public `mode=vector` returns a 500.
- Public MCP graph tools return `No module named 'spdbe.graph'`.
- `/api/rag` lacks retrieval controls such as year filters, mode, and top_k.
- Generated answers are not yet protected by a relevance gate.

## Goal

Make retrieval quality measurable first, then harden `/api/rag` so answer generation only uses relevant, inspectable, cited source material.

## Non-Goals

- Do not tune chunking, boosts, rerankers, or embedding models before baseline metrics exist.
- Do not build a large benchmark initially.
- Do not rely on qualitative inspection as the primary success signal.

## Phase 1: Retrieval Eval Set

Create `evals/retrieval_questions.yaml` with 30 to 50 cases.

Each case should include:

- `id`
- `question`
- `query_type`: `exact_keyword`, `natural_language`, `filtered`, or `negative`
- `filters`: `landesverband`, `year_min`, `year_max`, `status`, `submitter_type`
- `expected_kuerzel`, when known
- `expected_topic`, `expected_year`, or `expected_status`, when exact motion IDs are not known
- `notes`, only for evidence or known ambiguity

Starter topics:

- Mietpreisbremse
- Kita
- Schulmittagessen
- Polizei
- Wohnen
- Energie
- Landesparteitag I/2026
- Negative cases where the honest result should be not found

## Phase 2: Eval Runner

Add `evals/run_retrieval.py`.

The runner should:

- Call the retrieval layer directly.
- Deduplicate results by motion, not chunk.
- Run each case against `bm25`, `vector`, `hybrid`, and `hybrid_with_filters`.
- Run exact keyword and natural-language variants separately where available.
- Emit JSON metrics and a Markdown report.

Metrics:

- Recall@5
- Recall@10
- MRR
- Irrelevant-hit rate
- No-result rate
- Mode failure rate

Report path:

- `evals/reports/YYYY-MM-DD-retrieval.md`

## Phase 3: API Retrieval Controls

Extend `/api/rag` request shape with:

- `year_min`
- `year_max`
- `mode`
- `top_k`
- `submitter_type`
- `status`, if available in the index consistently

Also verify and fix:

- `/api/search?mode=bm25`
- `/api/search?mode=vector`
- `/api/search?mode=hybrid`

## Phase 4: Relevance Gate

Before generation:

1. Retrieve more candidates than needed.
2. Deduplicate by motion.
3. Build exact excerpts from source text.
4. Apply a relevance gate.
5. Generate only from sources that pass the gate.
6. Return not found or not enough evidence if too little passes.

Initial gate can be deterministic:

- Minimum retrieval score by mode.
- Keyword or phrase overlap with title or excerpt.
- Required filter match.
- Topic or expected field match when available.
- Drop sources with only accidental lexical overlap.

## Phase 5: Better RAG Packet Shape

Return enough retrieval evidence to debug answers.

The response should include:

- `query`
- `filters`
- `mode`
- `top_k`
- `not_found`
- `sources[].rank`
- `sources[].score`
- `sources[].kuerzel`
- `sources[].title`
- `sources[].year`
- `sources[].status`
- `sources[].excerpt`
- `sources[].match_reason`
- `sources[].passed_relevance_gate`

Generation must cite only gated sources.

## Phase 6: Query Decomposition

For broad natural-language questions, add deterministic query expansion before any LLM planner.

Example:

Question: "Was sagt die SPD zu bezahlbarem Wohnen?"

Search terms:

- Mietpreisbremse
- Mietendeckel
- Wohnraum
- Mieten
- sozialer Wohnungsbau

Keep expansions inspectable in the response packet.

## Phase 7: Tune Only After Metrics

Tune in this order after the first retrieval report exists:

1. Title boosts.
2. Field boosts.
3. Chunk deduplication.
4. Chunk size and overlap.
5. Reranker.
6. Embedding model.

## Acceptance Criteria

- At least 30 eval cases exist.
- Retrieval report can be regenerated with one command.
- Metrics are reported per retrieval mode.
- `/api/rag` supports filters, mode, and top_k.
- Weak retrieval does not produce confident generated answers.
- Every generated answer cites only gated retrieved sources.
- Broken public modes and MCP graph-tool claims are either fixed or explicitly marked unsupported.
