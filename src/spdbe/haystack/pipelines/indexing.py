"""Indexing pipeline: .md files -> Elasticsearch.

MotionNormalizer -> DocumentSplitter -> Embedder -> DocumentWriter(ES)
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

from haystack import Pipeline
from haystack.components.embedders import SentenceTransformersDocumentEmbedder
from haystack.components.preprocessors import DocumentSplitter
from haystack.components.writers import DocumentWriter
from haystack.document_stores.types import DuplicatePolicy

from spdbe.haystack.components.motion_normalizer import MotionNormalizer
from spdbe.haystack.document_store import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_ES_HOST,
    DEFAULT_INDEX,
    create_document_store,
)


def build_indexing_pipeline(
    es_host: str = DEFAULT_ES_HOST,
    index_name: str = DEFAULT_INDEX,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    boilerplate_index_path: str | None = None,
    landesverband: str = "berlin",
) -> Pipeline:
    """Build the corpus indexing pipeline.

    Stages:
    1. MotionNormalizer: .md files -> normalized Documents
    2. DocumentSplitter: split long motions into chunks (sentence-based)
    3. SentenceTransformersDocumentEmbedder: compute multilingual MiniLM embeddings
    4. DocumentWriter: write to Elasticsearch

    Args:
        es_host: Elasticsearch host URL.
        index_name: ES index name.
        embedding_model: Sentence transformer model name.
        boilerplate_index_path: Path to pre-computed boilerplate index JSON.
        landesverband: State identifier for multi-state corpus.

    Returns:
        Configured Haystack Pipeline ready to run.
    """
    doc_store = create_document_store(hosts=es_host, index=index_name)

    pipe = Pipeline()

    pipe.add_component(
        "normalizer",
        MotionNormalizer(
            boilerplate_index_path=boilerplate_index_path,
            landesverband=landesverband,
        ),
    )
    pipe.add_component(
        "splitter",
        DocumentSplitter(
            split_by="sentence",
            split_length=5,
            split_overlap=1,
            language="de",
        ),
    )
    pipe.add_component(
        "embedder",
        SentenceTransformersDocumentEmbedder(
            model=embedding_model,
            meta_fields_to_embed=["title"],
            normalize_embeddings=True,
            batch_size=64,
        ),
    )
    pipe.add_component(
        "writer",
        DocumentWriter(
            document_store=doc_store,
            policy=DuplicatePolicy.OVERWRITE,
        ),
    )

    pipe.connect("normalizer.documents", "splitter.documents")
    pipe.connect("splitter.documents", "embedder.documents")
    pipe.connect("embedder.documents", "writer.documents")

    return pipe


def run_indexing(
    md_dir: str | Path = "corpus/berlin",
    es_host: str = DEFAULT_ES_HOST,
    index_name: str = DEFAULT_INDEX,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    boilerplate_index_path: str | None = None,
    landesverband: str = "berlin",
    verbose: bool = False,
) -> dict:
    """Run the full indexing pipeline on a corpus directory.

    Returns the pipeline result dict.
    """
    from spdbe.ingest import discover_corpus

    md_dir = Path(md_dir)
    sources = [str(p) for p in discover_corpus(md_dir)]

    if verbose:
        logger.info(f"Found {len(sources)} .md files in {md_dir}")

    pipe = build_indexing_pipeline(
        es_host=es_host,
        index_name=index_name,
        embedding_model=embedding_model,
        boilerplate_index_path=boilerplate_index_path,
        landesverband=landesverband,
    )

    if verbose:
        logger.info("Running indexing pipeline...")

    result = pipe.run({"normalizer": {"sources": sources}})

    if verbose:
        written = result.get("writer", {}).get("documents_written", 0)
        logger.info(f"Indexed {written} documents into {index_name}")

    return result


def build_parquet_indexing_pipeline(
    es_host: str = DEFAULT_ES_HOST,
    index_name: str = DEFAULT_INDEX,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
) -> Pipeline:
    """Build indexing pipeline for pre-normalized parquet data.

    Skips MotionNormalizer — expects Documents already built from parquet rows.
    Stages: DocumentSplitter -> Embedder -> Writer
    """
    doc_store = create_document_store(hosts=es_host, index=index_name)

    pipe = Pipeline()

    pipe.add_component(
        "splitter",
        DocumentSplitter(
            split_by="sentence",
            split_length=5,
            split_overlap=1,
            language="de",
        ),
    )
    pipe.add_component(
        "embedder",
        SentenceTransformersDocumentEmbedder(
            model=embedding_model,
            meta_fields_to_embed=["title"],
            normalize_embeddings=True,
            batch_size=64,
        ),
    )
    pipe.add_component(
        "writer",
        DocumentWriter(
            document_store=doc_store,
            policy=DuplicatePolicy.OVERWRITE,
        ),
    )

    pipe.connect("splitter.documents", "embedder.documents")
    pipe.connect("embedder.documents", "writer.documents")

    return pipe


def run_indexing_from_parquet(
    parquet_path: str | Path,
    es_host: str = DEFAULT_ES_HOST,
    index_name: str = DEFAULT_INDEX,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    verbose: bool = False,
) -> dict:
    """Index pre-normalized parquet data into Elasticsearch.

    Reads parquet rows, converts to Haystack Documents, then runs
    splitter -> embedder -> writer pipeline.
    """
    import pandas as pd
    from haystack import Document

    parquet_path = Path(parquet_path)
    df = pd.read_parquet(parquet_path)

    if verbose:
        logger.info(f"Loaded {len(df)} rows from {parquet_path}")

    # Convert parquet rows to Haystack Documents
    documents = []
    for _, row in df.iterrows():
        content = row.get("text_clean", "") or row.get("text_content", "")
        if not content or len(str(content).strip()) < 10:
            continue

        def _clean(val):
            """Coerce NaN/None to empty string."""
            if val is None or (isinstance(val, float) and pd.isna(val)):
                return ""
            return str(val)

        meta = {
            "kuerzel": _clean(row.get("kuerzel")),
            "title": _clean(row.get("title")),
            "year": int(row["year"]) if pd.notna(row.get("year")) else None,
            "submitter_raw": _clean(row.get("submitter_raw")),
            "submitter_type": _clean(row.get("submitter_type")),
            "status_raw": _clean(row.get("status_raw")),
            "doc_type": _clean(row.get("doc_type")),
            "landesverband": _clean(row.get("landesverband")),
            "content_hash": _clean(row.get("content_hash")),
            "source_url": _clean(row.get("source_url")),
            "source_id": _clean(row.get("source_id")),
            "page_number": int(row["page_number"]) if pd.notna(row.get("page_number")) else None,
        }

        documents.append(Document(
            id=row.get("id", ""),
            content=str(content),
            meta={k: v for k, v in meta.items() if v is not None and v != ""},
        ))

    if verbose:
        logger.info(f"Built {len(documents)} Documents from parquet")

    pipe = build_parquet_indexing_pipeline(
        es_host=es_host,
        index_name=index_name,
        embedding_model=embedding_model,
    )

    result = pipe.run({"splitter": {"documents": documents}})

    if verbose:
        written = result.get("writer", {}).get("documents_written", 0)
        logger.info(f"Indexed {written} documents into {index_name}")

    return result
