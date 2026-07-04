"""Indexing pipeline: .md files -> Elasticsearch.

MotionNormalizer -> DocumentSplitter -> Embedder -> DocumentWriter(ES)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

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


def discover_derived_parquets(derived_dir: str | Path = "data/derived") -> list[Path]:
    """Find normalized state parquet files under a derived data directory."""
    return sorted(Path(derived_dir).glob("*/antraege.parquet"))


def _clean_parquet_value(value, pd) -> str:
    """Coerce pandas scalar values to indexable strings."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value)


def _first_clean_parquet_value(row, field_names: Iterable[str], pd) -> str:
    for field_name in field_names:
        value = _clean_parquet_value(row.get(field_name), pd)
        if value:
            return value
    return ""


def _optional_parquet_int(value, pd) -> int | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def documents_from_parquet(parquet_path: str | Path):
    """Load one normalized parquet file as Haystack Documents."""
    import pandas as pd
    from haystack import Document

    parquet_path = Path(parquet_path)
    df = pd.read_parquet(parquet_path)

    documents = []
    for _, row in df.iterrows():
        content = _first_clean_parquet_value(row, ("text_clean", "text_content"), pd)
        if not content or len(str(content).strip()) < 10:
            continue

        meta = {
            "kuerzel": _first_clean_parquet_value(row, ("kuerzel",), pd),
            "title": _first_clean_parquet_value(row, ("title",), pd),
            "year": _optional_parquet_int(row.get("year"), pd),
            "submitter_raw": _first_clean_parquet_value(row, ("submitter_raw",), pd),
            "submitter_type": _first_clean_parquet_value(row, ("submitter_type",), pd),
            "status_raw": _first_clean_parquet_value(row, ("status_raw",), pd),
            "doc_type": _first_clean_parquet_value(row, ("doc_type",), pd),
            "landesverband": _first_clean_parquet_value(row, ("landesverband",), pd),
            "content_hash": _first_clean_parquet_value(row, ("content_hash",), pd),
            "source_url": _first_clean_parquet_value(row, ("source_url",), pd),
            "source_id": _first_clean_parquet_value(row, ("source_id",), pd),
            "source_doc_id": _first_clean_parquet_value(row, ("source_doc_id",), pd),
            "veranstaltung_raw": _first_clean_parquet_value(
                row,
                ("veranstaltung_raw", "veranstaltung"),
                pd,
            ),
            "page_number": _optional_parquet_int(row.get("page_number"), pd),
        }

        documents.append(Document(
            id=_first_clean_parquet_value(row, ("id",), pd),
            content=str(content),
            meta={k: v for k, v in meta.items() if v is not None and v != ""},
        ))

    return documents


def run_indexing_from_documents(
    documents: list,
    es_host: str = DEFAULT_ES_HOST,
    index_name: str = DEFAULT_INDEX,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    verbose: bool = False,
) -> dict:
    """Index already-built Haystack Documents into Elasticsearch."""
    if verbose:
        logger.info(f"Built {len(documents)} Documents for indexing")

    pipe = build_parquet_indexing_pipeline(
        es_host=es_host,
        index_name=index_name,
        embedding_model=embedding_model,
    )

    result = pipe.run({"splitter": {"documents": documents}})
    result["loader"] = {"documents_loaded": len(documents)}

    if verbose:
        written = result.get("writer", {}).get("documents_written", 0)
        logger.info(f"Indexed {written} documents into {index_name}")

    return result


def run_indexing_from_parquet(
    parquet_path: str | Path,
    es_host: str = DEFAULT_ES_HOST,
    index_name: str = DEFAULT_INDEX,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    verbose: bool = False,
) -> dict:
    """Index one pre-normalized parquet file into Elasticsearch.

    Reads parquet rows, converts to Haystack Documents, then runs
    splitter -> embedder -> writer pipeline.
    """
    parquet_path = Path(parquet_path)
    documents = documents_from_parquet(parquet_path)

    if verbose:
        logger.info(f"Loaded {len(documents)} Documents from {parquet_path}")

    result = run_indexing_from_documents(
        documents=documents,
        es_host=es_host,
        index_name=index_name,
        embedding_model=embedding_model,
        verbose=verbose,
    )
    result["loader"]["parquet_files"] = 1
    result["loader"]["parquet_paths"] = [str(parquet_path)]
    return result


def run_indexing_from_parquets(
    parquet_paths: Iterable[str | Path],
    es_host: str = DEFAULT_ES_HOST,
    index_name: str = DEFAULT_INDEX,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    verbose: bool = False,
) -> dict:
    """Index multiple pre-normalized parquet files into Elasticsearch."""
    paths = [Path(path) for path in parquet_paths]
    if not paths:
        raise ValueError("No parquet files provided")

    documents = []
    for path in paths:
        path_documents = documents_from_parquet(path)
        documents.extend(path_documents)
        if verbose:
            logger.info(f"Loaded {len(path_documents)} Documents from {path}")

    result = run_indexing_from_documents(
        documents=documents,
        es_host=es_host,
        index_name=index_name,
        embedding_model=embedding_model,
        verbose=verbose,
    )
    result["loader"]["parquet_files"] = len(paths)
    result["loader"]["parquet_paths"] = [str(path) for path in paths]
    return result


def run_indexing_from_derived_parquets(
    derived_dir: str | Path = "data/derived",
    es_host: str = DEFAULT_ES_HOST,
    index_name: str = DEFAULT_INDEX,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    verbose: bool = False,
) -> dict:
    """Index all normalized state parquet files from a derived data directory."""
    parquet_paths = discover_derived_parquets(derived_dir)
    if not parquet_paths:
        raise FileNotFoundError(f"No antraege.parquet files found under {derived_dir}")
    return run_indexing_from_parquets(
        parquet_paths=parquet_paths,
        es_host=es_host,
        index_name=index_name,
        embedding_model=embedding_model,
        verbose=verbose,
    )
