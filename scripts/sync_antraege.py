#!/usr/bin/env python3
"""
Sync SPD Berlin Antraege from parteitag.spd.berlin to local corpus.

Usage examples:
    python scripts/sync_antraege.py --discover
    python scripts/sync_antraege.py --discover --deep-check
    python scripts/sync_antraege.py --scrape
    python scripts/sync_antraege.py --scrape --events "II/2025,I/2026"
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml
from bs4 import BeautifulSoup

# --- Configuration ---

BASE_URL = "https://parteitag.spd.berlin"
LISTING_URL = f"{BASE_URL}/antragsverfolgung/"

MD_DIR = Path(
    os.environ.get("ANTRAEGE_MD_DIR", "/home/andx/spd_antraege/corpus/berlin")
)
TOOLS_DATA_DIR = Path(
    os.environ.get("TOOLS_DATA_DIR", "/home/andx/spd_antraege/tools/data")
)
# Scraping
SCRAPE_DELAY = float(os.environ.get("SYNC_SCRAPE_DELAY", "0.5"))

# Chunking policy
CHUNK_SINGLE_MAX_TOKENS = int(os.environ.get("CHUNK_SINGLE_MAX_TOKENS", "2500"))
CHUNK_SECTION_SPLIT_MAX_TOKENS = int(
    os.environ.get("CHUNK_SECTION_SPLIT_MAX_TOKENS", "8000")
)
CHUNK_SOFT_MAX_TOKENS = int(os.environ.get("CHUNK_SOFT_MAX_TOKENS", "1600"))
CHUNK_OVERLAP_TOKENS = int(os.environ.get("CHUNK_OVERLAP_TOKENS", "100"))

# Event IDs from the website dropdown
EVENTS = {
    "I/2026": 284714,
    "II/2025": 262002,
    "I/2025": 238605,
    "II/2024": 237005,
    "I/2024": 210438,
    "II/2023": 201302,
    "I/2023": 192479,
    "I/2022": 140855,
    "II/2022": 176643,
    "I/2021": 122716,
    "II/2021": 135518,
    "I/2020": 107459,
    "I/2019": 71101,
    "II/2019": 87536,
    "II/2018": 51924,
    "I/2018": 50632,
    "IV/2017": 40699,
    "II/2017": 46082,
    "I/2017": 40700,
    "III/2016": 38120,
    "I/2016": 22172,
    "II/2015": 20604,
    "I/2015": 10067,
    "II/2014": 207,
    "I/2014": 210,
    "II/2013": 27203,
    "I/2013": 3115,
}

# Default: only sync recent events
DEFAULT_EVENTS = ["I/2026", "II/2025", "I/2025"]

# Status mapping from HTML to our frontmatter values
STATUS_MAP = {
    "annahme": "Annahme",
    "annahme mit änderungen": "Annahme mit Änderungen",
    "ablehnung": "Ablehnung",
    "überweisung": "Überweisung",
    "erledigt": "Erledigt",
    "nicht abgestimmt": "Nicht abgestimmt",
    "offen": "offen",
    "zurückgezogen": "Zurückgezogen",
}



# --- Utility ---


def utc_now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slugify(text):
    """Convert text to URL-safe slug."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    text = re.sub(r"[-\s]+", "-", text).strip("-")
    return text[:120]


def estimate_tokens(text):
    """
    Cheap deterministic token estimate for routing chunk strategy.
    ~4 chars/token heuristic.
    """
    return max(1, int(len(text) / 4))


