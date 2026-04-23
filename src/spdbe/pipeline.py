"""Orchestrator: Stages A → B → C → parquet output."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from spdbe.ingest import discover_corpus, parse_antrag
from spdbe.normalize import compute_stable_id, parse_veranstaltung_date, classify_submitter_type
from spdbe.text_clean import strip_markdown, deboilerplate, build_boilerplate_index, compute_boilerplate_share


def run_pipeline(
    md_dir: Path,
    output_path: Path,
    boilerplate_threshold: float = 0.05,
    verbose: bool = False,
) -> pd.DataFrame:
    """Run the full corpus processing pipeline.

    Stage A: Discover and parse all .md files
    Stage B: Normalize dates, submitter types, compute IDs
    Stage C: Clean text, de-boilerplate, compute metrics
    Output: Write parquet
    """
    # --- Stage A: Ingest ---
    paths = discover_corpus(md_dir)
    if verbose:
        print(f"Stage A: Found {len(paths)} files", file=sys.stderr)

    raw_records = []
    parse_errors = []
    for path in paths:
        try:
            doc = parse_antrag(path)
            raw_records.append(doc)
        except Exception as e:
            parse_errors.append({"path": str(path), "error": str(e)})

    if verbose:
        print(f"Stage A: Parsed {len(raw_records)}, errors: {len(parse_errors)}", file=sys.stderr)

    # --- Stage B: Normalize ---
    for doc in raw_records:
        # Stable ID
        doc["id"] = compute_stable_id(doc)

        # Date normalization
        date_info = parse_veranstaltung_date(doc.get("veranstaltung_raw", ""))
        doc["parteitag_id"] = date_info["parteitag_id"]
        doc["parteitag_date"] = date_info["parteitag_date"]
        doc["date_parse_ok"] = date_info["parteitag_date"] is not None

        # Year/month: prefer parsed date, fallback to kuerzel
        doc["year"] = date_info["year"]
        doc["month"] = date_info["month"]
        if doc["year"] is None and doc.get("_parsed_kuerzel"):
            doc["year"] = int(doc["_parsed_kuerzel"]["year"])

        # Submitter type
        doc["submitter_type"] = classify_submitter_type(doc.get("submitter_raw", ""))

        # Tag count
        doc["tag_count"] = len(doc.get("tags_raw", []))

    if verbose:
        print(f"Stage B: Normalized {len(raw_records)} records", file=sys.stderr)

    # --- Stage C: Text cleaning ---
    # First pass: collect all texts for boilerplate index
    all_texts = [doc.get("text_md", "") for doc in raw_records]
    boilerplate_index = build_boilerplate_index(all_texts, threshold=boilerplate_threshold)

    if verbose:
        print(f"Stage C: Built boilerplate index ({len(boilerplate_index)} phrases)", file=sys.stderr)

    # Compute tag_count p95 for quality flag
    tag_counts = sorted(doc["tag_count"] for doc in raw_records)
    p95_idx = int(len(tag_counts) * 0.95)
    tag_suspect_threshold = tag_counts[p95_idx] if tag_counts else 0

    for doc in raw_records:
        text_md = doc.get("text_md", "")

        # text_plain: markdown stripped
        doc["text_plain"] = strip_markdown(text_md)

        # text_clean: de-boilerplated
        doc["text_clean"] = deboilerplate(doc["text_plain"], boilerplate_index)

        # Metrics
        doc["word_count"] = len(doc["text_clean"].split())
        doc["char_count"] = len(doc["text_clean"])
        doc["boilerplate_share"] = compute_boilerplate_share(doc["text_plain"], doc["text_clean"])

        # Quality flags
        doc["missing_text"] = doc["word_count"] < 10
        doc["tag_suspect_broad"] = doc["tag_count"] > tag_suspect_threshold
        doc["conversion_artifacts_hint"] = _check_conversion_artifacts(text_md)

    if verbose:
        print(f"Stage C: Cleaned {len(raw_records)} records", file=sys.stderr)

    # --- Build DataFrame ---
    columns = [
        "id", "source_path", "source_url", "pdf_url", "source_doc_id",
        "parteitag_id", "parteitag_date", "year", "month",
        "submitter_raw", "submitter_type",
        "kuerzel", "title", "doc_type", "status_raw", "tags_raw", "tag_count",
        "ueberwiesen_an",
        "text_md", "text_plain", "text_clean",
        "word_count", "char_count", "boilerplate_share",
        "missing_text", "date_parse_ok", "tag_suspect_broad", "conversion_artifacts_hint",
        "content_hash", "veranstaltung_raw",
    ]

    rows = []
    for doc in raw_records:
        row = {}
        for col in columns:
            val = doc.get(col)
            if col == "tags_raw" and isinstance(val, list):
                val = val  # keep as list for parquet
            row[col] = val
        rows.append(row)

    df = pd.DataFrame(rows, columns=columns)

    # Write parquet
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False, engine="pyarrow")

    if verbose:
        print(f"Output: {len(df)} rows → {output_path}", file=sys.stderr)
        print(f"  Date parse rate: {df['date_parse_ok'].mean():.1%}", file=sys.stderr)
        print(f"  Missing text: {df['missing_text'].sum()}", file=sys.stderr)
        print(f"  Avg word count: {df['word_count'].mean():.0f}", file=sys.stderr)

    return df


def _check_conversion_artifacts(text: str) -> bool:
    """Heuristic: many isolated short lines suggest PDF conversion artifacts."""
    lines = text.split("\n")
    if len(lines) < 5:
        return False
    short_lines = sum(1 for l in lines if 0 < len(l.strip()) < 40)
    ratio = short_lines / len(lines)
    return ratio > 0.5
