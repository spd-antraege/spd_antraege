"""Search pipeline: hybrid BM25 + embedding retrieval with RRF.

query -> BM25Retriever + EmbeddingRetriever -> RRFJoiner -> results
"""

from __future__ import annotations

from typing import Any

from haystack import Pipeline
from haystack.components.embedders import SentenceTransformersTextEmbedder
from haystack_integrations.components.retrievers.elasticsearch import (
    ElasticsearchEmbeddingRetriever,
)

from spdbe.haystack.components.boosted_bm25 import BoostedBM25Retriever
from spdbe.haystack.components.rrf_joiner import RRFJoiner
from spdbe.haystack.document_store import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_ES_HOST,
    DEFAULT_INDEX,
    create_document_store,
)


def build_search_pipeline(
    es_host: str = DEFAULT_ES_HOST,
    index_name: str = DEFAULT_INDEX,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    top_k: int = 20,
    rrf_k: int = 60,
) -> Pipeline:
    """Build the hybrid search pipeline.

    Two parallel retrieval paths fused with RRF:
    1. BM25 (keyword) via Elasticsearch german_political analyzer
    2. Embedding (semantic) via multilingual MiniLM cosine similarity

    Args:
        es_host: Elasticsearch host URL.
        index_name: ES index name.
        embedding_model: Sentence transformer model for query embedding.
        top_k: Number of results per retriever (before fusion).
        rrf_k: RRF constant (higher = more weight to lower ranks).

    Returns:
        Configured Haystack Pipeline.
    """
    doc_store = create_document_store(hosts=es_host, index=index_name)

    pipe = Pipeline()

    pipe.add_component(
        "text_embedder",
        SentenceTransformersTextEmbedder(
            model=embedding_model,
            normalize_embeddings=True,
        ),
    )
    pipe.add_component(
        "bm25_retriever",
        BoostedBM25Retriever(
            document_store=doc_store,
            top_k=top_k,
            title_boost=3,
        ),
    )
    pipe.add_component(
        "embedding_retriever",
        ElasticsearchEmbeddingRetriever(
            document_store=doc_store,
            top_k=top_k,
        ),
    )
    pipe.add_component(
        "joiner",
        RRFJoiner(k=rrf_k, top_n=top_k),
    )

    # Wire: text_embedder output -> embedding_retriever input
    pipe.connect("text_embedder.embedding", "embedding_retriever.query_embedding")
    # Wire: both retrievers -> joiner
    pipe.connect("bm25_retriever.documents", "joiner.bm25_documents")
    pipe.connect("embedding_retriever.documents", "joiner.embedding_documents")

    return pipe


def build_bm25_search_pipeline(
    es_host: str = DEFAULT_ES_HOST,
    index_name: str = DEFAULT_INDEX,
    top_k: int = 20,
) -> Pipeline:
    """Build a BM25-only search pipeline.

    The hybrid pipeline's joiner requires both BM25 and embedding inputs.
    BM25-only mode therefore needs its own pipeline shape.
    """
    doc_store = create_document_store(hosts=es_host, index=index_name)

    pipe = Pipeline()
    pipe.add_component(
        "bm25_retriever",
        BoostedBM25Retriever(
            document_store=doc_store,
            top_k=top_k,
            title_boost=3,
        ),
    )
    return pipe


def build_vector_search_pipeline(
    es_host: str = DEFAULT_ES_HOST,
    index_name: str = DEFAULT_INDEX,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    top_k: int = 20,
) -> Pipeline:
    """Build a vector-only search pipeline."""
    doc_store = create_document_store(hosts=es_host, index=index_name)

    pipe = Pipeline()
    pipe.add_component(
        "text_embedder",
        SentenceTransformersTextEmbedder(
            model=embedding_model,
            normalize_embeddings=True,
        ),
    )
    pipe.add_component(
        "embedding_retriever",
        ElasticsearchEmbeddingRetriever(
            document_store=doc_store,
            top_k=top_k,
        ),
    )
    pipe.connect("text_embedder.embedding", "embedding_retriever.query_embedding")
    return pipe