def normalize_text(text):
    text = text.replace("\r\n", "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def compute_content_hash(content):
    normalized = normalize_text(content)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


def parse_kuerzel(raw):
    """Parse 'Antrag 405/II/2025' into components."""
    raw = (raw or "").strip()
    m = re.match(r"^Antrag\s+([^/]+)/((?:I|II|III|IV))/(\d{4})$", raw)
    if not m:
        return None
    number = m.group(1).strip()
    if not number:
        return None
    return {
        "number": number,
        "session": m.group(2),
        "year": m.group(3),
        "kuerzel": f"Antrag {number}/{m.group(2)}/{m.group(3)}",
    }


def kuerzel_to_filename(kuerzel, slug):
    """Convert kuerzel to filename matching existing convention."""
    parsed = parse_kuerzel(kuerzel)
    if not parsed:
        return None
    num, session, year = parsed["number"], parsed["session"], parsed["year"]
    return f"Antrag {num}-{session}-{year}--{slug}.md"


def source_doc_id_from_kuerzel(kuerzel):
    parsed = parse_kuerzel(kuerzel)
    if parsed:
        # Preserve semantic distinctions like "15.1" vs "151" to avoid collisions.
        raw_number = unicodedata.normalize("NFKD", parsed["number"])
        raw_number = raw_number.encode("ascii", "ignore").decode("ascii").lower()
        raw_number = raw_number.replace(".", "d")
        number = re.sub(r"[^a-z0-9]+", "", raw_number)
        if not number:
            number = "unknown"
        return f"antrag-{number}{parsed['session'].lower()}{parsed['year']}"

    raw = kuerzel.replace("Antrag", "").strip()
    slug = slugify(raw)
    return f"antrag-{slug}" if slug else "antrag-unknown"


def parse_markdown_frontmatter(path):
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}, text.strip()

    lines = text.splitlines(keepends=True)
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        return {}, text.strip()

    fm_text = "".join(lines[1:end_idx])
    body = "".join(lines[end_idx + 1 :]).lstrip("\n")

    try:
        fm = yaml.safe_load(fm_text) or {}
    except Exception:
        fm = {}

    return fm, body.strip()


def write_markdown_file(path, frontmatter, content):
    fm_str = yaml.dump(
        frontmatter,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=200,
    )
    path.write_text(
        f"---\n{fm_str}---\n\n{normalize_text(content)}\n", encoding="utf-8"
    )


def get_existing_kuerzels():
    """Scan corpus/berlin and return map of existing Antrag metadata."""
    existing = {}
    for f in MD_DIR.rglob("*.md"):
        try:
            fm, _body = parse_markdown_frontmatter(f)
            if fm and "kuerzel" in fm:
                existing[fm["kuerzel"]] = {
                    "path": f,
                    "status": fm.get("status_in_tabelle", ""),
                    "content_hash": fm.get("content_hash", ""),
                    "source_url": fm.get("source_url", ""),
                }
        except Exception:
            continue
    return existing


def parse_frontmatter_metadata(file_path):
    fm, body = parse_markdown_frontmatter(file_path)
    if not fm.get("kuerzel"):
        raise ValueError(f"Missing kuerzel in frontmatter: {file_path}")

    parsed = parse_kuerzel(fm["kuerzel"])
    year = fm.get("year") or (parsed["year"] if parsed else "")
    session = fm.get("session") or (parsed["session"] if parsed else "")

    return {
        "kuerzel": fm.get("kuerzel", ""),
        "titel": fm.get("titel", file_path.stem),
        "status_in_tabelle": fm.get("status_in_tabelle", ""),
        "antragsteller": fm.get("antragsteller", ""),
        "veranstaltung": fm.get("veranstaltung", ""),
        "tagesordnungspunkt": fm.get("tagesordnungspunkt", ""),
        "source_url": fm.get("source_url", ""),
        "year": str(year),
        "session": str(session),
        "content_hash": fm.get("content_hash", compute_content_hash(body)),
        "body": normalize_text(body),
        "frontmatter": fm,
    }


# --- Listing / Scraping ---


