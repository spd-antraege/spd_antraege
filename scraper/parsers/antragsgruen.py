"""
Parser for Antragsgrün instances.

Used by: Thüringen (inhalte.spd-thueringen.de).
Antragsgrün REST API may not be enabled. Fallback: HTML scraping of
the consultation/motion listing pages.
"""

from __future__ import annotations

import re
import time

import requests
from bs4 import BeautifulSoup


class AntragsgruenParser:
    """Scrapes Antragsgrün instances via HTML (API rarely enabled by SPD)."""

    def __init__(self, config: dict):
        self.config = config
        self.base_url = config["portal_url"].rstrip("/")
        self.delay = config.get("scrape_delay", 1.0)
        self.status_map = config.get("status_map", {})

    def discover_events(self) -> list[dict]:
        """Discover consultations (Veranstaltungen) from the main page."""
        resp = requests.get(self.base_url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        events = []
        # Antragsgrün lists consultations as links on the main page
        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            text = link.get_text(strip=True)
            # Consultation URLs typically match /{consultation_slug}
            if text and href and not href.startswith("http") and "/" in href:
                slug = href.strip("/").split("/")[0] if href.startswith("/") else href.split("/")[0]
                if slug and slug not in ("admin", "user", "login", "logout", "css", "js", "img"):
                    events.append({
                        "event_id": slug,
                        "label": text,
                        "url": f"{self.base_url}/{slug}",
                    })

        # Also try known consultation paths from config
        for consultation in self.config.get("consultations", []):
            events.append({
                "event_id": consultation["slug"],
                "label": consultation.get("label", consultation["slug"]),
                "url": f"{self.base_url}/{consultation['slug']}",
            })

        # Deduplicate
        seen = set()
        unique = []
        for e in events:
            if e["event_id"] not in seen:
                seen.add(e["event_id"])
                unique.append(e)

        return unique

    def list_motions(self, event: dict) -> list[dict]:
        """List all motions in a consultation."""
        url = event.get("url", f"{self.base_url}/{event['event_id']}")

        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        motions = []
        # Antragsgrün motion links: /{consultation}/{motion_slug}
        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            text = link.get_text(strip=True)

            # Motion links contain the consultation slug and a motion identifier
            if not text or len(text) < 3:
                continue

            # Match motion links (typically /consultation/motion-123 or /consultation/antrag-5)
            full_url = href if href.startswith("http") else f"{self.base_url}{href}"
            if event["event_id"] in href and href.count("/") >= 2:
                # Skip non-motion links
                if any(skip in href for skip in ["admin", "login", "amendment", "proposed-procedure"]):
                    continue

                slug = href.rstrip("/").rsplit("/", 1)[-1]
                motions.append({
                    "kuerzel": text[:80],
                    "titel": text,
                    "source_url": full_url,
                    "veranstaltung": event.get("label", ""),
                    "_slug": slug,
                })

        # Deduplicate by URL
        seen = set()
        unique = []
        for m in motions:
            if m["source_url"] not in seen:
                seen.add(m["source_url"])
                unique.append(m)

        return unique

    def fetch_content(self, motion: dict) -> str:
        """Fetch full motion content from its page."""
        url = motion.get("source_url", "")
        if not url:
            return ""

        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        sections = []

        # Motion title
        title = soup.find("h1")
        if title:
            sections.append(title.get_text(strip=True))
            sections.append("")

        # Initiator/submitter
        initiator = soup.find(class_=re.compile(r"motionDataTable|initiator|motionInitiator"))
        if initiator:
            text = initiator.get_text(strip=True)
            if text:
                sections.append(f"Antragsteller: {text}")
                sections.append("")

        # Motion text sections
        for section in soup.find_all(class_=re.compile(r"motionTextHolder|paragraph|textOrig")):
            text = section.get_text(separator="\n", strip=True)
            if text and len(text) > 10:
                sections.append(text)
                sections.append("")

        if not sections:
            # Fallback: main content area
            main = soup.find("main") or soup.find(class_="content") or soup.find(id="content")
            if main:
                return main.get_text(separator="\n", strip=True)[:5000]

        return "\n".join(sections)[:5000]
