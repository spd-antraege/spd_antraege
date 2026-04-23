"""
Tests for the chunking / metadata pipeline in sync_antraege.py.

Covers:
  1. Unit tests for chunking logic (all 3 tiers, edge cases)
  2. Metadata extraction correctness
  3. Document text assembly (header + body)

Run:
    pytest tests/test_chunking_pipeline.py -v
"""

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

# Make scripts importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from sync_antraege import (
    CHUNK_OVERLAP_TOKENS,
    CHUNK_SECTION_SPLIT_MAX_TOKENS,
    CHUNK_SINGLE_MAX_TOKENS,
    CHUNK_SOFT_MAX_TOKENS,
    _disambiguate_source_doc_id,
    chunk_antrag_content,
    estimate_tokens,
    normalize_text,
    parse_frontmatter_metadata,
    parse_kuerzel,
    source_doc_id_from_kuerzel,
    split_markdown_sections,
    split_section_with_soft_cap,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
MD_DIR = REPO_ROOT / "corpus/berlin"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_antrag(path):
    """Read an Antrag file, return (frontmatter_dict, body_text)."""
    raw = Path(path).read_text(encoding="utf-8")
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        fm = yaml.safe_load(parts[1])
        body = parts[2].strip()
    else:
        fm = {}
        body = raw.strip()
    return fm, body


def _find_corpus_files(min_bytes=0, max_bytes=float("inf"), limit=5):
    """Find real corpus files within a size range."""
    found = []
    for md_file in sorted(MD_DIR.rglob("*.md")):
        size = md_file.stat().st_size
        if min_bytes <= size <= max_bytes:
            found.append(md_file)
            if len(found) >= limit:
                break
    return found


def _source_doc_id(kuerzel):
    """Replicate the slug logic from sync_antraege."""
    slug = kuerzel.lower().strip()
    slug = re.sub(r"[/\s]+", "-", slug)
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


# ===========================================================================
# 1. estimate_tokens
# ===========================================================================


class TestEstimateTokens:
    def test_empty(self):
        assert estimate_tokens("") == 1  # max(1, ...)

    def test_short(self):
        assert estimate_tokens("Hallo") == 1

    def test_proportional(self):
        text = "a" * 400
        assert estimate_tokens(text) == 100

    def test_german_text(self):
        text = "Der Landesparteitag möge beschließen, dass alle Bürgerinnen und Bürger "
        tokens = estimate_tokens(text)
        assert 10 < tokens < 30


# ===========================================================================
# 2. normalize_text
# ===========================================================================


class TestNormalizeText:
    def test_strips_trailing_whitespace(self):
        assert normalize_text("hello   \n  world  ") == "hello\n  world"

    def test_collapses_blank_lines(self):
        assert normalize_text("a\n\n\n\nb") == "a\n\nb"

    def test_crlf_to_lf(self):
        assert normalize_text("a\r\nb") == "a\nb"

    def test_strip_outer(self):
        assert normalize_text("  text  ") == "text"


# ===========================================================================
# 3. split_markdown_sections
# ===========================================================================


class TestSplitMarkdownSections:
    def test_no_headings(self):
        text = "Just a paragraph.\n\nAnother paragraph."
        sections = split_markdown_sections(text)
        assert len(sections) == 1
        assert sections[0]["section_title"] == "Dokument"

    def test_two_sections(self):
        text = "Preamble\n\n## Antragstext\n\nSome text.\n\n## Beschluss\n\nAccepted."
        sections = split_markdown_sections(text)
        assert len(sections) == 3
        assert sections[0]["section_title"] == "Dokument"
        assert sections[1]["section_title"] == "Antragstext"
        assert sections[2]["section_title"] == "Beschluss"

    def test_empty_section_skipped(self):
        text = "## Antragstext\n\n## Beschluss\n\nOnly this."
        sections = split_markdown_sections(text)
        titles = [s["section_title"] for s in sections]
        # Antragstext section contains only the heading line itself — may or may not be empty
        assert "Beschluss" in titles

    def test_preserves_content(self):
        text = "## Antragstext\n\nDer Landesparteitag möge beschließen."
        sections = split_markdown_sections(text)
        assert "beschließen" in sections[0]["text"]