def _parse_table_rows(soup):
    """Parse Antrag rows from a listing page's HTML table."""
    table = soup.find("table", id="cvtx-page-antragsverfolgung-antraege")
    if not table:
        return []

    rows = table.find("tbody").find_all("tr") if table.find("tbody") else []
    results = []

    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 7:
            continue

        link_tag = cells[0].find("a")
        if not link_tag:
            continue
        kuerzel_raw = link_tag.get_text(strip=True)
        source_url = link_tag.get("href", "")
        if not source_url.startswith("http"):
            source_url = BASE_URL + source_url

        slug_match = re.search(r"/cvtx_antrag/([^/]+)/?$", source_url)
        slug = slug_match.group(1) if slug_match else slugify(kuerzel_raw)

        status = cells[1].get_text(strip=True)
        antragsteller = cells[2].get_text(strip=True)
        ueberwiesen_an = cells[3].get_text(strip=True)
        tagesordnungspunkt = cells[4].get_text(strip=True)
        titel = cells[5].get_text(strip=True)
        veranstaltung = cells[6].get_text(strip=True)

        pdf_url = ""
        if len(cells) > 7:
            pdf_link = cells[7].find("a")
            if pdf_link:
                pdf_url = pdf_link.get("href", "")
                if pdf_url and not pdf_url.startswith("http"):
                    pdf_url = BASE_URL + pdf_url

        status_lower = status.lower().strip()
        status_normalized = STATUS_MAP.get(status_lower, status)

        parsed = parse_kuerzel(kuerzel_raw)
        if not parsed:
            continue

        results.append(
            {
                "kuerzel": parsed["kuerzel"],
                "number": parsed["number"],
                "session": parsed["session"],
                "year": parsed["year"],
                "titel": titel,
                "status": status_normalized,
                "antragsteller": antragsteller,
                "ueberwiesen_an": ueberwiesen_an,
                "tagesordnungspunkt": tagesordnungspunkt,
                "veranstaltung": veranstaltung,
                "source_url": source_url,
                "pdf_url": pdf_url,
                "slug": slug,
            }
        )

    return results


def _get_max_page(soup):
    max_page = 1
    for link in soup.find_all("a", class_="page-numbers"):
        m = re.search(r"/page/(\d+)", link.get("href", ""))
        if m:
            max_page = max(max_page, int(m.group(1)))
        text = link.get_text(strip=True)
        if text.isdigit():
            max_page = max(max_page, int(text))
    return max_page


