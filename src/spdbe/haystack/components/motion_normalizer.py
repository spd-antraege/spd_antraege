"""MotionNormalizer: Parse .md files into normalized Haystack Documents.

Wraps the existing ingest + normalize + text_clean pipeline stages
as a single Haystack v2 component.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from haystack import Document, component

from spdbe.haystack.converters import record_to_document
from spdbe.ingest import discover_corpus, parse_antrag
from spdbe.normalize import (
    classify_submitter_type,
    compute_stable_id,
    parse_veranstaltung_date,
)
from spdbe.text_clean import (
    build_boilerplate_index,
    compute_boilerplate_share,
    deboilerplate,
    strip_markdown,
)


@component
class MotionNormalizer:
    """Parse SPD motion .md files into normalized Haystack Documents.

    Combines three pipeline stages:
    - Stage A: Parse frontmatter + body from markdown files
    - Stage B: Normalize dates, submitter types, compute stable IDs
    - Stage C: Strip markdown, remove boilerplate, compute metrics

    The boilerplate index is either loaded from a pre-computed JSON file
    or built on-the-fly from the input corpus (slower but self-contained).
    """

    def __init__(
        self,
        boilerplate_index_path: Optional[str] = None,
        boilerplate_threshold: float = 0.05,
        landesverband: str = "berlin",
    ):
        self.boilerplate_index_path = boilerplate_index_path
        self.boilerplate_threshold = boilerplate_threshold
        self.landesverband = landesverband
        self._boilerplate_index: set[str] | None = None

    def warm_up(self):
        """Load boilerplate index if path is provided."""
        if self.boilerplate_index_path:
            path = Path(self.boilerplate_index_path)
            if path.exists():
                data = json.loads(path.read_text())
                self._boilerplate_index = set(data.get("phrases", []))

    @component.output_types(documents=List[Document])
    def run(self, sources: List[str]) -> dict:
        """Process .md file paths into normalized Documents.

        Args:
            sources: List of file paths to .md files.

        Returns:
            dict with "documents" key containing List[Document].
        """
        # Stage A: Parse
        raw_records = []
        for source in sources:
            path = Path(source)
            if not path.exists():
                continue
            try:
                doc = parse_antrag(path)
                raw_records.append(doc)
            except (ValueError, Exception):
                continue

        # Stage B: Normalize
        for doc in raw_records:
            doc["id"] = compute_stable_id(doc)

            date_info = parse_veranstaltung_date(doc.get("veranstaltung_raw", ""))
            doc["parteitag_id"] = date_info["parteitag_id"]
            doc["parteitag_date"] = date_info["parteitag_date"]
            doc["date_parse_ok"] = date_info["parteitag_date"] is not None
            doc["year"] = date_info["year"]
            doc["month"] = date_info["month"]

            if doc["year"] is None and doc.get("_parsed_kuerzel"):
                doc["year"] = int(doc["_parsed_kuerzel"]["year"])

            doc["submitter_type"] = classify_submitter_type(
                doc.get("submitter_raw", "")
            )
            doc["tag_count"] = len(doc.get("tags_raw", []))

        # Stage C: Text cleaning
        # Build or use pre-computed boilerplate index
        bp_index = self._boilerplate_index
        if bp_index is None and raw_records:
            all_texts = [doc.get("text_md", "") for doc in raw_records]
            bp_index = build_boilerplate_index(
                all_texts, threshold=self.boilerplate_threshold
            )

        for doc in raw_records:
            text_md = doc.get("text_md", "")
            doc["text_plain"] = strip_markdown(text_md)
            doc["text_clean"] = deboilerplate(doc["text_plain"], bp_index)
            doc["word_count"] = len(doc["text_clean"].split())
            doc["char_count"] = len(doc["text_clean"])
            doc["boilerplate_share"] = compute_boilerplate_share(
                doc["text_plain"], doc["text_clean"]
            )
            doc["missing_text"] = doc["word_count"] < 10
            doc["conversion_artifacts_hint"] = _check_conversion_artifacts(text_md)

        # Convert to Haystack Documents
        documents = [
            record_to_document(doc, landesverband=self.landesverband)
            for doc in raw_records
        ]

        return {"documents": documents}


def save_boilerplate_index(
    md_dir: str | Path,
    output_path: str | Path,
    threshold: float = 0.05,
) -> int:
    """Pre-compute and save the boilerplate index for a corpus.

    Returns the number of boilerplate phrases found.
    """
    md_dir = Path(md_dir)
    output_path = Path(output_path)

    paths = discover_corpus(md_dir)
    texts = []
    for path in paths:
        try:
            doc = parse_antrag(path)
            text_md = doc.get("text_md", "")
            texts.append(strip_markdown(text_md))
        except (ValueError, Exception):
            continue

    bp_index = build_boilerplate_index(texts, threshold=threshold)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps({"phrases": sorted(bp_index)}, ensure_ascii=False, indent=2)
    )

    return len(bp_index)


def _check_conversion_artifacts(text: str) -> bool:
    """Heuristic: many isolated short lines suggest PDF conversion artifacts."""
    lines = text.split("\n")
    if len(lines) < 5:
        return False
    short_lines = sum(1 for line in lines if 0 < len(line.strip()) < 40)
    ratio = short_lines / len(lines)
    return ratio > 0.5