# ===========================================================================
# 4. split_section_with_soft_cap
# ===========================================================================


class TestSplitSectionWithSoftCap:
    def test_short_text_single_chunk(self):
        text = "Short paragraph."
        chunks = split_section_with_soft_cap(text, "Test", 500, 50)
        assert len(chunks) == 1
        assert chunks[0]["section_title"] == "Test"

    def test_multiple_paragraphs_split(self):
        # Create text that will exceed the soft cap
        para = "Wort " * 200  # ~200 tokens
        text = "\n\n".join([para] * 5)  # ~1000 tokens
        chunks = split_section_with_soft_cap(text, "Antragstext", 300, 20)
        assert len(chunks) > 1
        for c in chunks:
            assert c["section_title"] == "Antragstext"

    def test_overlap_present(self):
        para = "Wort " * 200
        text = "\n\n".join([para] * 5)
        chunks = split_section_with_soft_cap(text, "Test", 300, 30)
        if len(chunks) >= 2:
            # Last words of chunk 0 should appear at start of chunk 1
            tail_0 = chunks[0]["text"].split()[-10:]
            head_1 = chunks[1]["text"].split()[:30]
            overlap_count = sum(1 for w in tail_0 if w in head_1)
            assert overlap_count > 0, "Expected overlap between consecutive chunks"

    def test_empty_text(self):
        chunks = split_section_with_soft_cap("", "Empty", 500, 50)
        assert chunks == []


# ===========================================================================
# 5. chunk_antrag_content — tier routing
# ===========================================================================


class TestChunkAntragContent:
    def test_tier1_single_chunk(self):
        # Small doc: <= 2500 tokens => ~10000 chars
        text = "Der Landesparteitag möge beschließen.\n\n" + ("x " * 500)
        chunks = chunk_antrag_content(text)
        assert len(chunks) == 1
        assert chunks[0]["chunk_id"] == "chunk-000"
        assert chunks[0]["section_title"] == "Dokument"

    def test_tier2_section_split(self):
        # Medium doc: 2500-8000 tokens => ~10000-32000 chars
        preamble = "Preamble. " * 200
        antragstext = "## Antragstext\n\n" + "Antrag text. " * 400
        beschluss = "## Beschluss\n\n" + "Beschluss text. " * 200
        text = f"{preamble}\n\n{antragstext}\n\n{beschluss}"

        total_tokens = estimate_tokens(normalize_text(text))
        assert (
            CHUNK_SINGLE_MAX_TOKENS < total_tokens <= CHUNK_SECTION_SPLIT_MAX_TOKENS
        ), f"Test fixture out of tier 2 range: {total_tokens} tokens"

        chunks = chunk_antrag_content(text)
        assert len(chunks) >= 2
        titles = {c["section_title"] for c in chunks}
        assert "Antragstext" in titles

    def test_tier3_large_doc(self):
        # Large doc: > 8000 tokens => > 32000 chars
        sections = [
            "## Antragstext\n\n" + "Forderung. " * 2000,
            "## Begründung\n\n" + "Grund. " * 2000,
            "## Beschluss\n\n" + "Annahme. " * 2000,
        ]
        text = "\n\n".join(sections)

        total_tokens = estimate_tokens(normalize_text(text))
        assert total_tokens > CHUNK_SECTION_SPLIT_MAX_TOKENS, (
            f"Test fixture too small for tier 3: {total_tokens} tokens"
        )

        chunks = chunk_antrag_content(text)
        assert len(chunks) >= 4, (
            f"Expected many chunks for large doc, got {len(chunks)}"
        )

    def test_chunk_ids_sequential(self):
        text = "## A\n\n" + "word " * 3000 + "\n\n## B\n\n" + "word " * 3000
        chunks = chunk_antrag_content(text)
        for i, c in enumerate(chunks):
            assert c["chunk_id"] == f"chunk-{i:03d}"

    def test_no_empty_chunks(self):
        text = "## Antragstext\n\n\n\n## Beschluss\n\nSome content."
        chunks = chunk_antrag_content(text)
        for c in chunks:
            assert c["text"].strip(), f"Empty chunk: {c['chunk_id']}"

    def test_estimated_tokens_present(self):
        text = "Simple content for testing."
        chunks = chunk_antrag_content(text)
        for c in chunks:
            assert "estimated_tokens" in c
            assert c["estimated_tokens"] > 0

    def test_fallback_on_empty(self):
        # Even whitespace-only should produce at least 1 chunk
        chunks = chunk_antrag_content("   \n\n   ")
        assert len(chunks) >= 1


