"""Stage B: Normalize dates, submitter types, compute stable IDs."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import yaml

# German month names for date parsing
GERMAN_MONTHS = {
    "Januar": 1, "Februar": 2, "März": 3, "April": 4,
    "Mai": 5, "Juni": 6, "Juli": 7, "August": 8,
    "September": 9, "Oktober": 10, "November": 11, "Dezember": 12,
}

# Compiled regex for parteitag_id extraction
_RE_PARTEITAG_ID = re.compile(r"(I{1,4}V?)/(\d{4})")

# Multi-day events: "01./02.06.2018" or "01./02. Juni 2018"
_RE_MULTI_DAY = re.compile(r"(\d{1,2})\./\d{1,2}\.(\d{1,2})\.(\d{4})")

# Compiled regex for DD.MM.YYYY dates
_RE_DATE_DMY = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")

# Compiled regex for DD. Month YYYY dates
_RE_DATE_DMONTHY = re.compile(
    r"(\d{1,2})\.\s*("
    + "|".join(GERMAN_MONTHS.keys())
    + r")\s+(\d{4})"
)


def parse_veranstaltung_date(raw: str) -> dict:
    """Parse veranstaltung field into parteitag_id and date.

    Returns dict with:
        parteitag_id: str or None (e.g. "II/2022")
        parteitag_date: str or None (e.g. "2022-11-12")
        year: int or None
        month: int or None
    """
    raw = (raw or "").strip().strip('"').replace("\\n", " ")

    # Handle multi-value: take first entry
    if "," in raw:
        raw = raw.split(",")[0].strip()

    result = {
        "parteitag_id": None,
        "parteitag_date": None,
        "year": None,
        "month": None,
    }

    # Extract parteitag_id
    m = _RE_PARTEITAG_ID.search(raw)
    if m:
        result["parteitag_id"] = f"{m.group(1)}/{m.group(2)}"
        result["year"] = int(m.group(2))

    # Try multi-day first: "01./02.06.2018" → take first day
    m = _RE_MULTI_DAY.search(raw)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            result["parteitag_date"] = f"{year:04d}-{month:02d}-{day:02d}"
            result["year"] = year
            result["month"] = month
            return result

    # Try DD.MM.YYYY (most common)
    m = _RE_DATE_DMY.search(raw)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            result["parteitag_date"] = f"{year:04d}-{month:02d}-{day:02d}"
            result["year"] = year
            result["month"] = month
            return result

    # Try DD. Month YYYY
    m = _RE_DATE_DMONTHY.search(raw)
    if m:
        day = int(m.group(1))
        month = GERMAN_MONTHS.get(m.group(2))
        year = int(m.group(3))
        if month and 1 <= day <= 31:
            result["parteitag_date"] = f"{year:04d}-{month:02d}-{day:02d}"
            result["year"] = year
            result["month"] = month
            return result

    return result


def compute_stable_id(doc: dict) -> str:
    """Compute SHA1 stable ID.

    Uses source_path as primary key — it's the only field guaranteed unique
    across the corpus (some docs share pdf_url or source_url due to
    replacement Anträge and website deduplication).
    """
    # source_path is unique per file and deterministic
    source_path = (doc.get("source_path") or "").strip()
    if source_path:
        return hashlib.sha1(source_path.encode("utf-8")).hexdigest()

    # Fallback chain
    for field in ("source_url", "pdf_url"):
        val = (doc.get(field) or "").strip()
        if val:
            return hashlib.sha1(val.encode("utf-8")).hexdigest()

    return hashlib.sha1((doc.get("kuerzel", "unknown")).encode("utf-8")).hexdigest()


# Submitter classification rules (loaded from config or hardcoded defaults)
_DEFAULT_SUBMITTER_RULES = [
    (re.compile(r"^Landesvorstand"), "Landesvorstand"),
    (re.compile(r"^KDV\b"), "KDV"),
    (re.compile(r"^(Abt\.|Abteilung)\s"), "Abteilung"),
    (re.compile(r"^(AfA|AfB|AG\s|ASF|ASJ|Jusos|Forum\s|Schwusos|AG Selbst|AGS\b|60plus|Netzwerk|Queer)"), "AG"),
    (re.compile(r"^FA\s"), "FA"),
    (re.compile(r"^Bezirk"), "Bezirk"),
]


def classify_submitter_type(raw: str) -> str:
    """Classify antragsteller into a canonical type."""
    raw = (raw or "").strip()
    if not raw:
        return "Unknown"

    for pattern, stype in _DEFAULT_SUBMITTER_RULES:
        if pattern.search(raw):
            return stype

    return "Unknown"


def load_submitter_rules(config_path: Path) -> None:
    """Load submitter rules from config YAML (optional override)."""
    global _DEFAULT_SUBMITTER_RULES

    with open(config_path) as f:
        config = yaml.safe_load(f)

    rules = config.get("submitter_rules", [])
    if rules:
        _DEFAULT_SUBMITTER_RULES = [
            (re.compile(r["pattern"]), r["type"])
            for r in rules
            if r.get("pattern")
        ]
