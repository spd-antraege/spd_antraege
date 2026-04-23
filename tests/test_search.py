"""
Phase 4: Search tests.

BM25 tests run locally. Vector tests require embeddings built.
"""

import time

import pytest

from conftest import REPO_ROOT, requires_parquet


LANCE_DIR = REPO_ROOT / "data" / "vectors" / "documents"

requires_vectors = pytest.mark.skipif(
    not LANCE_DIR.exists(), reason="Vector index not built"
)


@requires_parquet
class TestBM25:
    def _search(self):
        from spdbe.search import HybridSearch
        hs = HybridSearch(
            REPO_ROOT / "data" / "derived" / "antraege.parquet",
            LANCE_DIR,
        )
        hs.build()
        return hs

    def test_finds_exact_keyword(self):
        """BM25 finds documents by exact keyword."""
        hs = self._search()
        results = hs.search("Mietpreisbremse", top_k=5, mode="bm25")
        assert len(results) > 0
        # At least one result should mention Miet-something
        texts = [r.get("title", "") + r.get("snippet", "") for r in results]
        assert any("Miet" in t or "miet" in t for t in texts)

    def test_finds_antragsnummer(self):
        """BM25 finds documents by Antragsnummer."""
        hs = self._search()
        results = hs.search("150/I/2022", top_k=5, mode="bm25")
        assert len(results) > 0

    def test_returns_enriched_results(self):
        """Results include kuerzel, title, year, snippet."""
        hs = self._search()
        results = hs.search("Datenschutz", top_k=3, mode="bm25")
        assert len(results) > 0
        r = results[0]
        assert "doc_id" in r
        assert "score" in r
        assert "kuerzel" in r
        assert "snippet" in r

    def test_metadata_filter_year(self):
        """Year filter narrows results."""
        hs = self._search()
        results = hs.search("Polizei", top_k=20, mode="bm25",
                            filters={"year_min": 2022})
        for r in results:
            if r.get("year"):
                assert r["year"] >= 2022

    def test_metadata_filter_submitter_type(self):
        """Submitter type filter works."""
        hs = self._search()
        results = hs.search("Schule", top_k=20, mode="bm25",
                            filters={"submitter_type": "KDV"})
        for r in results:
            if r.get("submitter_type"):
                assert r["submitter_type"] == "KDV"

    def test_fast_response(self):
        """BM25 search returns in <2 seconds."""
        hs = self._search()
        start = time.time()
        hs.search("Verwaltungsdigitalisierung", top_k=10, mode="bm25")
        elapsed = time.time() - start
        assert elapsed < 2.0, f"Search took {elapsed:.1f}s"


class TestRRF:
    def test_fusion_combines_lists(self):
        """RRF combines two ranked lists."""
        from spdbe.search import reciprocal_rank_fusion

        list1 = [("a", 10), ("b", 8), ("c", 5)]
        list2 = [("b", 10), ("d", 8), ("a", 5)]

        fused = reciprocal_rank_fusion(list1, list2, top_n=4)
        ids = [f[0] for f in fused]
        # "b" appears high in both lists, should be top
        assert ids[0] == "b" or ids[1] == "b"
        # All unique IDs present
        assert set(ids) <= {"a", "b", "c", "d"}

    def test_fusion_deduplicates(self):
        """RRF doesn't produce duplicate doc_ids."""
        from spdbe.search import reciprocal_rank_fusion

        list1 = [("a", 10), ("b", 8)]
        list2 = [("a", 10), ("b", 8)]

        fused = reciprocal_rank_fusion(list1, list2, top_n=5)
        ids = [f[0] for f in fused]
        assert len(ids) == len(set(ids))