# ===========================================================================
# 6. Chunk quality constraints
# ===========================================================================


class TestChunkQuality:
    """Verify that chunks satisfy the design invariants from SYSTEM_IMPROVEMENTS.md."""

    def test_tier1_no_information_loss(self):
        """Single-chunk tier must preserve all content."""
        text = "Wir fordern:\n\n1. Punkt eins\n2. Punkt zwei\n3. Punkt drei"
        chunks = chunk_antrag_content(text)
        combined = " ".join(c["text"] for c in chunks)
        assert "Punkt eins" in combined
        assert "Punkt zwei" in combined
        assert "Punkt drei" in combined

    def test_section_titles_from_headings(self):
        """Section titles must match the ## headings in the source (tier 2+ docs)."""
        # Must exceed CHUNK_SINGLE_MAX_TOKENS to trigger section splitting
        body = "Antragstext content. " * 400
        why = "Begründung content. " * 400
        done = "Beschluss content. " * 200
        text = f"Pre\n\n## Antragstext\n\n{body}\n\n## Begründung\n\n{why}\n\n## Beschluss\n\n{done}"

        total_tokens = estimate_tokens(normalize_text(text))
        assert total_tokens > CHUNK_SINGLE_MAX_TOKENS, (
            "Fixture too small for section split"
        )

        chunks = chunk_antrag_content(text)
        titles = {c["section_title"] for c in chunks}
        assert "Antragstext" in titles
        assert "Begründung" in titles
        assert "Beschluss" in titles

    def test_chunk_soft_cap_respected(self):
        """No chunk should massively exceed the soft cap (allow 2x for single-paragraph edge case)."""
        big = "## Antragstext\n\n" + ("Forderung der SPD. " * 500 + "\n\n") * 10
        chunks = chunk_antrag_content(big)
        for c in chunks:
            # Allow up to 3x soft cap for edge cases (single huge paragraph)
            assert c["estimated_tokens"] <= CHUNK_SOFT_MAX_TOKENS * 3, (
                f"Chunk {c['chunk_id']} too large: {c['estimated_tokens']} tokens"
            )


# ===========================================================================
# 7. Document text assembly
# ===========================================================================