def run_search(
    query: str,
    es_host: str = DEFAULT_ES_HOST,
    index_name: str = DEFAULT_INDEX,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    top_k: int = 20,
    landesverband: str | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    submitter_type: str | None = None,
    mode: str = "hybrid",
) -> list[dict]:
    """Run a search query and return results.

    Args:
        query: Search query string.
        mode: "hybrid" (BM25+embedding+RRF), "bm25", or "vector".
        landesverband: Filter by state (e.g. "berlin", "bayern").
        year_min/year_max: Year range filter.
        submitter_type: Filter by submitter type.

    Returns:
        List of result dicts with doc_id, score, kuerzel, title, year, snippet.
    """
    if mode not in ("hybrid", "bm25", "vector"):
        raise ValueError("mode must be hybrid, bm25, or vector")

    # Build Elasticsearch filters
    filters = _build_filters(landesverband, year_min, year_max, submitter_type)

    if mode == "bm25":
        pipe = build_bm25_search_pipeline(
            es_host=es_host,
            index_name=index_name,
            top_k=top_k,
        )
        pipeline_input: dict[str, Any] = {"bm25_retriever": {"query": query}}
        if filters:
            pipeline_input["bm25_retriever"]["filters"] = filters
        result = pipe.run(pipeline_input)
        documents = result.get("bm25_retriever", {}).get("documents", [])

    elif mode == "vector":
        pipe = build_vector_search_pipeline(
            es_host=es_host,
            index_name=index_name,
            embedding_model=embedding_model,
            top_k=top_k,
        )
        pipeline_input = {"text_embedder": {"text": query}}
        if filters:
            pipeline_input["embedding_retriever"] = {"filters": filters}
        result = pipe.run(pipeline_input)
        documents = result.get("embedding_retriever", {}).get("documents", [])

    else:
        pipe = build_search_pipeline(
            es_host=es_host,
            index_name=index_name,
            embedding_model=embedding_model,
            top_k=top_k,
        )
        pipeline_input = {
            "bm25_retriever": {"query": query},
            "text_embedder": {"text": query},
        }
        if filters:
            pipeline_input["bm25_retriever"]["filters"] = filters
            pipeline_input["embedding_retriever"] = {"filters": filters}
        result = pipe.run(pipeline_input)
        documents = result.get("joiner", {}).get("documents", [])

    # Convert to result dicts, deduplicating chunks by kuerzel (keep highest score)
    seen: set[str] = set()
    results = []
    for doc in documents:
        k = doc.meta.get("kuerzel", "")
        if k and k in seen:
            continue
        if k:
            seen.add(k)
        results.append({
            "doc_id": doc.id,
            "score": round(doc.score, 4) if doc.score else 0,
            "kuerzel": k,
            "title": doc.meta.get("title", ""),
            "year": doc.meta.get("year"),
            "status": doc.meta.get("status_raw", ""),
            "submitter_type": doc.meta.get("submitter_type", ""),
            "landesverband": doc.meta.get("landesverband", ""),
            "snippet": (doc.content or "")[:300],
        })
    return results


def _build_filters(
    landesverband: str | None,
    year_min: int | None,
    year_max: int | None,
    submitter_type: str | None,
) -> dict | None:
    """Build Elasticsearch filter dict in Haystack v2 format."""
    conditions = []

    if landesverband:
        conditions.append({
            "field": "landesverband",
            "operator": "==",
            "value": landesverband,
        })
    if year_min is not None:
        conditions.append({
            "field": "year",
            "operator": ">=",
            "value": year_min,
        })
    if year_max is not None:
        conditions.append({
            "field": "year",
            "operator": "<=",
            "value": year_max,
        })
    if submitter_type:
        conditions.append({
            "field": "submitter_type",
            "operator": "==",
            "value": submitter_type,
        })

    if not conditions:
        return None

    if len(conditions) == 1:
        return conditions[0]

    return {"operator": "AND", "conditions": conditions}
