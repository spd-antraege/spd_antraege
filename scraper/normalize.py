"""
Normalize motions from different states to a common schema.

Handles kuerzel mapping, status normalization, year extraction,
submitter type classification, and stable ID generation.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata


def normalize_motion(motion: dict, config: dict) -> dict:
    """Normalize a motion dict to Berlin-compatible schema."""
    state = config.get("state", "unknown")
    text = motion.get("text_content", "")

    # Kuerzel: prefix if configured
    kuerzel = motion.get("kuerzel", "")
    prefix = config.get("kuerzel_prefix", "")
    if prefix and not kuerzel.startswith(prefix):
        kuerzel = f"{prefix}{kuerzel}"

    # Year: extract from veranstaltung or kuerzel
    year = _extract_year(motion)

    # Submitter type: classify from raw text
    submitter_raw = motion.get("antragsteller", "")
    submitter_type = classify_submitter_type(submitter_raw)

    # Stable ID
    doc_id = compute_stable_id(kuerzel, text, state)

    # Content hash
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12] if text else ""

    return {
        "id": doc_id,
        "kuerzel": kuerzel,
        "title": motion.get("titel", ""),
        "year": year,
        "submitter_raw": submitter_raw,
        "submitter_type": submitter_type,
        "status_raw": motion.get("status", ""),
        "doc_type": motion.get("tagesordnungspunkt", ""),
        "veranstaltung": motion.get("veranstaltung", ""),
        "source_url": motion.get("source_url", ""),
        "text_clean": _clean_text(text),
        "content_hash": content_hash,
        "landesverband": state,
    }


def _extract_year(motion: dict) -> int | None:
    """Extract year from motion metadata."""
    # Try kuerzel first (e.g. "100/II/2018" → 2018)
    kuerzel = motion.get("kuerzel", "")
    year_match = re.search(r"(20\d{2})", kuerzel)
    if year_match:
        return int(year_match.group(1))

    # Try veranstaltung
    veranstaltung = motion.get("veranstaltung", "")
    year_match = re.search(r"(20\d{2})", veranstaltung)
    if year_match:
        return int(year_match.group(1))

    return None


def classify_submitter_type(submitter: str) -> str:
    """Classify submitter into type categories."""
    if not submitter:
        return "Unknown"

    s = submitter.lower()

    if any(k in s for k in ["kreisverband", "kdv", "kreis "]):
        return "KDV"
    if any(k in s for k in ["abteilung", "abt."]):
        return "Abteilung"
    if any(k in s for k in ["jusos", "juso"]):
        return "AG"
    if any(k in s for k in ["landesvorstand", "parteivorstand"]):
        return "Landesvorstand"
    if any(k in s for k in ["ag ", "arbeitsgemeinschaft", "afa", "asf", "asj",
                              "asg", "afb", "spd 60", "queer"]):
        return "AG"
    if any(k in s for k in ["fraktion", "fraktionsantrag"]):
        return "FA"
    if any(k in s for k in ["forum", "fachausschuss"]):
        return "FA"
    if any(k in s for k in ["bezirk", "unterbezirk"]):
        return "KDV"
    if any(k in s for k in ["ortsverein", "ov "]):
        return "Abteilung"

    return "Unknown"


def compute_stable_id(kuerzel: str, text: str, state: str) -> str:
    """Compute a stable document ID from kuerzel + state."""
    raw = f"{state}:{kuerzel}"
    normalized = unicodedata.normalize("NFKD", raw)
    normalized = normalized.encode("ascii", "ignore").decode("ascii").lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")

    # Add content hash suffix for collision safety
    content_hash = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8] if text else "empty"
    return f"{normalized}-{content_hash}"


def _clean_text(text: str) -> str:
    """Basic text cleanup."""
    text = text.replace("\r\n", "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
