"""Extraction pipeline: enrich documents with LLM intelligence.

documents -> MetadataExtractor -> TaxonomyClassifier -> DocumentWriter(ES)
"""

from __future__ import annotations

from haystack import Pipeline
from haystack.components.writers import DocumentWriter
from haystack.document_stores.types import DuplicatePolicy

from spdbe.haystack.components.metadata_extractor import MetadataExtractor
from spdbe.haystack.components.taxonomy_classifier import TaxonomyClassifier
from spdbe.haystack.document_store import (
    DEFAULT_ES_HOST,
    DEFAULT_INDEX,
    create_document_store,
)


def build_extraction_pipeline(
    es_host: str = DEFAULT_ES_HOST,
    index_name: str = DEFAULT_INDEX,
    taxonomy_path: str = "data/taxonomy/topics.yaml",
    model: str = "claude-haiku-4-5-20251001",
    escalation_model: str = "claude-sonnet-4-5-20250929",
    escalation_threshold: float = 0.7,
    proposal_threshold: int = 5,
) -> Pipeline:
    """Build the intelligence extraction pipeline.

    Documents are fed in externally (read from ES or parquet).
    Pipeline enriches them with LLM extraction, validates taxonomy,
    and writes back to ES.

    Args:
        es_host: Elasticsearch host URL.
        index_name: ES index name.
        taxonomy_path: Path to taxonomy YAML.
        model: Primary extraction model (Haiku).
        escalation_model: Escalation model (Sonnet).
        escalation_threshold: Confidence threshold for escalation.
        proposal_threshold: Signal count threshold for taxonomy proposals.

    Returns:
        Configured Haystack Pipeline.
    """
    doc_store = create_document_store(hosts=es_host, index=index_name)

    pipe = Pipeline()

    pipe.add_component(
        "extractor",
        MetadataExtractor(
            taxonomy_path=taxonomy_path,
            model=model,
            escalation_model=escalation_model,
            escalation_threshold=escalation_threshold,
        ),
    )
    pipe.add_component(
        "classifier",
        TaxonomyClassifier(
            taxonomy_path=taxonomy_path,
            proposal_threshold=proposal_threshold,
        ),
    )
    pipe.add_component(
        "writer",
        DocumentWriter(
            document_store=doc_store,
            policy=DuplicatePolicy.OVERWRITE,
        ),
    )

    pipe.connect("extractor.documents", "classifier.documents")
    pipe.connect("classifier.documents", "writer.documents")

    return pipe
