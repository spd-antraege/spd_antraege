"""
Phase 1: Corpus processing tests.

Run locally (no VPS needed):
    pytest tests/test_corpus.py -v

Requires corpus/berlin/ to be present (the real corpus).
"""

import re

import pytest

from conftest import REPO_ROOT, MD_DIR, requires_corpus, requires_parquet

from spdbe.ingest import parse_antrag, discover_corpus
from spdbe.normalize import (
    compute_stable_id,
    parse_veranstaltung_date,
    classify_submitter_type,
)
from spdbe.text_clean import strip_markdown, deboilerplate, compute_boilerplate_share


# ===========================================================================
# Stage A: Ingest + Validate
# ===========================================================================


@requires_corpus
class TestIngestAll:
    def test_parse_all_documents(self):
        """Every .md file must parse without crash."""
        failures = []
        for path in sorted(MD_DIR.rglob("*.md")):
            try:
                doc = parse_antrag(path)
                assert doc["kuerzel"] is not None
            except Exception as e:
                failures.append((str(path.relative_to(REPO_ROOT)), str(e)))
        assert failures == [], (
            f"{len(failures)} parse failures:\n"
            + "\n".join(f"  {p}: {e}" for p, e in failures[:20])
        )

    def test_corpus_size_minimum(self):
        """Corpus has at least 4200 files."""
        paths = list(MD_DIR.rglob("*.md"))
        assert len(paths) >= 4200, f"Expected >=4200 files, found {len(paths)}"


# ===========================================================================
# Stage A: Stable IDs
# ===========================================================================


@requires_corpus
class TestStableIds:
    def test_deterministic(self):
        """Same file always produces same ID."""
        path = next(MD_DIR.rglob("*.md"))
        doc = parse_antrag(path)
        id1 = compute_stable_id(doc)
        id2 = compute_stable_id(doc)
        assert id1 == id2

    def test_unique_across_corpus(self):
        """No two documents produce the same ID."""
        ids = []
        for path in MD_DIR.rglob("*.md"):
            doc = parse_antrag(path)
            ids.append(compute_stable_id(doc))
        dupes = len(ids) - len(set(ids))
        assert dupes == 0, f"{dupes} duplicate IDs"

    def test_id_is_sha1_hex(self):
        """ID is a 40-char hex string."""
        path = next(MD_DIR.rglob("*.md"))
        doc = parse_antrag(path)
        stable_id = compute_stable_id(doc)
        assert re.match(r"^[0-9a-f]{40}$", stable_id), f"Bad ID format: {stable_id}"

    def test_id_from_source_path(self):
        """ID is derived from source_path (unique per file)."""
        doc_a = {
            "pdf_url": "https://example.com/same.pdf",
            "source_url": "https://example.com/same",
            "source_path": "2025/file_a.md",
        }
        doc_b = {
            "pdf_url": "https://example.com/same.pdf",
            "source_url": "https://example.com/same",
            "source_path": "2025/file_b.md",
        }
        # Even with same pdf_url and source_url, different paths → different IDs
        assert compute_stable_id(doc_a) != compute_stable_id(doc_b)


# ===========================================================================
# Stage B: Date Normalization
# ===========================================================================


class TestDateNormalization:
    @pytest.mark.parametrize(
        "raw, expected_id, expected_date",
        [
            ("I/2025 LPT 24.05.2025", "I/2025", "2025-05-24"),
            ("II/2022 Landesparteitag 12.11.2022", "II/2022", "2022-11-12"),
            ("I/2014 Parteitag I / 2014", "I/2014", None),
            ("II/2019 Landesparteitag 26. Oktober 2019", "II/2019", "2019-10-26"),
        ],
    )
    def test_parse_veranstaltung(self, raw, expected_id, expected_date):
        result = parse_veranstaltung_date(raw)
        assert result["parteitag_id"] == expected_id
        if expected_date:
            assert result["parteitag_date"] == expected_date
        else:
            assert result["parteitag_date"] is None

    def test_escaped_newline(self):
        """Handles \\n in YAML strings."""
        raw = "II/2014 \\nAnträge zum Parteitag 08. November 2014"
        result = parse_veranstaltung_date(raw)
        assert result["parteitag_id"] == "II/2014"
        assert result["parteitag_date"] == "2014-11-08"

    def test_multi_day_event(self):
        """Takes first day of multi-day events."""
        raw = "I/2018 \\nLandesparteitag 01./02.06.2018"
        result = parse_veranstaltung_date(raw)
        assert result["parteitag_id"] == "I/2018"
        assert result["parteitag_date"] == "2018-06-01"

    def test_multi_veranstaltung_takes_first(self):
        """Comma-separated veranstaltungen: take first."""
        raw = "I/2022 Landesparteitag 19.06.2022,I/2020 Landesparteitag 31.10.2020"
        result = parse_veranstaltung_date(raw)
        assert result["parteitag_id"] == "I/2022"

    def test_empty_string(self):
        result = parse_veranstaltung_date("")
        assert result["parteitag_id"] is None
        assert result["parteitag_date"] is None

    @requires_corpus
    def test_parteitag_id_parse_rate(self):
        """>=99% of corpus files must have a parseable parteitag_id."""
        total = 0
        parsed = 0
        for path in MD_DIR.rglob("*.md"):
            doc = parse_antrag(path)
            total += 1
            result = parse_veranstaltung_date(doc.get("veranstaltung_raw", ""))
            if result["parteitag_id"] is not None:
                parsed += 1
        rate = parsed / total if total else 0
        assert rate >= 0.99, f"Parteitag ID parse rate {rate:.1%} < 99% ({parsed}/{total})"

    @requires_corpus
    def test_date_parse_success_rate(self):
        """>=93% of corpus files must have a concrete date."""
        total = 0
        parsed = 0
        for path in MD_DIR.rglob("*.md"):
            doc = parse_antrag(path)
            total += 1
            result = parse_veranstaltung_date(doc.get("veranstaltung_raw", ""))
            if result["parteitag_date"] is not None:
                parsed += 1
        rate = parsed / total if total else 0
        assert rate >= 0.93, f"Date parse rate {rate:.1%} < 93% ({parsed}/{total})"


