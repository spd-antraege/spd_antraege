"""Tests for Haystack indexing helpers."""

from __future__ import annotations

import pandas as pd


def test_discover_derived_parquets(tmp_path):
    from spdbe.haystack.pipelines.indexing import discover_derived_parquets

    first = tmp_path / "hessen" / "antraege.parquet"
    second = tmp_path / "nrw" / "antraege.parquet"
    ignored = tmp_path / "nrw" / "other.parquet"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("placeholder")
    second.write_text("placeholder")
    ignored.write_text("placeholder")

    assert discover_derived_parquets(tmp_path) == [first, second]


def test_documents_from_parquet_maps_normalized_fields(tmp_path):
    from spdbe.haystack.pipelines.indexing import documents_from_parquet

    parquet_path = tmp_path / "antraege.parquet"
    pd.DataFrame(
        [
            {
                "id": "hessen-1",
                "kuerzel": "LPT-1",
                "title": "Bezahlbares Wohnen",
                "year": 2025,
                "submitter_raw": "AG Wohnen",
                "submitter_type": "AG",
                "status_raw": "Annahme",
                "doc_type": "Antrag",
                "veranstaltung": "Landesparteitag",
                "source_url": "https://example.test/antrag",
                "text_clean": "Bezahlbares Wohnen braucht dauerhaft mehr sozialen Wohnungsbau.",
                "content_hash": "abc123",
                "landesverband": "hessen",
            },
            {
                "id": "empty",
                "text_clean": "",
            },
        ]
    ).to_parquet(parquet_path)

    documents = documents_from_parquet(parquet_path)

    assert len(documents) == 1
    assert documents[0].id == "hessen-1"
    assert documents[0].content.startswith("Bezahlbares Wohnen")
    assert documents[0].meta["kuerzel"] == "LPT-1"
    assert documents[0].meta["year"] == 2025
    assert documents[0].meta["landesverband"] == "hessen"
    assert documents[0].meta["veranstaltung_raw"] == "Landesparteitag"


def test_run_indexing_from_parquets_uses_one_pipeline(monkeypatch, tmp_path):
    from spdbe.haystack.pipelines import indexing

    paths = []
    for state in ("hessen", "nrw"):
        parquet_path = tmp_path / state / "antraege.parquet"
        parquet_path.parent.mkdir()
        pd.DataFrame(
            [
                {
                    "id": f"{state}-1",
                    "kuerzel": "A01",
                    "title": "Test",
                    "year": 2025,
                    "text_clean": f"{state} motion text with enough content.",
                    "landesverband": state,
                }
            ]
        ).to_parquet(parquet_path)
        paths.append(parquet_path)

    captured = {}

    class FakePipe:
        def run(self, pipeline_input):
            documents = pipeline_input["splitter"]["documents"]
            captured["document_ids"] = [doc.id for doc in documents]
            return {"writer": {"documents_written": len(documents)}}

    monkeypatch.setattr(
        indexing,
        "build_parquet_indexing_pipeline",
        lambda **_: FakePipe(),
    )

    result = indexing.run_indexing_from_parquets(paths)

    assert captured["document_ids"] == ["hessen-1", "nrw-1"]
    assert result["writer"]["documents_written"] == 2
    assert result["loader"]["documents_loaded"] == 2
    assert result["loader"]["parquet_files"] == 2
