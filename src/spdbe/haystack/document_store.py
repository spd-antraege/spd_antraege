"""Elasticsearch document store configuration for SPD Antragskorpus."""

from __future__ import annotations

DEFAULT_INDEX = "spd-motions"
DEFAULT_ES_HOST = "http://localhost:9200"
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIM = 384  # paraphrase-multilingual-MiniLM-L12-v2 output dimension

# Custom German analyzer for BM25 search on political text
ES_INDEX_SETTINGS = {
    "analysis": {
        "analyzer": {
            "german_political": {
                "type": "custom",
                "tokenizer": "standard",
                "filter": [
                    "lowercase",
                    "german_normalization",
                    "german_stemmer",
                ],
            }
        },
        "filter": {
            "german_stemmer": {
                "type": "stemmer",
                "language": "light_german",
            }
        },
    }
}

# Explicit mappings for structured fields
ES_INDEX_MAPPINGS = {
    "properties": {
        # Content fields — searchable with German analyzer
        "content": {"type": "text", "analyzer": "german_political"},
        "title": {"type": "text", "analyzer": "german_political"},
        "submitter_raw": {
            "type": "text",
            "analyzer": "german_political",
            "fields": {"keyword": {"type": "keyword"}},
        },
        # Embedding
        "embedding": {
            "type": "dense_vector",
            "dims": EMBEDDING_DIM,
            "index": True,
            "similarity": "cosine",
        },
        # Keyword fields — exact match, facets, filters
        "id": {"type": "keyword"},
        "kuerzel": {"type": "keyword"},
        "parteitag_id": {"type": "keyword"},
        "doc_type": {"type": "keyword"},
        "status_raw": {"type": "keyword"},
        "submitter_type": {"type": "keyword"},
        "landesverband": {"type": "keyword"},
        "tags_raw": {"type": "keyword"},
        "content_hash": {"type": "keyword"},
        # Numeric fields — range queries, stats
        "year": {"type": "integer"},
        "month": {"type": "integer"},
        "word_count": {"type": "integer"},
        "char_count": {"type": "integer"},
        "tag_count": {"type": "integer"},
        "boilerplate_share": {"type": "float"},
        # Date field
        "parteitag_date": {"type": "date", "format": "yyyy-MM-dd", "ignore_malformed": True},
        # Boolean flags
        "missing_text": {"type": "boolean"},
        "date_parse_ok": {"type": "boolean"},
        "tag_suspect_broad": {"type": "boolean"},
        "conversion_artifacts_hint": {"type": "boolean"},
        # Stored-only text (not indexed for search)
        "text_md": {"type": "text", "index": False},
        "text_plain": {"type": "text", "index": False},
    }
}


def create_document_store(
    hosts: str = DEFAULT_ES_HOST,
    index: str = DEFAULT_INDEX,
):
    """Create an ElasticsearchDocumentStore with German political text config.

    The custom index settings (analyzer, mappings) are applied on first write
    via the embedding_dim and custom_mapping parameters.
    """
    from haystack_integrations.document_stores.elasticsearch import (
        ElasticsearchDocumentStore,
    )

    return ElasticsearchDocumentStore(
        hosts=hosts,
        index=index,
        embedding_similarity_function="cosine",
    )
