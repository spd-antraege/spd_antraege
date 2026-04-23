"""BM25 retriever with field boosting (title^3, content^1)."""

from __future__ import annotations

from typing import Any

from haystack import Document, component
from haystack.document_stores.types import FilterPolicy, apply_filter_policy
from haystack_integrations.document_stores.elasticsearch import (
    ElasticsearchDocumentStore,
)
from haystack_integrations.document_stores.elasticsearch.document_store import (
    _normalize_filters,
)


@component
class BoostedBM25Retriever:
    """BM25 retriever that boosts title matches over content matches.

    Uses ES multi_match with explicit field weights instead of the default
    equal-weight search across all text fields.
    """

    def __init__(
        self,
        document_store: ElasticsearchDocumentStore,
        *,
        top_k: int = 10,
        fuzziness: str = "AUTO",
        title_boost: int = 3,
        filter_policy: FilterPolicy = FilterPolicy.REPLACE,
        filters: dict[str, Any] | None = None,
    ):
        self._document_store = document_store
        self._top_k = top_k
        self._fuzziness = fuzziness
        self._title_boost = title_boost
        self._filter_policy = filter_policy
        self._filters = filters

    @component.output_types(documents=list[Document])
    def run(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        top_k: int | None = None,
    ) -> dict[str, list[Document]]:
        """Retrieve documents with title-boosted BM25 scoring."""
        filters = apply_filter_policy(self._filter_policy, self._filters, filters)
        top_k = top_k or self._top_k

        body: dict[str, Any] = {
            "size": top_k,
            "query": {
                "bool": {
                    "must": [
                        {
                            "multi_match": {
                                "query": query,
                                "fields": [
                                    f"title^{self._title_boost}",
                                    "content",
                                    "submitter_raw",
                                ],
                                "fuzziness": self._fuzziness,
                                "type": "most_fields",
                                "operator": "OR",
                            }
                        }
                    ]
                }
            },
        }

        if filters:
            body["query"]["bool"]["filter"] = _normalize_filters(filters)

        documents = self._document_store._search_documents(**body)
        return {"documents": documents}
