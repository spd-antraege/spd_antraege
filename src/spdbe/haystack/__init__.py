"""Haystack v2 integration for SPD Berlin Antragskorpus.

Components:
    MotionNormalizer — Parse .md files -> normalized Documents
    MetadataExtractor — Claude-based intelligence extraction
    TaxonomyClassifier — Validate taxonomy + track unmatched signals
    RRFJoiner — Reciprocal Rank Fusion for hybrid search

Pipelines (build functions):
    build_indexing_pipeline — .md files -> ES
    build_search_pipeline — hybrid BM25 + embedding retrieval
    build_bm25_search_pipeline — BM25-only retrieval
    build_vector_search_pipeline — embedding-only retrieval
    build_rag_pipeline — retrieval + generation
    build_extraction_pipeline — LLM extraction + taxonomy validation
"""

from spdbe.haystack.components.metadata_extractor import MetadataExtractor
from spdbe.haystack.components.motion_normalizer import MotionNormalizer
from spdbe.haystack.components.rrf_joiner import RRFJoiner
from spdbe.haystack.components.taxonomy_classifier import TaxonomyClassifier
from spdbe.haystack.pipelines.extraction import build_extraction_pipeline
from spdbe.haystack.pipelines.indexing import build_indexing_pipeline
from spdbe.haystack.pipelines.rag import build_rag_pipeline
from spdbe.haystack.pipelines.search import (
    build_bm25_search_pipeline,
    build_search_pipeline,
    build_vector_search_pipeline,
)

__all__ = [
    "MotionNormalizer",
    "MetadataExtractor",
    "TaxonomyClassifier",
    "RRFJoiner",
    "build_indexing_pipeline",
    "build_search_pipeline",
    "build_bm25_search_pipeline",
    "build_vector_search_pipeline",
    "build_rag_pipeline",
    "build_extraction_pipeline",
]
