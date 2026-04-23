"""
Parser for cvtx WordPress plugin portals.

Used by: Berlin, Brandenburg, Hamburg, Bayern, RLP, Bezirk Hannover.
Reuses logic from scripts/sync_antraege.py and scripts/audit_cvtx.py.
"""

from __future__ import annotations

import re
import time

import requests
from bs4 import BeautifulSoup


class CvtxParser:
    """Scrapes cvtx-based Antragsportale."""

    def __init__(self, config: dict):
        self.config = config
        self.base_url = config["portal_url"].rstrip("/")
        self.listing_url = f"{self.base_url}/antragsverfolgung/"
        self.delay = config.get("scrape_delay", 1.0)
        self.status_map = config.get("status_map", {})

    def discover_events(self) -> list[dict]:
        """Discover all Veranstaltungen from the dropdown."""
        resp = requests.get(self.listing_url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        events = []
        select = soup.find("select", {"name": "cvtx_antrag_event"})
        if select:
            for option in select.find_all("option"):
                value = option.get("value", "").strip()
                label = option.get_text(strip=True)
                if value and label and value != "0" and value != "-1":
                    events.append({"event_id": value, "label": label})

        return events

    def list_motions(self, event: dict) -> list[dict]:
        """List all motions for an event, handling pagination."""
        event_id = event["event_id"]
        params = f"?cvtx_virtualpage=antragsverfolgung&cvtx_antrag_event={event_id}"
        url = f"{self.listing_url}{params}"

        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        max_page = self._get_max_page(soup)
        results = self._parse_table(soup)

        for page in range(2, max_page + 1):
            time.sleep(self.delay)
            page_url = f"{self.listing_url}page/{page}/{params}"
            resp = requests.get(page_url, timeout=30)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                results.extend(self._parse_table(soup))

        # Tag with event info
        for r in results:
            if not r.get("veranstaltung"):
                r["veranstaltung"] = event.get("label", "")

        return results

    def fetch_content(self, motion: dict) -> str:
        """Fetch full content from individual Antrag page."""
        url = motion.get("source_url", "")
        if not url:
            return ""

        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        entry = soup.find("div", class_="entry") or soup.find("div", class_="entry-content")
        if not entry:
            return ""

        sections = []

        original = entry.find("div", class_="cvtx-state-original")
        if original:
            steller = original.find("span", class_="cvtx_field_cvtx_antrag_steller")
            if steller:
                sections.append(f"AntragstellerInnen: {steller.get_text(strip=True)}")
                sections.append("")

            recipient = original.find("div", class_="cvtx_field_cvtx_antrag_recipient")
            if recipient:
                text = recipient.get_text(strip=True)
                if text:
                    sections.append(f"Adressat: {text}")
                    sections.append("")

            sections.append("Antragstext")
            sections.append("")
            for p in original.find_all("p"):
                text = p.get_text(strip=True)
                if text:
                    sections.append(text)
            for li in original.find_all("li"):
                if li.find_parent("div", class_="cvtx-state-menu"):
                    continue
                text = li.get_text(strip=True)
                if text:
                    sections.append(f"- {text}")

            ak = original.find("div", class_="cvtx_field_cvtx_antrag_ak_recommendation_select")
            if ak:
                sections.append("")
                sections.append(f"Empfehlung der Antragskommission: {ak.get_text(strip=True)}")

            ak_grund = original.find("div", class_="cvtx_field_cvtx_antrag_ak_grund")
            if ak_grund:
                text = ak_grund.get_text(strip=True)
                if text:
                    sections.append(f"Begruendung AK: {text}")

        if not sections:
            # Fallback: extract all text
            for menu in entry.find_all("div", class_="cvtx-state-menu"):
                menu.decompose()
            return entry.get_text(separator="\n", strip=True)[:5000]

        # Decision section
        decision = entry.find("div", class_="cvtx-state-decision")
        if decision:
            sections.append("")
            sections.append("Beschluss")
            sections.append("")
            for p in decision.find_all("p"):
                text = p.get_text(strip=True)
                if text:
                    sections.append(text)

        return "\n".join(sections)

    def _parse_table(self, soup) -> list[dict]:
        """Parse the cvtx antragsverfolgung table."""
        table = soup.find("table", id="cvtx-page-antragsverfolgung-antraege")
        if not table:
            table = soup.find("table", class_=re.compile(r"cvtx"))
        if not table:
            return []

        tbody = table.find("tbody")
        if not tbody:
            return []

        # Detect headers
        headers = []
        thead = table.find("thead")
        if thead:
            for th in thead.find_all("th"):
                headers.append(th.get_text(strip=True).lower())

        rows = []
        for tr in tbody.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) < 2:
                continue

            link = cells[0].find("a")
            if not link:
                continue

            kuerzel = link.get_text(strip=True)
            href = link.get("href", "")
            if href and not href.startswith("http"):
                href = self.base_url + href

            row = {"kuerzel": kuerzel, "source_url": href}

            # Map cells by header or position
            if headers:
                for i, cell in enumerate(cells[1:], 1):
                    if i >= len(headers):
                        break
                    h = headers[i]
                    text = cell.get_text(strip=True)
                    if "status" in h or "votum" in h or "empfehlung" in h:
                        row["status"] = self._normalize_status(text)
                    elif "steller" in h or "antragsteller" in h:
                        row["antragsteller"] = text
                    elif "titel" in h or "betreff" in h or "thema" in h:
                        row["titel"] = text
                    elif "veranstaltung" in h or "parteitag" in h or "event" in h:
                        row["veranstaltung"] = text
                    elif "tagesordnung" in h or "top" in h:
                        row["tagesordnungspunkt"] = text
                    elif "überweis" in h:
                        row["ueberwiesen_an"] = text
            else:
                # Berlin-style positional fallback
                if len(cells) >= 6:
                    row["status"] = self._normalize_status(cells[1].get_text(strip=True))
                    row["antragsteller"] = cells[2].get_text(strip=True)
                    row["tagesordnungspunkt"] = cells[4].get_text(strip=True) if len(cells) > 4 else ""
                    row["titel"] = cells[5].get_text(strip=True) if len(cells) > 5 else ""
                    row["veranstaltung"] = cells[6].get_text(strip=True) if len(cells) > 6 else ""

            rows.append(row)

        return rows

    def _normalize_status(self, status: str) -> str:
        """Normalize status to Berlin vocabulary."""
        key = status.lower().strip()
        return self.status_map.get(key, status)

    def _get_max_page(self, soup) -> int:
        max_page = 1
        for link in soup.find_all("a", class_="page-numbers"):
            m = re.search(r"/page/(\d+)", link.get("href", ""))
            if m:
                max_page = max(max_page, int(m.group(1)))
            text = link.get_text(strip=True)
            if text.isdigit():
                max_page = max(max_page, int(text))
        return max_page
