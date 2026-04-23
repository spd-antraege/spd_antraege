"""Canonical record schema for the SPD Berlin Antragskorpus."""

from __future__ import annotations

from typing import TypedDict


class CanonicalRecord(TypedDict, total=False):
    """One row in data/derived/antraege.parquet."""

    # Identifiers
    id: str                     # SHA1 of pdf_url > source_url > source_path
    source_path: str            # relative path under corpus/berlin/
    source_url: str
    pdf_url: str
    source_doc_id: str          # kuerzel-based slug (for human readability)

    # Time
    parteitag_id: str           # e.g. "II/2022"
    parteitag_date: str | None  # "YYYY-MM-DD" or None
    year: int | None
    month: int | None

    # Actors
    submitter_raw: str          # original antragsteller
    submitter_type: str         # Landesvorstand | KDV | Abteilung | AG | FA | Bezirk | Unknown

    # Document descriptors
    kuerzel: str
    title: str
    doc_type: str               # from tagesordnungspunkt
    status_raw: str
    tags_raw: list[str]
    tag_count: int

    # Referrals
    ueberwiesen_an: str

    # Text variants
    text_md: str                # raw body
    text_plain: str             # markdown-stripped
    text_clean: str             # de-boilerplated

    # Derived metrics
    word_count: int
    char_count: int
    boilerplate_share: float

    # Quality flags
    missing_text: bool
    date_parse_ok: bool
    tag_suspect_broad: bool
    conversion_artifacts_hint: bool

    # Metadata
    content_hash: str
    veranstaltung_raw: str