# ===========================================================================
# Stage B: Submitter Type
# ===========================================================================


class TestSubmitterType:
    VALID_TYPES = {
        "Landesvorstand", "KDV", "Abteilung", "AG", "FA",
        "Einzelperson", "Bezirk", "Unknown",
    }

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("Landesvorstand", "Landesvorstand"),
            ("KDV Neukölln", "KDV"),
            ("Abt. 03/11 Mauerpark (Pankow)", "Abteilung"),
            ("Abteilung 07/04 Lichtenrade-Marienfelde", "Abteilung"),
            ("AfA Berlin", "AG"),
            ("AG 60plus Landesvorstand", "AG"),
            ("Jusos Berlin", "AG"),
            ("ASF LFK", "AG"),
            ("FA III Innen", "FA"),
            ("", "Unknown"),
        ],
    )
    def test_classify(self, raw, expected):
        assert classify_submitter_type(raw) == expected

    @requires_corpus
    def test_all_submitters_classify(self):
        """Every submitter in corpus maps to a known type."""
        unmapped = set()
        for path in MD_DIR.rglob("*.md"):
            doc = parse_antrag(path)
            stype = classify_submitter_type(doc.get("submitter_raw", ""))
            if stype not in self.VALID_TYPES:
                unmapped.add(doc.get("submitter_raw", ""))
        assert unmapped == set(), f"Unmapped submitters: {unmapped}"


# ===========================================================================
# Stage C: Text Cleaning
# ===========================================================================


class TestTextCleaning:
    def test_strip_markdown_removes_headers(self):
        md = "## Antragstext\n\nDer Senat wird aufgefordert."
        plain = strip_markdown(md)
        assert "##" not in plain
        assert "Der Senat wird aufgefordert" in plain

    def test_strip_markdown_removes_bold(self):
        md = "**AntragstellerInnen:** Landesvorstand"
        plain = strip_markdown(md)
        assert "**" not in plain
        assert "Landesvorstand" in plain

    def test_strip_markdown_removes_links(self):
        md = "Siehe [Beschluss](https://example.com) dazu."
        plain = strip_markdown(md)
        assert "[" not in plain
        assert "Beschluss" in plain

    def test_deboilerplate_removes_procedural(self):
        text = (
            "Der Landesparteitag möge beschließen\n\n"
            "Konkrete Forderung zur Mietpreisbremse.\n\n"
            "Der Landesparteitag möge beschließen\n\n"
            "Zweite Forderung."
        )
        clean = deboilerplate(text)
        assert "Mietpreisbremse" in clean
        assert clean.count("Der Landesparteitag möge beschließen") < 2

    def test_boilerplate_share_between_0_and_1(self):
        original = "Some text. " * 100
        cleaned = "Some text. " * 80
        share = compute_boilerplate_share(original, cleaned)
        assert 0.0 <= share <= 1.0


# ===========================================================================
# Pipeline Output: Parquet Schema
# ===========================================================================


@requires_parquet
class TestParquetOutput:
    REQUIRED_COLUMNS = [
        "id", "source_path", "source_url", "pdf_url",
        "parteitag_id", "parteitag_date", "year", "month",
        "submitter_raw", "submitter_type",
        "kuerzel", "title", "doc_type", "status_raw", "tags_raw", "tag_count",
        "text_md", "text_plain", "text_clean",
        "word_count", "char_count", "boilerplate_share",
        "missing_text", "date_parse_ok", "tag_suspect_broad", "conversion_artifacts_hint",
    ]

    def test_schema_columns(self):
        import pandas as pd
        df = pd.read_parquet(REPO_ROOT / "data" / "derived" / "antraege.parquet")
        for col in self.REQUIRED_COLUMNS:
            assert col in df.columns, f"Missing column: {col}"

    def test_row_count(self):
        import pandas as pd
        df = pd.read_parquet(REPO_ROOT / "data" / "derived" / "antraege.parquet")
        assert len(df) >= 4200, f"Expected >=4200 rows, got {len(df)}"

    def test_no_duplicate_ids(self):
        import pandas as pd
        df = pd.read_parquet(REPO_ROOT / "data" / "derived" / "antraege.parquet")
        dupes = df["id"].duplicated().sum()
        assert dupes == 0, f"{dupes} duplicate IDs"

    def test_word_count_positive(self):
        import pandas as pd
        df = pd.read_parquet(REPO_ROOT / "data" / "derived" / "antraege.parquet")
        zeros = (df["word_count"] == 0).sum()
        assert zeros < len(df) * 0.01, f"{zeros} docs with 0 word_count"
