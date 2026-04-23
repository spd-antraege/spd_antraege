"""Convert between canonical record dicts and Haystack Documents."""

from __future__ import annotations

from haystack import Document


# Fields that go into Document.meta (everything except content and id)
META_FIELDS = [
    "source_path", "source_url", "pdf_url", "source_doc_id",
    "parteitag_id", "parteitag_date", "year", "month",
    "submitter_raw", "submitter_type",
    "kuerzel", "title", "doc_type", "status_raw", "tags_raw", "tag_count",
    "ueberwiesen_an",
    "text_md", "text_plain",
    "word_count", "char_count", "boilerplate_share",
    "missing_text", "date_parse_ok", "tag_suspect_broad",
    "conversion_artifacts_hint",
    "content_hash", "veranstaltung_raw",
    "landesverband",
]


def record_to_document(record: dict, landesverband: str = "berlin") -> Document:
    """Convert a canonical record dict to a Haystack Document.

    Document.content = text_clean (the searchable, de-boilerplated text)
    Document.id = record['id'] (SHA1 stable ID)
    Document.meta = all other fields
    """
    meta = {}
    for field in META_FIELDS:
        if field in record:
            meta[field] = record[field]

    # Ensure landesverband is always set
    if "landesverband" not in meta:
        meta["landesverband"] = landesverband

    return Document(
        id=record.get("id", ""),
        content=record.get("text_clean", ""),
        meta=meta,
    )


def document_to_record(doc: Document) -> dict:
    """Convert a Haystack Document back to a canonical record dict."""
    record = {
        "id": doc.id,
        "text_clean": doc.content or "",
    }
    if doc.meta:
        record.update(doc.meta)
    return record
