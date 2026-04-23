"""TaxonomyClassifier: Validate taxonomy assignments and track unmatched signals.

Wraps taxonomy_engine.UnmatchedAccumulator to work within Haystack pipelines.
Runs after MetadataExtractor to validate and accumulate signals.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Dict, List

import yaml
from haystack import Document, component, logging

try:
    from spdbe.taxonomy_engine import UnmatchedAccumulator, generate_proposals
except ImportError:
    UnmatchedAccumulator = None
    generate_proposals = None

logger = logging.getLogger(__name__)


@component
class TaxonomyClassifier:
    """Validate taxonomy assignments and track unmatched signals.

    For each Document with intelligence metadata:
    1. Validates that topics.primary exists in the taxonomy
    2. Tracks unmatched_signals via UnmatchedAccumulator
    3. Sets meta["taxonomy_validated"] flag
    4. Outputs taxonomy proposals when signals reach threshold

    Uses in-memory accumulator (no PostgreSQL) for pipeline portability.
    """

    def __init__(
        self,
        taxonomy_path: str = "data/taxonomy/topics.yaml",
        proposal_threshold: int = 5,
    ):
        self.taxonomy_path = taxonomy_path
        self.proposal_threshold = proposal_threshold
        self._existing_ids: set[str] | None = None
        self._accumulator: UnmatchedAccumulator | None = None

    def warm_up(self):
        """Load taxonomy and initialize accumulator."""
        path = Path(self.taxonomy_path)
        if path.exists():
            with open(path) as f:
                tax = yaml.safe_load(f)
            self._existing_ids = set()
            for domain_id, domain in tax.get("domains", {}).items():
                self._existing_ids.add(domain_id)
                for sub_id in domain.get("subtopics", {}):
                    self._existing_ids.add(sub_id)
        else:
            self._existing_ids = set()

        self._accumulator = UnmatchedAccumulator(use_db=False)

    @component.output_types(documents=List[Document], proposals=List[Dict[str, Any]])
    def run(self, documents: List[Document]) -> dict:
        """Validate taxonomy and accumulate unmatched signals.

        Args:
            documents: Documents with meta["intelligence"] from MetadataExtractor.

        Returns:
            dict with:
              - "documents": Documents with meta["taxonomy_validated"]
              - "proposals": List of taxonomy proposal dicts (if threshold reached)
        """
        if self._existing_ids is None or self._accumulator is None:
            self.warm_up()

        enriched = []
        for doc in documents:
            intel = (doc.meta or {}).get("intelligence", {})
            if not intel:
                enriched.append(doc)
                continue

            # Validate primary topic
            primary = intel.get("topics", {}).get("primary", "")
            validated = primary in self._existing_ids

            # Track unmatched signals
            signals = intel.get("connections", {}).get("unmatched_signals", [])
            for signal in signals:
                if isinstance(signal, str) and signal.strip():
                    self._accumulator.add(signal, doc.id)

            # Update meta
            new_meta = dict(doc.meta) if doc.meta else {}
            new_meta["taxonomy_validated"] = validated
            enriched.append(dataclasses.replace(doc, meta=new_meta))

        # Generate proposals from accumulated signals
        proposals = []
        if self._accumulator:
            raw_proposals = generate_proposals(
                self._accumulator,
                Path(self.taxonomy_path),
                threshold=self.proposal_threshold,
            )
            proposals = [
                {
                    "proposal_id": p.proposal_id,
                    "topic_id": p.topic_id,
                    "domain_id": p.domain_id,
                    "label_de": p.label_de,
                    "evidence_count": len(p.evidence_doc_ids),
                    "evidence_doc_ids": p.evidence_doc_ids[:10],
                }
                for p in raw_proposals
            ]

        return {"documents": enriched, "proposals": proposals}
