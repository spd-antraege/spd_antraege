"""Shared fixtures for PIS tests."""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

MD_DIR = REPO_ROOT / "corpus/berlin"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _env(key):
    import os
    return os.environ.get(key, "")


requires_corpus = pytest.mark.skipif(
    not MD_DIR.exists(), reason="corpus/berlin/ not found"
)

requires_vps = pytest.mark.skipif(
    not _env("PIS_DB_PASSWORD"),
    reason="PIS_DB_PASSWORD not set -- not running on VPS with Doppler",
)

requires_rocketchat = pytest.mark.skipif(
    not _env("ROCKETCHAT_AUTH_TOKEN"),
    reason="ROCKETCHAT_AUTH_TOKEN not set",
)

requires_parquet = pytest.mark.skipif(
    not (REPO_ROOT / "data" / "derived" / "antraege.parquet").exists(),
    reason="data/derived/antraege.parquet not found -- run pipeline first",
)
