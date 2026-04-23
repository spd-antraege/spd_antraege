"""RRFJoiner: Reciprocal Rank Fusion for combining retriever results.

Fuses BM25 and embedding retriever outputs into a single ranked list
using RRF scoring. Operates on Haystack Document objects.
"""

from __future__ import annotations

import dataclasses
from typing import List

from haystack import Document, component


@component
class RRFJoiner:
    """Fuse multiple ranked document lists using Reciprocal Rank Fusion.

    Takes BM25 and embedding retriever outputs, combines them with RRF
    scoring, and returns a single re-ranked list.

    RRF score for document d = sum over all lists: 1 / (k + rank(d))
    """

    def __init__(self, k: int = 60, top_n: int = 20):
        self.k = k
        self.top_n = top_n

    @component.output_types(documents=List[Document])
    def run(
        self,
        bm25_documents: List[Document],
        embedding_documents: List[Document],
    ) -> dict:
        """Fuse two ranked lists of documents.

        Args:
            bm25_documents: Results from BM25 retriever (ranked by relevance).
            embedding_documents: Results from embedding retriever (ranked by similarity).

        Returns:
            dict with "documents" key containing fused, re-ranked List[Document].
        """
        # Build RRF scores
        scores: dict[str, float] = {}
        doc_map: dict[str, Document] = {}

        for ranked_list in [bm25_documents, embedding_documents]:
            for rank, doc in enumerate(ranked_list):
                doc_id = doc.id
                scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (self.k + rank + 1)
                # Keep the doc object (later occurrence overwrites, which is fine)
                doc_map[doc_id] = doc

        # Sort by RRF score descending
        sorted_ids = sorted(scores.keys(), key=lambda d: scores[d], reverse=True)

        # Build result list with RRF scores (immutable replace per Haystack convention)
        documents = []
        for doc_id in sorted_ids[: self.top_n]:
            doc = doc_map[doc_id]
            documents.append(dataclasses.replace(doc, score=scores[doc_id]))

        return {"documents": documents}
