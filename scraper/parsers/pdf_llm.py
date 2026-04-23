"""
LLM-powered PDF Antrag extraction using Mistral Small.

Replaces regex-based segmentation with structured extraction:
1. pdfplumber extracts text per page
2. Mistral Small extracts individual Anträge with metadata
3. Results normalized to common schema

Usage:
    from scraper.parsers.pdf_llm import LlmPdfParser
    parser = LlmPdfParser(config)
    events = parser.discover_events()
    motions = parser.list_motions(events[0])
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import requests

CACHE_DIR = Path("data/pdf_cache")
EXTRACTION_CACHE_DIR = Path("data/pdf_cache/extractions")

EXTRACTION_PROMPT = """\
Du erhältst eine Seite aus einem SPD-Antragsbuch. Extrahiere alle Anträge auf dieser Seite.

## Seitentypen

1. INHALTSVERZEICHNIS / ÜBERSICHT: Seiten, die Anträge nur auflisten (Kürzel + Titel, \
ohne Antragstext). Setze "page_type": "toc" und extrahiere nur kuerzel und titel. \
Kein text-Feld nötig.

2. ANTRAGSSEITE: Seiten mit vollständigem Antragstext. Setze "page_type": "content".

3. FORTSETZUNG: Seiten, die einen Antrag von der vorherigen Seite fortsetzen. \
Setze "continuation": true. Versuche das Kürzel des fortgesetzten Antrags zu erkennen \
(oft in der Kopfzeile oder am Seitenrand). Falls kein Kürzel erkennbar: \
setze kuerzel auf "CONTINUE_PREV".

4. KEINE ANTRÄGE: Deckblatt, Grußwort, Organisatorisches. Gib ein leeres Array zurück.

## Felder pro Antrag

- kuerzel: Die Antragsnummer. Normalisiere: entferne "Antrag " Präfix. \
Beispiele: "A01", "Ar03", "S5", "LPT-01/I/2025"
- titel: Der Titel des Antrags (PFLICHT wenn vorhanden)
- antragsteller: Wer den Antrag stellt (PFLICHT — suche aktiv danach). \
Steht oft unter dem Titel oder am Anfang des Antragstexts. \
Beispiele: "Landesvorstand", "UB Köln", "OV Südstadt", "Jusos NRW", \
"AfA-Landesvorstand", "KV Düsseldorf"
- status: Status ODER Empfehlung der Antragskommission. \
Suche nach: "Empfehlung:", "Votum:", "Beschluss:", oder Marginalien wie \
"Annahme", "Überweisung an...", "Ablehnung", "Erledigt durch...". \
Auch "Empfehlung der Antragskommission: Annahme in der Fassung der AK" zählt.
- sachgebiet: Themenbereich falls angegeben
- text: Der Antragstext (so vollständig wie auf dieser Seite vorhanden)

Antworte NUR mit validem JSON:
[
  {
    "kuerzel": "...",
    "titel": "...",
    "antragsteller": "...",
    "status": "...",
    "sachgebiet": "...",
    "text": "...",
    "page_type": "content",
    "continuation": false
  }
]