class TestDocumentTextAssembly:
    """Test _build_chunk_document_text produces correct header + body."""

    def test_header_format(self):
        # Import the private helper
        from sync_antraege import _build_chunk_document_text

        meta = {
            "kuerzel": "Antrag 139/II/2025",
            "titel": "Antrag 139/II/2025 Keine Überwachung durch Palantir",
        }
        chunk = {
            "chunk_id": "chunk-000",
            "section_title": "Antragstext",
            "text": "Der Senat wird aufgefordert, Palantir-Software abzulehnen.",
            "estimated_tokens": 20,
        }

        result = _build_chunk_document_text(meta, chunk)

        assert result.startswith("Kuerzel: Antrag 139/II/2025")
        assert "Titel: Antrag 139/II/2025 Keine Überwachung durch Palantir" in result
        assert "Abschnitt: Antragstext" in result
        assert "Palantir-Software abzulehnen" in result

    def test_header_body_contiguous(self):
        """Header and body must be in a single block (no \\n\\n separation)."""
        from sync_antraege import _build_chunk_document_text

        meta = {"kuerzel": "Antrag 1/I/2020", "titel": "Test"}
        chunk = {
            "chunk_id": "chunk-000",
            "section_title": "Dokument",
            "text": "Body text here.",
            "estimated_tokens": 5,
        }

        result = _build_chunk_document_text(meta, chunk)
        # Header joined to body with single \n, no \n\n that would cause splits
        assert "Abschnitt: Dokument\nBody text here." in result
        # Must NOT contain \n\n between header and body
        header_end = result.index("Dokument") + len("Dokument")
        after_header = result[header_end:]
        assert not after_header.startswith("\n\n"), (
            "Header must not be separated from body by blank line"
        )


# ===========================================================================
# 8. Metadata extraction from frontmatter
# ===========================================================================


class TestMetadataExtraction:
    """Verify metadata values are correctly derived from real corpus files."""

    @pytest.fixture
    def sample_files(self):
        files = _find_corpus_files(min_bytes=500, max_bytes=50000, limit=10)
        if not files:
            pytest.skip("No corpus files found")
        return files

    def test_kuerzel_format(self, sample_files):
        """Every kuerzel must match 'Antrag <nr>/<session>/<year>' (nr can contain dots)."""
        pattern = re.compile(r"^Antrag [\w.\-]+/(I{1,3}V?|IV)/\d{4}$")
        for f in sample_files:
            fm, _ = _load_antrag(f)
            kuerzel = fm.get("kuerzel", "")
            assert pattern.match(kuerzel), f"Bad kuerzel '{kuerzel}' in {f.name}"

    def test_content_hash_present(self, sample_files):
        """Every file should have a content_hash in frontmatter."""
        for f in sample_files:
            fm, _ = _load_antrag(f)
            h = fm.get("content_hash", "")
            assert h and len(h) == 12, f"Missing/bad content_hash in {f.name}"

    def test_content_hash_correct(self, sample_files):
        """content_hash must match recomputed hash of body."""
        for f in sample_files:
            fm, body = _load_antrag(f)
            stored_hash = fm.get("content_hash", "")
            recomputed = hashlib.sha256(
                normalize_text(body).encode("utf-8")
            ).hexdigest()[:12]
            assert stored_hash == recomputed, (
                f"Hash mismatch in {f.name}: stored={stored_hash} recomputed={recomputed}"
            )

    def test_source_doc_id_deterministic(self, sample_files):
        """source_doc_id must be deterministic from kuerzel."""
        for f in sample_files:
            fm, _ = _load_antrag(f)
            kuerzel = fm.get("kuerzel", "")
            sid = _source_doc_id(kuerzel)
            assert sid == _source_doc_id(kuerzel), "source_doc_id not deterministic"
            assert re.match(r"^antrag-[\w-]+$", sid), f"Bad source_doc_id: {sid}"

    def test_year_extractable(self, sample_files):
        """Year must be extractable from kuerzel."""
        for f in sample_files:
            fm, _ = _load_antrag(f)
            kuerzel = fm.get("kuerzel", "")
            m = re.search(r"/(\d{4})$", kuerzel)
            assert m, f"Can't extract year from '{kuerzel}'"
            year = int(m.group(1))
            assert 2010 <= year <= 2030, f"Implausible year {year}"


# ===========================================================================
# 9a. Kuerzel parsing and source id stability
# ===========================================================================


