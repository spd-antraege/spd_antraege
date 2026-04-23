"""
Parser for PDF Antragsbücher.

Used by: SPD Bund, NRW, BaWü, Niedersachsen, Sachsen, Hessen, MV, etc.
Downloads PDFs, extracts text with pdfplumber, segments into individual motions.

SPD Antragsbücher use two main formats:
  1. "Antrag [N]" headers (Bund, BaWü, some LVs)
  2. Code-based headers like "AW3", "BA7", "B3" (Niedersachsen, NRW)

The segmenter handles both by detecting motion boundaries from context.
"""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

import requests


CACHE_DIR = Path("data/pdf_cache")

# Common motion header patterns across LVs
MOTION_PATTERNS = [
    # "Antrag 123" or "Antrag Nr. 123" or "Antrag 12.1"
    r"^Antrag(?:\s+Nr\.?)?\s+(\d+[\w.]*)\b",
    # Code-based: "AW3", "BA7", "B3", "SG2", "F5" at line start, followed by submitter
    r"^([A-Z]{1,3}\d+)\s+(?:AfA|AfB|ASF|ASG|ASJ|Jusos|OV|UB|BZ|KV|SPD|AG)\b",
    # "Initiativantrag" or "Dringlichkeitsantrag"
    r"^((?:Initiativ|Dringlichkeits)antrag(?:\s+\d+)?)\b",
]