Seitentext:
"""


class LlmPdfParser:
    """Extract Anträge from PDF Antragsbücher using Mistral Small."""

    def __init__(self, config: dict):
        self.config = config
        self.delay = config.get("scrape_delay", 1.0)
        self.status_map = config.get("status_map", {})
        self.api_key = os.environ.get("MISTRAL_API_KEY", "")
        self.model = "mistral-small-latest"

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
        """Download PDF, extract per page with LLM, merge continuations."""
        url = event.get("url", "")
        if not url:
            return []

        pdf_path = self._download_pdf(url)
        if not pdf_path:
            return []

        # Check extraction cache
        cache_key = hashlib.md5(url.encode()).hexdigest()[:12]
        cache_path = EXTRACTION_CACHE_DIR / f"{cache_key}.json"
        if cache_path.exists():
            print(f"  Using cached extraction: {cache_path}")
            return json.loads(cache_path.read_text())

        # Extract text per page
        pages = self._extract_pages(pdf_path)
        print(f"  {len(pages)} pages extracted from PDF")

        # LLM extraction per page
        all_extractions = []
        for i, page_text in enumerate(pages):
            if len(page_text.strip()) < 50:
                continue

            print(f"  [{i+1}/{len(pages)}] Extracting...", end="", flush=True)
            extracted = self._extract_page(page_text, i + 1)
            print(f" {len(extracted)} Anträge")
            all_extractions.extend(extracted)

            # Rate limiting
            time.sleep(0.3)

        # Merge continuations with their parent Antrag
        motions = self._merge_continuations(all_extractions)

        # Enrich with event metadata
        veranstaltung = event.get("veranstaltung", "")
        year = event.get("year")
        for m in motions:
            m["veranstaltung"] = veranstaltung
            m["source_url"] = url
            if year and not m.get("year"):
                m["year"] = year

        # Cache extractions
        EXTRACTION_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(motions, ensure_ascii=False, indent=2))

        return motions

    def fetch_content(self, motion: dict) -> str:
        """Return content already extracted during list_motions."""
        return motion.get("text_content", motion.get("text", ""))

    def _download_pdf(self, url: str) -> Path | None:
        """Download PDF to cache dir."""
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
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
                print(f"    WARNING: PDF too small ({len(resp.content)} bytes)")
                return None
            cache_path.write_bytes(resp.content)
            time.sleep(self.delay)
            return cache_path
        except Exception as e:
            print(f"    ERROR downloading {url}: {e}")
            return None

    def _extract_pages(self, pdf_path: Path) -> list[str]:
        """Extract text from each page using pdfplumber."""
        import pdfplumber

        pages = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                pages.append(text)
        return pages

    def _extract_page(self, page_text: str, page_num: int, retries: int = 2) -> list[dict]:
        """Use Mistral Small to extract Anträge from a single page."""
        if not self.api_key:
            raise ValueError("MISTRAL_API_KEY not set")

        prompt = EXTRACTION_PROMPT + page_text

        for attempt in range(retries + 1):
            try:
                return self._call_mistral(prompt, page_num)
            except requests.exceptions.HTTPError as e:
                if e.response is not None and e.response.status_code in (429, 503) and attempt < retries:
                    wait = 2 ** (attempt + 1)
                    print(f" (retry in {wait}s)", end="", flush=True)
                    time.sleep(wait)
                    continue
                print(f" (error: {e})", end="")
                return []
            except Exception as e:
                print(f" (error: {e})", end="")
                return []
        return []

    def _call_mistral(self, prompt: str, page_num: int) -> list[dict]:
        """Single Mistral API call with response parsing."""
        try:
            resp = requests.post(
                "https://api.mistral.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0,
                    "max_tokens": 4096,
                },
                timeout=30,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]

            # Strip markdown fences if present
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1] if "\n" in content else content[3:]
            if content.endswith("```"):
                content = content[:-3].strip()

            parsed = json.loads(content)
            # Handle both {"antraege": [...]} and [...] formats
            if isinstance(parsed, dict):
                parsed = parsed.get("antraege", parsed.get("data", []))
            if not isinstance(parsed, list):
                parsed = [parsed]

            # Add page number
            for item in parsed:
                item["page_number"] = page_num

            return parsed

        except json.JSONDecodeError:
            print(f" (JSON parse error)", end="")
            return []
        except Exception as e:
            print(f" (error: {e})", end="")
            return []

    def _merge_continuations(self, extractions: list[dict]) -> list[dict]:
        """Merge continuation pages and TOC entries into parent Anträge.

        Handles:
        - TOC entries (page_type=toc): metadata only, merged into content entries
        - Continuations: appended to previous motion by kürzel or sequence
        - Kürzel normalization: strips "Antrag " prefix, whitespace
        """
        motions = []
        kuerzel_map: dict[str, dict] = {}
        last_motion: dict | None = None

        for item in extractions:
            kuerzel = self._normalize_kuerzel(item.get("kuerzel") or "")
            if not kuerzel and not item.get("continuation"):
                continue

            is_continuation = item.get("continuation", False)
            is_toc = item.get("page_type") == "toc"

            # Handle CONTINUE_PREV — attach to the last seen motion
            if is_continuation and (kuerzel == "CONTINUE_PREV" or not kuerzel):
                if last_motion:
                    extra_text = item.get("text") or ""
                    if extra_text:
                        last_motion["text_content"] = (
                            (last_motion.get("text_content") or "") + "\n" + extra_text
                        )
                continue

            # Continuation with known kürzel
            if is_continuation and kuerzel in kuerzel_map:
                existing = kuerzel_map[kuerzel]
                extra_text = item.get("text") or ""
                if extra_text:
                    existing["text_content"] = (
                        (existing.get("text_content") or "") + "\n" + extra_text
                    )
                continue

            # TOC entry — seed metadata, content entry will overwrite later
            if is_toc:
                if kuerzel not in kuerzel_map:
                    motion = {
                        "kuerzel": kuerzel,
                        "titel": item.get("titel") or "",
                        "antragsteller": item.get("antragsteller") or "",
                        "status": self._map_status(item.get("status") or ""),
                        "sachgebiet": item.get("sachgebiet") or "",
                        "text_content": "",
                        "page_number": item.get("page_number"),
                        "_from_toc": True,
                    }
                    motions.append(motion)
                    kuerzel_map[kuerzel] = motion
                continue

            # Content entry — merge into TOC stub or create new
            if kuerzel in kuerzel_map:
                existing = kuerzel_map[kuerzel]
                # Overwrite TOC stub with real content
                if existing.get("_from_toc"):
                    existing.pop("_from_toc", None)
                    existing["text_content"] = item.get("text") or ""
                    existing["page_number"] = item.get("page_number")
                    # Fill in any fields TOC didn't have
                    for field in ("titel", "antragsteller", "status", "sachgebiet"):
                        val = item.get(field) or ""
                        if field == "status":
                            val = self._map_status(val)
                        if val and not existing.get(field):
                            existing[field] = val
                else:
                    # Duplicate kürzel from different page — append text
                    extra_text = item.get("text") or ""
                    if extra_text:
                        existing["text_content"] = (
                            (existing.get("text_content") or "") + "\n" + extra_text
                        )
                last_motion = existing
            else:
                motion = {
                    "kuerzel": kuerzel,
                    "titel": item.get("titel") or "",
                    "antragsteller": item.get("antragsteller") or "",
                    "status": self._map_status(item.get("status") or ""),
                    "sachgebiet": item.get("sachgebiet") or "",
                    "text_content": item.get("text") or "",
                    "page_number": item.get("page_number"),
                }
                motions.append(motion)
                kuerzel_map[kuerzel] = motion
                last_motion = motion

        # Clean up internal flags
        for m in motions:
            m.pop("_from_toc", None)

        return motions

    @staticmethod
    def _normalize_kuerzel(raw: str) -> str:
        """Normalize kürzel: strip 'Antrag ' prefix, whitespace."""
        k = raw.strip()
        # Remove common prefixes
        for prefix in ("Antrag ", "ANTRAG "):
            if k.startswith(prefix):
                k = k[len(prefix):]
        return k.strip()

    def _map_status(self, raw_status: str) -> str:
        """Map raw status text to normalized form."""
        if not raw_status:
            return ""
        lower = raw_status.lower().strip()
        for key, value in self.status_map.items():
            if key in lower:
                return value
        return raw_status
