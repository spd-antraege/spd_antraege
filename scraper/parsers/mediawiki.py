"""
Parser for MediaWiki-based Beschlussdatenbanken.

Used by: Schleswig-Holstein (Landes + KV Kiel, Steinburg, Lübeck).
Uses MediaWiki API — no HTML scraping needed.
"""

from __future__ import annotations

import re
import time

import requests


class MediaWikiParser:
    """Scrapes MediaWiki Beschlussdatenbanken via API."""

    def __init__(self, config: dict):
        self.config = config
        self.api_url = config["api_url"]
        self.delay = config.get("scrape_delay", 1.0)
        self.status_map = config.get("status_map", {})
        self.template_map = config.get("template_map", {})

    def discover_events(self) -> list[dict]:
        """Discover categories that represent events/Parteitage."""
        params = {
            "action": "query",
            "list": "allcategories",
            "aclimit": "500",
            "format": "json",
        }
        resp = requests.get(self.api_url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        categories = []
        for cat in data.get("query", {}).get("allcategories", []):
            name = cat.get("*", "")
            if name:
                categories.append({"event_id": name, "label": name})

        return categories

    def list_motions(self, event: dict) -> list[dict]:
        """List all pages in a category."""
        category = event["event_id"]
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": f"Kategorie:{category}" if not category.startswith("Kategorie:") else category,
            "cmlimit": "500",
            "format": "json",
        }
        resp = requests.get(self.api_url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        motions = []
        for member in data.get("query", {}).get("categorymembers", []):
            title = member.get("title", "")
            if title and not title.startswith("Kategorie:"):
                motions.append({
                    "kuerzel": title,
                    "titel": title,
                    "source_url": f"{self.api_url.rsplit('/', 1)[0]}/index.php/{requests.utils.quote(title)}",
                    "veranstaltung": category,
                })

        return motions

    def fetch_content(self, motion: dict) -> str:
        """Fetch page content via API and parse wiki markup."""
        title = motion.get("kuerzel", "")
        params = {
            "action": "query",
            "titles": title,
            "prop": "revisions",
            "rvprop": "content",
            "format": "json",
        }
        resp = requests.get(self.api_url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        pages = data.get("query", {}).get("pages", {})
        for page_id, page_data in pages.items():
            if page_id == "-1":
                return ""
            revisions = page_data.get("revisions", [])
            if revisions:
                wikitext = revisions[0].get("*", "")
                return self._parse_wikitext(wikitext, motion)

        return ""

    def _parse_wikitext(self, wikitext: str, motion: dict) -> str:
        """Extract structured data from wiki markup with {{Beschluss}} template."""
        # Extract template fields
        template_match = re.search(r"\{\{Beschluss\s*\|([^}]+)\}\}", wikitext, re.DOTALL)
        if template_match:
            template_body = template_match.group(1)
            for field_match in re.finditer(r"\|\s*(\w+)\s*=\s*([^|]*?)(?=\||$)", template_body, re.DOTALL):
                field_name = field_match.group(1).strip()
                field_value = field_match.group(2).strip()

                # Map template fields to our schema
                schema_field = self.template_map.get(field_name)
                if schema_field and field_value:
                    motion[schema_field] = field_value

                if field_name == "Status":
                    motion["status"] = self._normalize_status(field_value)
                elif field_name == "Antragsteller":
                    motion["antragsteller"] = field_value

        # Extract body text (everything after the template)
        body = wikitext
        body = re.sub(r"\{\{[^}]+\}\}", "", body)  # remove templates
        body = re.sub(r"\[\[Kategorie:[^\]]+\]\]", "", body)  # remove categories
        body = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", body)  # [[link|text]] → text
        body = re.sub(r"\[\[([^\]]+)\]\]", r"\1", body)  # [[link]] → link
        body = re.sub(r"'{2,3}", "", body)  # remove bold/italic markup
        body = re.sub(r"^=+\s*(.+?)\s*=+$", r"\1", body, flags=re.MULTILINE)  # == heading == → heading

        return body.strip()

    def _normalize_status(self, status: str) -> str:
        key = status.lower().strip()
        return self.status_map.get(key, status)

    def list_all_pages(self, limit: int = 5000) -> list[dict]:
        """List ALL pages (not category-filtered). For bulk export."""
        motions = []
        apcontinue = None

        while True:
            params = {
                "action": "query",
                "list": "allpages",
                "aplimit": "500",
                "apnamespace": "0",
                "format": "json",
            }
            if apcontinue:
                params["apcontinue"] = apcontinue

            resp = requests.get(self.api_url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            for page in data.get("query", {}).get("allpages", []):
                title = page.get("title", "")
                motions.append({
                    "kuerzel": title,
                    "titel": title,
                    "source_url": f"{self.api_url.rsplit('/', 1)[0]}/index.php/{requests.utils.quote(title)}",
                })

            if len(motions) >= limit:
                break

            cont = data.get("continue", {})
            apcontinue = cont.get("apcontinue")
            if not apcontinue:
                break

            time.sleep(self.delay)

        return motions
