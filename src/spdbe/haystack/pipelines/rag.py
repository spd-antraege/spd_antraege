"""RAG pipeline: search + prompt + generation.

Search Pipeline output -> PromptBuilder -> AnthropicGenerator
"""

from __future__ import annotations

from typing import Any

from haystack import Pipeline
from haystack.components.builders import PromptBuilder
from haystack.components.embedders import SentenceTransformersTextEmbedder
from haystack.components.generators import OpenAIGenerator
from haystack.utils.auth import Secret
from haystack_integrations.components.retrievers.elasticsearch import (
    ElasticsearchBM25Retriever,
    ElasticsearchEmbeddingRetriever,
)

from spdbe.haystack.components.rrf_joiner import RRFJoiner
from spdbe.haystack.document_store import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_ES_HOST,
    DEFAULT_INDEX,
    create_document_store,
)

# German RAG template for political motion analysis
RAG_TEMPLATE = """\
Du bist ein Experte fuer SPD Berlin Parteipolitik. Beantworte die Frage \
basierend ausschliesslich auf den folgenden Parteitagsantraegen.

{% for doc in documents %}
---
Kuerzel: {{ doc.meta.kuerzel }}
Jahr: {{ doc.meta.year }}
Status: {{ doc.meta.status_raw }}
Antragsteller: {{ doc.meta.submitter_raw }}

{{ doc.content }}
{% endfor %}
---

Frage: {{ query }}

Antworte praezise und belege jede Aussage mit dem Kuerzel des Antrags. \
Wenn die Antraege die Frage nicht beantworten, sage das klar.
"""


def build_rag_pipeline(
    es_host: str = DEFAULT_ES_HOST,
    index_name: str = DEFAULT_INDEX,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    llm_model: str = "claude-sonnet-4-5-20250929",
    top_k: int = 5,
) -> Pipeline:
    """Build the RAG pipeline.

    Retrieval (BM25 + embedding + RRF) -> PromptBuilder -> LLM generation.

    Uses OpenAIGenerator with Anthropic-compatible endpoint for Claude models.

    Args:
        es_host: Elasticsearch host URL.
        index_name: ES index name.
        embedding_model: Sentence transformer model for query embedding.
        llm_model: Anthropic model name for generation.
        top_k: Number of documents to retrieve for context.

    Returns:
        Configured Haystack Pipeline.
    """
    doc_store = create_document_store(hosts=es_host, index=index_name)

    pipe = Pipeline()

    # Retrieval components
    pipe.add_component(
        "text_embedder",
        SentenceTransformersTextEmbedder(
            model=embedding_model,
            normalize_embeddings=True,
        ),
    )
    pipe.add_component(
        "bm25_retriever",
        ElasticsearchBM25Retriever(document_store=doc_store, top_k=top_k * 2),
    )
    pipe.add_component(
        "embedding_retriever",
        ElasticsearchEmbeddingRetriever(document_store=doc_store, top_k=top_k * 2),
    )
    pipe.add_component(
        "joiner",
        RRFJoiner(k=60, top_n=top_k),
    )

    # Generation components
    pipe.add_component(
        "prompt_builder",
        PromptBuilder(template=RAG_TEMPLATE),
    )
    pipe.add_component(
        "llm",
        OpenAIGenerator(
            model=llm_model,
            api_base_url="https://api.anthropic.com/v1/",
            api_key=Secret.from_env_var("ANTHROPIC_API_KEY", strict=False),
        ),
    )

    # Wire retrieval
    pipe.connect("text_embedder.embedding", "embedding_retriever.query_embedding")
    pipe.connect("bm25_retriever.documents", "joiner.bm25_documents")
    pipe.connect("embedding_retriever.documents", "joiner.embedding_documents")

    # Wire generation
    pipe.connect("joiner.documents", "prompt_builder.documents")
    pipe.connect("prompt_builder.prompt", "llm.prompt")

    return pipe


def run_rag(
    query: str,
    es_host: str = DEFAULT_ES_HOST,
    index_name: str = DEFAULT_INDEX,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    llm_model: str = "claude-sonnet-4-5-20250929",
    top_k: int = 5,
    landesverband: str | None = None,
) -> dict:
    """Run a RAG query.

    Returns dict with 'answer', 'sources', and 'query'.
    """
    pipe = build_rag_pipeline(
        es_host=es_host,
        index_name=index_name,
        embedding_model=embedding_model,
        llm_model=llm_model,
        top_k=top_k,
    )

    pipeline_input: dict[str, Any] = {
        "text_embedder": {"text": query},
        "bm25_retriever": {"query": query},
        "prompt_builder": {"query": query},
    }

    if landesverband:
        es_filter = {
            "field": "landesverband",
            "operator": "==",
            "value": landesverband,
        }
        pipeline_input["bm25_retriever"]["filters"] = es_filter
        pipeline_input["embedding_retriever"] = {"filters": es_filter}

    result = pipe.run(pipeline_input)

    answer = ""
    llm_result = result.get("llm", {})
    replies = llm_result.get("replies", [])
    if replies:
        answer = replies[0]

    # Collect sources from joiner output
    sources = []
    joiner_docs = result.get("joiner", {}).get("documents", [])
    for doc in joiner_docs:
        sources.append({
            "kuerzel": doc.meta.get("kuerzel", ""),
            "year": doc.meta.get("year"),
            "title": doc.meta.get("title", ""),
        })

    return {
        "query": query,
        "answer": answer,
        "sources": sources,
    }