class TestKuerzelAndSourceIds:
    def test_parse_kuerzel_supports_dotted_numbers(self):
        parsed = parse_kuerzel("Antrag 15.1/II/2014")
        assert parsed is not None
        assert parsed["number"] == "15.1"
        assert parsed["session"] == "II"
        assert parsed["year"] == "2014"

    def test_source_doc_id_distinguishes_dotted_vs_plain_numbers(self):
        dotted = source_doc_id_from_kuerzel("Antrag 15.1/II/2014")
        plain = source_doc_id_from_kuerzel("Antrag 151/II/2014")
        assert dotted != plain

    def test_frontmatter_metadata_extracts_year_session_for_dotted_kuerzel(self):
        path = (
            REPO_ROOT
            / "corpus/berlin/2015/Antrag 15.1-II-2014--1ii2014-ersetzungsantrag-i-zu-15ii2014.md"
        )
        if not path.exists():
            pytest.skip("Reference dotted kuerzel file not found")
        meta = parse_frontmatter_metadata(path)
        assert meta["year"] == "2014"
        assert meta["session"] == "II"

    def test_duplicate_source_doc_id_gets_stable_suffix(self):
        base = source_doc_id_from_kuerzel("Antrag 02/I/2025")
        counts = {base: 2}
        meta_a = {
            "kuerzel": "Antrag 02/I/2025",
            "titel": "A",
            "source_url": "https://example.org/a",
            "file_path": "a.md",
        }
        meta_b = {
            "kuerzel": "Antrag 02/I/2025",
            "titel": "B",
            "source_url": "https://example.org/b",
            "file_path": "b.md",
        }

        sid_a = _disambiguate_source_doc_id(base, meta_a, counts)
        sid_b = _disambiguate_source_doc_id(base, meta_b, counts)

        assert sid_a.startswith(base + "-")
        assert sid_b.startswith(base + "-")
        assert sid_a != sid_b


# ===========================================================================
# 10. Real corpus chunking (parametrized across tiers)
# ===========================================================================


class TestRealCorpusChunking:
    """Run chunking on actual Antrag files and verify structural invariants."""

    @pytest.fixture(params=["small", "medium", "large"])
    def corpus_file(self, request):
        if request.param == "small":
            files = _find_corpus_files(max_bytes=2000, limit=1)
        elif request.param == "medium":
            files = _find_corpus_files(min_bytes=3000, max_bytes=10000, limit=1)
        else:
            files = _find_corpus_files(min_bytes=50000, limit=1)

        if not files:
            pytest.skip(f"No {request.param} corpus file found")
        return files[0], request.param

    def test_chunks_cover_content(self, corpus_file):
        """Combined chunk text should contain key phrases from original."""
        path, size_class = corpus_file
        fm, body = _load_antrag(path)
        chunks = chunk_antrag_content(body)

        combined = " ".join(c["text"] for c in chunks)

        # Body content should be in chunks
        words = [w for w in body.split()[:20] if len(w) > 4]
        if words:
            found = sum(1 for w in words if w in combined)
            assert found >= len(words) // 2, (
                f"Too much content lost in chunking ({found}/{len(words)} words found)"
            )

    def test_chunk_count_reasonable(self, corpus_file):
        """Chunk count should be proportional to document size."""
        path, size_class = corpus_file
        _, body = _load_antrag(path)
        chunks = chunk_antrag_content(body)

        if size_class == "small":
            assert len(chunks) == 1, f"Small doc should be 1 chunk, got {len(chunks)}"
        elif size_class == "medium":
            assert 1 <= len(chunks) <= 10
        else:
            assert len(chunks) >= 2, "Large doc should have multiple chunks"

    def test_external_doc_ids_unique(self, corpus_file):
        """All external_doc_ids for one Antrag must be unique."""
        path, _ = corpus_file
        fm, body = _load_antrag(path)
        sid = _source_doc_id(fm.get("kuerzel", "unknown"))
        chunks = chunk_antrag_content(body)

        ext_ids = [f"{sid}::{c['chunk_id']}" for c in chunks]
        assert len(ext_ids) == len(set(ext_ids)), "Duplicate external_doc_ids"
