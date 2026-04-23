"""Stage A: Discover, parse, and validate corpus files."""

from __future__ import annotations

import sys
from pathlib import Path

# Reuse battle-tested parsing from sync_antraege.py
SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from sync_antraege import (  # noqa: E402
    parse_markdown_frontmatter,
    parse_kuerzel,
    normalize_text,
    compute_content_hash,
    source_doc_id_from_kuerzel,
)


def discover_corpus(md_dir: Path) -> list[Path]:
    """Find all .md files in the corpus directory, sorted."""
    return sorted(md_dir.rglob("*.md"))


def parse_antrag(path: Path) -> dict:
    """Parse a single Antrag .md file into a raw record.

    Returns a dict with frontmatter fields + body text + path metadata.
    Raises ValueError if kuerzel is missing.
    """
    fm, body = parse_markdown_frontmatter(path)

    kuerzel = fm.get("kuerzel", "")
    if not kuerzel:
        raise ValueError(f"Missing kuerzel in frontmatter: {path}")

    parsed_k = parse_kuerzel(kuerzel)

    # Compute relative path from corpus/berlin/
    # Walk up to find corpus/berlin parent
    rel_path = str(path)
    idx = rel_path.find("corpus/berlin/")
    if idx >= 0:
        rel_path = rel_path[idx:]

    return {
        "kuerzel": kuerzel,
        "title": fm.get("titel", path.stem),
        "status_raw": fm.get("status_in_tabelle", ""),
        "submitter_raw": fm.get("antragsteller", ""),
        "veranstaltung_raw": fm.get("veranstaltung", ""),
        "doc_type": fm.get("tagesordnungspunkt", ""),
        "source_url": fm.get("source_url", ""),
        "pdf_url": fm.get("pdf_url", ""),
        "tags_raw": fm.get("tags", []) or [],
        "ueberwiesen_an": fm.get("ueberwiesen_an", ""),
        "content_hash": fm.get("content_hash", "") or compute_content_hash(body),
        "text_md": normalize_text(body),
        "source_path": rel_path,
        "source_doc_id": source_doc_id_from_kuerzel(kuerzel),
        "_parsed_kuerzel": parsed_k,
        "_path": path,
    }
