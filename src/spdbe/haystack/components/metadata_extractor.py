"""MetadataExtractor: Claude-based intelligence extraction as Haystack component.

Wraps extraction.extract_single to enrich Documents with topics, actors,
demands, strategy, and style metadata via LLM.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import List, Optional

from haystack import Document, component, logging

try:
    from spdbe.extraction import _build_taxonomy_reference, extract_single
except ImportError:
    _build_taxonomy_reference = None
    extract_single = None
from spdbe.haystack.converters import document_to_record

logger = logging.getLogger(__name__)


@component
class MetadataExtractor:
    """Extract structured intelligence from SPD motions using Claude.

    For each input Document, calls Claude to extract:
    - topics (primary, secondary, micro_tags)
    - actors (addressees, mentioned)
    - demands (text, type, strength)
    - strategy (framing, coalition_potential, vulnerability)
    - style (register, complexity, persuasion_mode)
    - connections (responds_to_external, unmatched_signals)

    Low-confidence extractions are escalated to a stronger model.
    Results are stored in Document.meta["intelligence"].
    """

    def __init__(
        self,
        taxonomy_path: str = "data/taxonomy/topics.yaml",
        model: str = "claude-haiku-4-5-20251001",
        escalation_model: str = "claude-sonnet-4-5-20250929",
        escalation_threshold: float = 0.7,
    ):
        self.taxonomy_path = taxonomy_path
        self.model = model
        self.escalation_model = escalation_model
        self.escalation_threshold = escalation_threshold
        # Lazy-init for YAML serializability
        self._client = None
        self._taxonomy_ref: str | None = None

    def warm_up(self):
        """Initialize Anthropic client and taxonomy reference."""
        import anthropic

        self._client = anthropic.Anthropic()
        self._taxonomy_ref = _build_taxonomy_reference(Path(self.taxonomy_path))

    @component.output_types(documents=List[Document])
    def run(self, documents: List[Document]) -> dict:
        """Extract intelligence from each document.

        Args:
            documents: List of Documents with content and metadata.

        Returns:
            dict with "documents" containing enriched Documents.
        """
        if self._client is None or self._taxonomy_ref is None:
            self.warm_up()

        enriched = []
        for doc in documents:
            record = document_to_record(doc)

            try:
                result = extract_single(
                    record, self._taxonomy_ref, self._client, model=self.model
                )

                # Escalate if low confidence
                if result.get("confidence", 0) < self.escalation_threshold:
                    result2 = extract_single(
                        record,
                        self._taxonomy_ref,
                        self._client,
                        model=self.escalation_model,
                    )
                    if result2.get("confidence", 0) > result.get("confidence", 0):
                        result = result2

                # Merge into document meta
                new_meta = dict(doc.meta) if doc.meta else {}
                new_meta["intelligence"] = result
                enriched.append(dataclasses.replace(doc, meta=new_meta))

            except Exception as e:
                logger.warning(
                    "Extraction failed for {doc_id}: {error}",
                    doc_id=doc.id,
                    error=str(e),
                )
                enriched.append(doc)

        return {"documents": enriched}