def fetch_listing(event_key):
    """Fetch all pages of the listing for an event and parse the HTML tables."""
    event_id = EVENTS.get(event_key)
    if event_id is None:
        print(f"  Unknown event: {event_key}")
        return []

    base_params = f"?cvtx_virtualpage=antragsverfolgung&cvtx_antrag_event={event_id}"
    url = f"{LISTING_URL}{base_params}"
    print(f"  Fetching listing for {event_key} (ID {event_id})...")

    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    max_page = _get_max_page(soup)
    results = _parse_table_rows(soup)
    print(f"    Page 1/{max_page}: {len(results)} rows", end="", flush=True)

    for page in range(2, max_page + 1):
        time.sleep(SCRAPE_DELAY)
        page_url = f"{LISTING_URL}page/{page}{base_params}"
        resp = requests.get(page_url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        page_rows = _parse_table_rows(soup)
        results.extend(page_rows)
        print(f", p{page}: {len(page_rows)}", end="", flush=True)

    print(f"\n  Found {len(results)} Antraege for {event_key}")
    return results


def _html_to_markdown(element):
    lines = []
    for elem in element.descendants:
        if elem.name in ("h1", "h2", "h3"):
            text = elem.get_text(strip=True)
            if text:
                level = int(elem.name[1])
                lines.append("")
                lines.append(f"{'#' * level} {text}")
                lines.append("")
        elif elem.name == "p":
            text = elem.get_text(strip=True)
            if text:
                lines.append(text)
                lines.append("")
        elif elem.name == "li":
            text = elem.get_text(strip=True)
            if text:
                lines.append(f"- {text}")
        elif elem.name == "br":
            lines.append("")

    content = "\n".join(lines)
    return normalize_text(content)


def fetch_antrag_content(source_url):
    """Fetch individual Antrag page and extract structured content."""
    resp = requests.get(source_url, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    entry = soup.find("div", class_="entry")
    if not entry:
        return ""

    sections = []

    original = entry.find("div", class_="cvtx-state-original")
    if original:
        steller = original.find("span", class_="cvtx_field_cvtx_antrag_steller")
        if steller:
            sections.append(f"**AntragstellerInnen:** {steller.get_text(strip=True)}")
            sections.append("")

        recipient = original.find("div", class_="cvtx_field_cvtx_antrag_recipient")
        if recipient:
            text = recipient.get_text(strip=True)
            if text:
                sections.append(f"**Adressat:** {text}")
                sections.append("")

        antragstext_parts = []
        for p in original.find_all("p"):
            text = p.get_text(strip=True)
            if text:
                antragstext_parts.append(text)
        for li in original.find_all("li"):
            if li.find_parent("div", class_="cvtx-state-menu"):
                continue
            text = li.get_text(strip=True)
            if text:
                antragstext_parts.append(f"- {text}")

        if antragstext_parts:
            sections.append("## Antragstext")
            sections.append("")
            sections.extend(antragstext_parts)
            sections.append("")

        ak = original.find(
            "div", class_="cvtx_field_cvtx_antrag_ak_recommendation_select"
        )
        if not ak:
            ak_wrapper = entry.find(
                "div", class_="cvtx_field_cvtx_antrag_ak_recommendation_select-wrapper"
            )
            if ak_wrapper:
                ak = ak_wrapper.find(
                    "div", class_="cvtx_field_cvtx_antrag_ak_recommendation_select"
                )
        if ak:
            sections.append(
                f"**Empfehlung der Antragskommission:** {ak.get_text(strip=True)}"
            )
            sections.append("")

        ak_grund = original.find("div", class_="cvtx_field_cvtx_antrag_ak_grund")
        if ak_grund:
            text = ak_grund.get_text(strip=True)
            if text:
                sections.append(f"**Begruendung AK:** {text}")
                sections.append("")

    if not sections:
        menu = entry.find("div", class_="cvtx-state-menu")
        if menu:
            menu.decompose()
        all_wrapper = entry.find("div", class_="cvtx-state-all")
        if all_wrapper:
            all_wrapper.decompose()
        return _html_to_markdown(entry)

    decision = entry.find("div", class_="cvtx-state-decision")
    if decision:
        decision_text = []
        for p in decision.find_all("p"):
            text = p.get_text(strip=True)
            if text:
                decision_text.append(text)
        if decision_text:
            sections.append("## Beschluss")
            sections.append("")
            sections.extend(decision_text)
            sections.append("")

    return normalize_text("\n".join(sections).strip())


def build_markdown(antrag, content):
    """Build a complete markdown file with YAML frontmatter."""
    normalized = normalize_text(content)
    content_hash = compute_content_hash(normalized)

    frontmatter = {
        "kuerzel": antrag["kuerzel"],
        "titel": antrag["titel"],
        "status_in_tabelle": antrag["status"],
        "antragsteller": antrag["antragsteller"],
        "ueberwiesen_an": antrag["ueberwiesen_an"],
        "tagesordnungspunkt": antrag["tagesordnungspunkt"],
        "veranstaltung": antrag["veranstaltung"],
        "verantwortlich": "SPD Berlin",
        "herkunft": "parteitag.spd.berlin",
        "source_url": antrag["source_url"],
        "pdf_url": antrag["pdf_url"],
        "publication_date": "",
        "tags": [],
        "content_hash": content_hash,
    }

    fm_str = yaml.dump(
        frontmatter,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=200,
    )

    return f"---\n{fm_str}---\n\n{normalized}\n"


# --- Chunking ---


def split_markdown_sections(content):
    lines = content.splitlines()
    sections = []

    current_title = "Dokument"
    current_lines = []

    for line in lines:
        if line.startswith("## "):
            if current_lines:
                text = normalize_text("\n".join(current_lines))
                if text:
                    sections.append({"section_title": current_title, "text": text})
            current_title = line[3:].strip() or "Abschnitt"
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        text = normalize_text("\n".join(current_lines))
        if text:
            sections.append({"section_title": current_title, "text": text})

    if not sections:
        sections.append({"section_title": "Dokument", "text": normalize_text(content)})

    return sections


def tail_words(text, token_count):
    words = text.split()
    if token_count <= 0 or len(words) <= token_count:
        return text.strip()
    return " ".join(words[-token_count:]).strip()


def split_section_with_soft_cap(text, section_title, soft_max_tokens, overlap_tokens):
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    if not paragraphs:
        return []

    chunks = []
    buffer_parts = []

    def flush_buffer():
        if not buffer_parts:
            return
        chunk_text = normalize_text("\n\n".join(buffer_parts))
        if chunk_text:
            chunks.append({"section_title": section_title, "text": chunk_text})

    for para in paragraphs:
        candidate_parts = buffer_parts + [para]
        candidate_text = normalize_text("\n\n".join(candidate_parts))

        if not buffer_parts or estimate_tokens(candidate_text) <= soft_max_tokens:
            buffer_parts = candidate_parts
            continue

        flush_buffer()
        overlap = tail_words(chunks[-1]["text"], overlap_tokens)
        if overlap:
            buffer_parts = [overlap, para]
        else:
            buffer_parts = [para]

        if estimate_tokens(normalize_text("\n\n".join(buffer_parts))) > soft_max_tokens:
            words = para.split()
            window = max(200, soft_max_tokens)
            step = max(50, window - overlap_tokens)
            for start in range(0, len(words), step):
                piece = " ".join(words[start : start + window]).strip()
                if piece:
                    chunks.append({"section_title": section_title, "text": piece})
            buffer_parts = []

    flush_buffer()
    return chunks


def chunk_antrag_content(content):
    text = normalize_text(content)
    total_tokens = estimate_tokens(text)

    if total_tokens <= CHUNK_SINGLE_MAX_TOKENS:
        return [
            {
                "chunk_id": "chunk-000",
                "section_title": "Dokument",
                "text": text,
                "estimated_tokens": total_tokens,
            }
        ]

    sections = split_markdown_sections(text)

    chunk_bodies = []
    if total_tokens <= CHUNK_SECTION_SPLIT_MAX_TOKENS:
        chunk_bodies = sections
    else:
        for section in sections:
            st = section["text"]
            if estimate_tokens(st) <= CHUNK_SOFT_MAX_TOKENS:
                chunk_bodies.append(section)
            else:
                chunk_bodies.extend(
                    split_section_with_soft_cap(
                        st,
                        section["section_title"],
                        CHUNK_SOFT_MAX_TOKENS,
                        CHUNK_OVERLAP_TOKENS,
                    )
                )

    chunks = []
    for idx, section in enumerate(chunk_bodies):
        chunk_text = normalize_text(section["text"])
        if not chunk_text:
            continue
        chunks.append(
            {
                "chunk_id": f"chunk-{idx:03d}",
                "section_title": section["section_title"],
                "text": chunk_text,
                "estimated_tokens": estimate_tokens(chunk_text),
            }
        )

    if not chunks:
        chunks = [
            {
                "chunk_id": "chunk-000",
                "section_title": "Dokument",
                "text": text,
                "estimated_tokens": total_tokens,
            }
        ]

    return chunks


# --- Main Commands ---


def cmd_discover(event_keys, deep_check=False):
    """Discover new, status-updated, and optionally content-updated Antraege."""
    existing = get_existing_kuerzels()
    print(f"Existing corpus: {len(existing)} Antraege\n")

    all_new = []
    all_status_updated = []
    all_current = []

    for event_key in event_keys:
        remote = fetch_listing(event_key)
        for antrag in remote:
            if antrag["kuerzel"] not in existing:
                all_new.append(antrag)
            elif existing[antrag["kuerzel"]]["status"] != antrag["status"]:
                all_status_updated.append(antrag)
            else:
                all_current.append(antrag)

    all_content_updated = []

    if deep_check and all_current:
        print(
            f"\nDeep-checking {len(all_current)} unchanged rows for silent content edits..."
        )
        for i, antrag in enumerate(all_current):
            print(
                f"\r  [{i + 1}/{len(all_current)}] {antrag['kuerzel']:30}",
                end="",
                flush=True,
            )
            try:
                content = fetch_antrag_content(antrag["source_url"])
                remote_hash = compute_content_hash(content)
                local_hash = existing.get(antrag["kuerzel"], {}).get("content_hash", "")
                if not local_hash or local_hash != remote_hash:
                    all_content_updated.append(antrag)
            except Exception as exc:
                print(f" ERROR: {exc}")
            time.sleep(SCRAPE_DELAY)
        print()

    print(f"\n{'=' * 60}")
    print(f"New:             {len(all_new)}")
    print(f"Status updated:  {len(all_status_updated)}")
    print(f"Content updated: {len(all_content_updated)}")
    print(f"Current:         {len(all_current) - len(all_content_updated)}")
    print(f"{'=' * 60}")

    return all_new, all_status_updated, all_content_updated


def cmd_scrape(event_keys, deep_check=False):
    """Discover and scrape new/updated Antraege."""
    all_new, all_status_updated, all_content_updated = cmd_discover(
        event_keys, deep_check=deep_check
    )

    to_scrape_map = {}
    for antrag in all_new + all_status_updated + all_content_updated:
        to_scrape_map[antrag["kuerzel"]] = antrag
    to_scrape = list(to_scrape_map.values())

    if not to_scrape:
        print("\nNothing to scrape.")
        return []

    existing = get_existing_kuerzels()

    print(f"\nScraping {len(to_scrape)} Antraege...")
    scraped_files = []

    for i, antrag in enumerate(to_scrape):
        print(
            f"\r  [{i + 1}/{len(to_scrape)}] {antrag['kuerzel']:30}", end="", flush=True
        )

        try:
            content = fetch_antrag_content(antrag["source_url"])
            if not content:
                print(" (empty content, skipping)")
                continue

            md = build_markdown(antrag, content)

            year_dir = MD_DIR / antrag["year"]
            year_dir.mkdir(parents=True, exist_ok=True)

            filename = kuerzel_to_filename(antrag["kuerzel"], antrag["slug"])
            if not filename:
                continue

            filepath = year_dir / filename

            if antrag["kuerzel"] in existing:
                old_path = existing[antrag["kuerzel"]]["path"]
                if old_path != filepath:
                    filepath = old_path

            filepath.write_text(md, encoding="utf-8")
            scraped_files.append(filepath)

        except Exception as exc:
            print(f" ERROR: {exc}")

        time.sleep(SCRAPE_DELAY)

    print(f"\n\nScraped {len(scraped_files)} files to {MD_DIR}")
    return scraped_files


def main():
    parser = argparse.ArgumentParser(
        description="Sync SPD Berlin Antraege from website to local corpus"
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--discover",
        action="store_true",
        help="Discover new/updated Antraege (dry run)",
    )
    group.add_argument(
        "--scrape", action="store_true", help="Discover and scrape to local corpus"
    )

    parser.add_argument(
        "--events",
        type=str,
        default=None,
        help='Comma-separated event keys (e.g. "II/2025,I/2026"). Default: latest 3',
    )
    parser.add_argument(
        "--deep-check",
        action="store_true",
        help="Fetch unchanged rows and compare content_hash for silent edits",
    )

    args = parser.parse_args()

    if args.events:
        event_keys = [e.strip() for e in args.events.split(",") if e.strip()]
        for event_key in event_keys:
            if event_key not in EVENTS:
                print(f"Unknown event: {event_key}")
                print(f"Available: {', '.join(sorted(EVENTS.keys()))}")
                sys.exit(1)
    else:
        event_keys = DEFAULT_EVENTS

    if args.discover:
        print(f"Events: {', '.join(event_keys)}\n")
        cmd_discover(event_keys, deep_check=args.deep_check)
    elif args.scrape:
        print(f"Events: {', '.join(event_keys)}\n")
        cmd_scrape(event_keys, deep_check=args.deep_check)


if __name__ == "__main__":
    main()
