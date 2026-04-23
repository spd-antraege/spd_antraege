"""Tests for MCP RAG server helpers."""

import sys
from pathlib import Path

# Make tools importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from mcp_rag_server import _filter_hits_by_metadata


def test_filter_hits_by_metadata_plain_shape():
    hits = [
        {
            "content": "foo",
            "document": {
                "metadata": {
                    "year": "2025",
                    "status_in_tabelle": "Annahme",
                    "antragsteller": "Jusos",
                }
            },
        }
    ]
    filters = {"year": "2025", "status_in_tabelle": "Annahme", "antragsteller": ""}
    out = _filter_hits_by_metadata(hits, filters)
    assert len(out) == 1


def test_filter_hits_by_metadata_segment_wrapped_shape():
    hits = [
        {
            "segment": {
                "content": "foo",
                "document": {
                    "metadata": {
                        "year": "2025",
                        "status_in_tabelle": "Annahme",
                        "antragsteller": "Jusos",
                    }
                },
            }
        }
    ]
    filters = {"year": "2025", "status_in_tabelle": "Annahme", "antragsteller": ""}
    out = _filter_hits_by_metadata(hits, filters)
    assert len(out) == 1


def test_filter_hits_by_metadata_segment_wrapped_non_match():
    hits = [
        {
            "segment": {
                "content": "foo",
                "document": {
                    "metadata": {
                        "year": "2024",
                        "status_in_tabelle": "Annahme",
                        "antragsteller": "Jusos",
                    }
                },
            }
        }
    ]
    filters = {"year": "2025", "status_in_tabelle": "", "antragsteller": ""}
    out = _filter_hits_by_metadata(hits, filters)
    assert out == []
