"""Unit tests for Haystack v2 custom components."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from haystack import Document

pytestmark = pytest.mark.haystack


# ---------------------------------------------------------------------------
# Converters
# ---------------------------------------------------------------------------


class TestConverters:
    def test_record_to_document(self):
        from spdbe.haystack.converters import record_to_document

        rec = {
            "id": "abc123",
            "text_clean": "Dies ist ein Test.",
            "kuerzel": "1/I/2024",
            "year": 2024,
            "title": "Testantrag",
            "submitter_type": "KDV",
        }
        doc = record_to_document(rec, landesverband="berlin")

        assert doc.id == "abc123"
        assert doc.content == "Dies ist ein Test."
        assert doc.meta["kuerzel"] == "1/I/2024"
        assert doc.meta["year"] == 2024
        assert doc.meta["landesverband"] == "berlin"

    def test_document_to_record(self):
        from spdbe.haystack.converters import document_to_record

        doc = Document(
            id="xyz",
            content="Inhalt",
            meta={"kuerzel": "2/II/2023", "year": 2023},
        )
        rec = document_to_record(doc)

        assert rec["id"] == "xyz"
        assert rec["text_clean"] == "Inhalt"
        assert rec["kuerzel"] == "2/II/2023"

    def test_round_trip(self):
        from spdbe.haystack.converters import (
            document_to_record,
            record_to_document,
        )

        original = {
            "id": "test_id",
            "text_clean": "Original text",
            "kuerzel": "5/I/2020",
            "year": 2020,
            "submitter_type": "AG",
            "tags_raw": ["digital", "verwaltung"],
        }
        doc = record_to_document(original)
        result = document_to_record(doc)

        assert result["id"] == original["id"]
        assert result["text_clean"] == original["text_clean"]
        assert result["kuerzel"] == original["kuerzel"]
        assert result["tags_raw"] == original["tags_raw"]

    def test_default_landesverband(self):
        from spdbe.haystack.converters import record_to_document

        doc = record_to_document({"id": "x", "text_clean": ""})
        assert doc.meta["landesverband"] == "berlin"

    def test_explicit_landesverband(self):
        from spdbe.haystack.converters import record_to_document

        doc = record_to_document(
            {"id": "x", "text_clean": "", "landesverband": "bayern"},
            landesverband="rlp",
        )
        # Record's own landesverband takes precedence
        assert doc.meta["landesverband"] == "bayern"


# ---------------------------------------------------------------------------
# RRFJoiner
# ---------------------------------------------------------------------------


class TestRRFJoiner:
    def test_basic_fusion(self):
        from spdbe.haystack.components.rrf_joiner import RRFJoiner

        joiner = RRFJoiner(k=60, top_n=5)

        bm25 = [
            Document(id="a", content="a"),
            Document(id="b", content="b"),
            Document(id="c", content="c"),
        ]
        emb = [
            Document(id="b", content="b"),
            Document(id="d", content="d"),
            Document(id="a", content="a"),
        ]

        result = joiner.run(bm25_documents=bm25, embedding_documents=emb)
        docs = result["documents"]

        # Both a and b appear in both lists
        ids = [d.id for d in docs]
        assert "a" in ids
        assert "b" in ids
        assert "c" in ids
        assert "d" in ids

        # All have scores
        for doc in docs:
            assert doc.score > 0

    def test_top_n_limit(self):
        from spdbe.haystack.components.rrf_joiner import RRFJoiner

        joiner = RRFJoiner(k=60, top_n=2)

        bm25 = [Document(id=str(i), content=str(i)) for i in range(10)]
        emb = [Document(id=str(i), content=str(i)) for i in range(10)]

        result = joiner.run(bm25_documents=bm25, embedding_documents=emb)
        assert len(result["documents"]) == 2

    def test_empty_inputs(self):
        from spdbe.haystack.components.rrf_joiner import RRFJoiner

        joiner = RRFJoiner(k=60, top_n=5)
        result = joiner.run(bm25_documents=[], embedding_documents=[])
        assert result["documents"] == []

    def test_no_mutation(self):
        """Verify original documents are not mutated."""
        from spdbe.haystack.components.rrf_joiner import RRFJoiner

        joiner = RRFJoiner(k=60, top_n=5)
        original = Document(id="x", content="x", score=None)
        result = joiner.run(
            bm25_documents=[original],
            embedding_documents=[original],
        )
        # Original should be unchanged
        assert original.score is None
        # Result should have a score
        assert result["documents"][0].score > 0


# ---------------------------------------------------------------------------
# MotionNormalizer
# ---------------------------------------------------------------------------


class TestMotionNormalizer:
    def test_with_real_files(self):
        """Test with actual corpus files (requires corpus/berlin/)."""
        import glob

        from spdbe.haystack.components.motion_normalizer import MotionNormalizer

        files = sorted(glob.glob("corpus/berlin/2024/*.md"))[:2]
        if not files:
            pytest.skip("No corpus files available")

        mn = MotionNormalizer(landesverband="berlin")
        result = mn.run(sources=files)
        docs = result["documents"]

        assert len(docs) == 2
        for doc in docs:
            assert doc.id  # has stable ID
            assert doc.content  # has text_clean
            assert doc.meta["kuerzel"]
            assert doc.meta["landesverband"] == "berlin"
            assert doc.meta["word_count"] > 0

    def test_nonexistent_files_skipped(self):
        from spdbe.haystack.components.motion_normalizer import MotionNormalizer

        mn = MotionNormalizer()
        result = mn.run(sources=["/nonexistent/file.md"])
        assert result["documents"] == []

    def test_boilerplate_index_loading(self):
        from spdbe.haystack.components.motion_normalizer import MotionNormalizer

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"phrases": ["der landesparteitag möge beschließen"]}, f)
            f.flush()

            mn = MotionNormalizer(boilerplate_index_path=f.name)
            mn.warm_up()
            assert mn._boilerplate_index is not None
            assert "der landesparteitag möge beschließen" in mn._boilerplate_index


# ---------------------------------------------------------------------------
# TaxonomyClassifier
# ---------------------------------------------------------------------------


class TestTaxonomyClassifier:
    def test_validates_known_topic(self):
        from spdbe.haystack.components.taxonomy_classifier import TaxonomyClassifier

        tc = TaxonomyClassifier(taxonomy_path="data/taxonomy/topics.yaml")
        tc.warm_up()

        # Pick a known topic ID
        known_id = sorted(tc._existing_ids)[0]

        doc = Document(
            id="test",
            content="test",
            meta={
                "intelligence": {
                    "topics": {"primary": known_id},
                    "connections": {"unmatched_signals": []},
                }
            },
        )

        result = tc.run(documents=[doc])
        assert result["documents"][0].meta["taxonomy_validated"] is True

    def test_rejects_unknown_topic(self):
        from spdbe.haystack.components.taxonomy_classifier import TaxonomyClassifier

        tc = TaxonomyClassifier(taxonomy_path="data/taxonomy/topics.yaml")
        tc.warm_up()

        doc = Document(
            id="test",
            content="test",
            meta={
                "intelligence": {
                    "topics": {"primary": "completely_nonexistent_topic_xyz"},
                    "connections": {"unmatched_signals": []},
                }
            },
        )

        result = tc.run(documents=[doc])
        assert result["documents"][0].meta["taxonomy_validated"] is False

    def test_passes_through_docs_without_intelligence(self):
        from spdbe.haystack.components.taxonomy_classifier import TaxonomyClassifier

        tc = TaxonomyClassifier(taxonomy_path="data/taxonomy/topics.yaml")

        doc = Document(id="plain", content="no intelligence")
        result = tc.run(documents=[doc])
        assert len(result["documents"]) == 1
        assert result["documents"][0].id == "plain"


# ---------------------------------------------------------------------------
# Pipeline builds (no ES required — just verify graph construction)
# ---------------------------------------------------------------------------


class TestPipelineBuilds:
    def test_indexing_pipeline_builds(self):
        from spdbe.haystack.pipelines.indexing import build_indexing_pipeline

        pipe = build_indexing_pipeline()
        assert "normalizer" in pipe.graph.nodes
        assert "splitter" in pipe.graph.nodes
        assert "embedder" in pipe.graph.nodes
        assert "writer" in pipe.graph.nodes

    def test_search_pipeline_builds(self):
        from spdbe.haystack.pipelines.search import build_search_pipeline

        pipe = build_search_pipeline()
        assert "text_embedder" in pipe.graph.nodes
        assert "bm25_retriever" in pipe.graph.nodes
        assert "embedding_retriever" in pipe.graph.nodes
        assert "joiner" in pipe.graph.nodes

    def test_rag_pipeline_builds(self):
        import os

        if not os.environ.get("ANTHROPIC_API_KEY"):
            pytest.skip("ANTHROPIC_API_KEY not set")

        from spdbe.haystack.pipelines.rag import build_rag_pipeline

        pipe = build_rag_pipeline()
        assert "prompt_builder" in pipe.graph.nodes
        assert "llm" in pipe.graph.nodes
        assert "joiner" in pipe.graph.nodes

    def test_extraction_pipeline_builds(self):
        from spdbe.haystack.pipelines.extraction import build_extraction_pipeline

        pipe = build_extraction_pipeline()
        assert "extractor" in pipe.graph.nodes
        assert "classifier" in pipe.graph.nodes
        assert "writer" in pipe.graph.nodes

    def test_indexing_pipeline_serializes(self):
        from spdbe.haystack.pipelines.indexing import build_indexing_pipeline

        pipe = build_indexing_pipeline()
        yaml_str = pipe.dumps()
        assert "normalizer" in yaml_str
        assert "splitter" in yaml_str
        assert len(yaml_str) > 100

    def test_search_pipeline_serializes(self):
        from spdbe.haystack.pipelines.search import build_search_pipeline

        pipe = build_search_pipeline()
        yaml_str = pipe.dumps()
        assert "bm25_retriever" in yaml_str
        assert "joiner" in yaml_str