class PdfParser:
    """Extracts individual motions from PDF Antragsbücher."""

    def __init__(self, config: dict):
        self.config = config
        self.delay = config.get("scrape_delay", 1.0)
        self.status_map = config.get("status_map", {})

    def discover_events(self) -> list[dict]:
        """List PDF sources configured for this state."""
        pdf_sources = self.config.get("pdf_sources", [])
        return [{
            "event_id": p.get("label", p["url"]),
            "label": p.get("label", p["url"]),
            "url": p["url"],
            "veranstaltung": p.get("veranstaltung", p.get("label", "")),
            "year": p.get("year"),
        } for p in pdf_sources]

    def list_motions(self, event: dict) -> list[dict]:
        """Download PDF, extract text, segment into individual motions."""
        url = event.get("url", "")
        if not url:
            return []

        # Download to cache
        pdf_path = self._download_pdf(url)
        if not pdf_path:
            return []

        # Extract full text
        text = self._extract_text(pdf_path)
        if not text:
            return []

        # Segment into individual motions
        motions = self._segment(text)

        # Enrich with event metadata
        veranstaltung = event.get("veranstaltung", "")
        year = event.get("year")
        for m in motions:
            m["veranstaltung"] = veranstaltung
            m["source_url"] = url
            if year and not m.get("year"):
                m["year"] = year

        return motions

    def fetch_content(self, motion: dict) -> str:
        """Return content already extracted during list_motions."""
        return motion.get("text_content", "")

    def _download_pdf(self, url: str) -> Path | None:
        """Download PDF to cache dir. Returns cached path."""
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

        # Cache key from URL hash
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        filename = url.rsplit("/", 1)[-1] if "/" in url else f"{url_hash}.pdf"
        cache_path = CACHE_DIR / f"{url_hash}_{filename}"

        if cache_path.exists() and cache_path.stat().st_size > 1000:
            return cache_path

        try:
            resp = requests.get(url, timeout=60, headers={
                "User-Agent": "Mozilla/5.0 (compatible; SPD-Scraper/1.0)"
            })
            resp.raise_for_status()

            if len(resp.content) < 1000:
                print(f"    WARNING: PDF too small ({len(resp.content)} bytes), likely redirect")
                return None

            cache_path.write_bytes(resp.content)
            time.sleep(self.delay)
            return cache_path

        except Exception as e:
            print(f"    ERROR downloading {url}: {e}")
            return None

    def _extract_text(self, pdf_path: Path) -> str:
        """Extract all text from PDF using pdfplumber."""
        import pdfplumber

        pages_text = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    # Remove page headers (repeated on every page)
                    lines = text.split("\n")
                    # Skip lines that look like headers (short, repeated pattern)
                    cleaned = []
                    for line in lines:
                        # Skip "SPD [LV] Antragsbuch" header + "ordentlicher Landesparteitag" + date/location
                        if re.match(r"^SPD\s+\w+\s+Antragsbuch", line):
                            continue
                        if re.match(r"^ordentlicher\s+Landesparteitag", line, re.IGNORECASE):
                            continue
                        # Skip line numbers at start (pdfplumber artifact)
                        line = re.sub(r"^\d+\s+", "", line)
                        cleaned.append(line)
                    pages_text.append("\n".join(cleaned))

        return "\n\n".join(pages_text)

    def _segment(self, text: str) -> list[dict]:
        """Split full PDF text into individual motions.

        Detects motion boundaries using multiple patterns and context.
        """
        lines = text.split("\n")
        motions = []
        current_motion = None
        current_lines = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if current_lines:
                    current_lines.append("")
                continue

            # Check if this line starts a new motion
            motion_match = self._match_motion_header(stripped)

            if motion_match:
                # Save previous motion
                if current_motion and current_lines:
                    current_motion["text_content"] = "\n".join(current_lines).strip()
                    if len(current_motion["text_content"]) > 50:
                        motions.append(current_motion)

                # Start new motion
                kuerzel, submitter_hint, title_hint = motion_match
                current_motion = {
                    "kuerzel": kuerzel,
                    "titel": title_hint or "",
                    "antragsteller": submitter_hint or "",
                }
                current_lines = [stripped]
            elif current_motion:
                current_lines.append(stripped)

                # Try to extract submitter and title from early lines
                if len(current_lines) <= 5:
                    if not current_motion["antragsteller"] and self._looks_like_submitter(stripped):
                        current_motion["antragsteller"] = stripped
                    elif not current_motion["titel"] and len(stripped) > 20 and not stripped.startswith("Begründung"):
                        current_motion["titel"] = stripped[:200]

        # Don't forget last motion
        if current_motion and current_lines:
            current_motion["text_content"] = "\n".join(current_lines).strip()
            if len(current_motion["text_content"]) > 50:
                motions.append(current_motion)

        return motions

    def _match_motion_header(self, line: str) -> tuple[str, str, str] | None:
        """Check if a line starts a new motion.

        Returns (kuerzel, submitter_hint, title_hint) or None.
        """
        for pattern in MOTION_PATTERNS:
            m = re.match(pattern, line)
            if m:
                kuerzel = m.group(1) if m.lastindex else m.group(0)

                # Extract submitter and title from the rest of the line
                rest = line[m.end():].strip(" -–—")
                submitter = ""
                title = ""

                # Pattern: "AW3 AfB Niedersachsen - Title text here"
                sub_match = re.match(
                    r"((?:AfA|AfB|ASF|ASG|ASJ|Jusos|OV|UB|BZ|KV|SPD|AG)\s+[\w\s-]+?)\s*[-–—]\s*(.*)",
                    rest,
                )
                if sub_match:
                    submitter = sub_match.group(1).strip()
                    title = sub_match.group(2).strip()
                elif rest:
                    title = rest

                return kuerzel, submitter, title

        # Special: "Antrag [N]" on its own line (Bund-style)
        m = re.match(r"^Antrag\s+(\d+[\w./]*)$", line)
        if m:
            return f"Antrag {m.group(1)}", "", ""

        return None

    def _looks_like_submitter(self, line: str) -> bool:
        """Heuristic: does this line look like a submitter attribution?"""
        submitter_keywords = [
            "antragsteller", "eingebracht von", "eingereicht von",
            "kreisverband", "ortsverein", "unterbezirk", "bezirk",
            "jusos", "afa", "afb", "asf", "asg",
            "landesvorstand", "parteivorstand", "fraktion",
        ]
        lower = line.lower()
        return any(kw in lower for kw in submitter_keywords)
