#!/usr/bin/env python3
"""
Dry-run audit of cvtx-based SPD Antragsportale.

Discovers all Veranstaltungen and Anträge on a cvtx portal, fetches
a small sample, parses them, and scores schema compatibility with Berlin.
Does NOT write to the corpus. Read-only.

Usage:
    python scripts/audit_cvtx.py --url https://www.parteitag-bayernspd.de --output data/audit/bayern/
    python scripts/audit_cvtx.py --url https://www.parteitag-spd-brandenburg.de --output data/audit/brandenburg/
    python scripts/audit_cvtx.py --url https://antraege.spd-sachsen.de --output data/audit/sachsen/
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SCRAPE_DELAY = 1.0  # polite crawling
SAMPLE_COUNT = 5  # Anträge to fetch full content for

# Berlin schema fields — what we score compatibility against
BERLIN_FIELDS = {
    "kuerzel": {"weight": 3, "required": True},
    "titel": {"weight": 2, "required": True},
    "status": {"weight": 3, "required": True},
    "antragsteller": {"weight": 2, "required": True},
    "tagesordnungspunkt": {"weight": 1, "required": False},
    "veranstaltung": {"weight": 2, "required": True},
    "source_url": {"weight": 2, "required": True},
    "text_content": {"weight": 3, "required": True},
}

# Berlin status vocabulary
BERLIN_STATUSES = {
    "annahme", "annahme mit änderungen", "ablehnung",
    "überweisung", "erledigt", "nicht abgestimmt", "offen", "zurückgezogen",
}


def discover_events(base_url: str) -> list[dict]:
    """Discover all Veranstaltungen (events/congresses) from the listing page."""
    listing_url = f"{base_url.rstrip('/')}/antragsverfolgung/"
    print(f"Discovering events at {listing_url}...")

    resp = requests.get(listing_url, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    events = []

    # cvtx uses a <select> dropdown for events
    select = soup.find("select", {"name": "cvtx_antrag_event"})
    if select:
        for option in select.find_all("option"):
            value = option.get("value", "").strip()
            label = option.get_text(strip=True)
            if value and label and value != "0":
                events.append({
                    "event_id": value,
                    "label": label,
                })

    # Also check for links/tabs if no dropdown
    if not events:
        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            if "cvtx_antrag_event=" in href:
                m = re.search(r"cvtx_antrag_event=(\d+)", href)
                if m:
                    events.append({
                        "event_id": m.group(1),
                        "label": link.get_text(strip=True),
                    })

    # Deduplicate
    seen = set()
    unique = []
    for e in events:
        if e["event_id"] not in seen:
            seen.add(e["event_id"])
            unique.append(e)

    print(f"  Found {len(unique)} events")
    return unique


def fetch_event_listing(base_url: str, event_id: str) -> list[dict]:
    """Fetch all Anträge for a single event. Returns list of antrag metadata dicts."""
    listing_url = f"{base_url.rstrip('/')}/antragsverfolgung/"
    params = f"?cvtx_virtualpage=antragsverfolgung&cvtx_antrag_event={event_id}"
    url = f"{listing_url}{params}"

    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Find max pages
    max_page = 1
    for link in soup.find_all("a", class_="page-numbers"):
        m = re.search(r"/page/(\d+)", link.get("href", ""))
        if m:
            max_page = max(max_page, int(m.group(1)))
        text = link.get_text(strip=True)
        if text.isdigit():
            max_page = max(max_page, int(text))

    all_rows = _parse_table(soup, base_url)

    for page in range(2, max_page + 1):
        time.sleep(SCRAPE_DELAY)
        page_url = f"{listing_url}page/{page}/{params}"
        resp = requests.get(page_url, timeout=30)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            all_rows.extend(_parse_table(soup, base_url))

    return all_rows


def _parse_table(soup, base_url: str) -> list[dict]:
    """Parse the cvtx antragsverfolgung table. Adapts to varying column counts."""
    table = soup.find("table", id="cvtx-page-antragsverfolgung-antraege")
    if not table:
        # Try any table with cvtx in class/id
        table = soup.find("table", class_=re.compile(r"cvtx"))
    if not table:
        return []

    tbody = table.find("tbody")
    if not tbody:
        return []

    # Detect header columns
    header_row = table.find("thead")
    headers = []
    if header_row:
        for th in header_row.find_all("th"):
            headers.append(th.get_text(strip=True).lower())

    rows = []
    for tr in tbody.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 2:
            continue

        # First cell always has the Antrag link
        link = cells[0].find("a")
        if not link:
            continue

        kuerzel = link.get_text(strip=True)
        href = link.get("href", "")
        if href and not href.startswith("http"):
            href = base_url.rstrip("/") + href

        # Build row dict from cells
        row = {
            "kuerzel": kuerzel,
            "source_url": href,
        }

        # Map remaining cells based on header or position
        # Berlin order: kuerzel, status, antragsteller, ueberwiesen_an, TOP, titel, veranstaltung, pdf
        # Other LVs may differ, so we try both header-based and position-based
        if headers:
            for i, cell in enumerate(cells[1:], 1):
                if i < len(headers):
                    h = headers[i]
                    text = cell.get_text(strip=True)
                    if "status" in h or "votum" in h or "empfehlung" in h:
                        row["status"] = text
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
            # Fallback: Berlin-style positional mapping
            if len(cells) >= 6:
                row["status"] = cells[1].get_text(strip=True)
                row["antragsteller"] = cells[2].get_text(strip=True)
                row["tagesordnungspunkt"] = cells[4].get_text(strip=True) if len(cells) > 4 else ""
                row["titel"] = cells[5].get_text(strip=True) if len(cells) > 5 else ""
                row["veranstaltung"] = cells[6].get_text(strip=True) if len(cells) > 6 else ""
            elif len(cells) >= 3:
                row["status"] = cells[1].get_text(strip=True)
                row["titel"] = cells[2].get_text(strip=True) if len(cells) > 2 else ""

        rows.append(row)

    return rows


def fetch_antrag_content(url: str) -> str:
    """Fetch full content from individual Antrag page. Returns markdown text."""
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    entry = soup.find("div", class_="entry")
    if not entry:
        # Try entry-content
        entry = soup.find("div", class_="entry-content")
    if not entry:
        return ""

    sections = []

    original = entry.find("div", class_="cvtx-state-original")
    if original:
        steller = original.find("span", class_="cvtx_field_cvtx_antrag_steller")
        if steller:
            sections.append(f"AntragstellerInnen: {steller.get_text(strip=True)}")

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

    if not sections:
        # Fallback: get all text from entry
        for menu in entry.find_all("div", class_="cvtx-state-menu"):
            menu.decompose()
        text = entry.get_text(separator="\n", strip=True)
        return text[:5000]

    return "\n".join(sections)[:5000]


def score_schema_compatibility(antraege: list[dict], samples: list[dict]) -> dict:
    """Score how well this LV's data maps to Berlin schema."""
    scores = {}
    total_weight = 0
    total_score = 0

    for field, spec in BERLIN_FIELDS.items():
        weight = spec["weight"]
        total_weight += weight

        if field == "text_content":
            # Score based on samples
            if samples:
                has_content = sum(1 for s in samples if len(s.get("content", "")) > 100)
                field_score = has_content / len(samples)
            else:
                field_score = 0.0
        else:
            # Score based on listing data
            if antraege:
                has_field = sum(1 for a in antraege if a.get(field) and len(str(a[field])) > 0)
                field_score = has_field / len(antraege)
            else:
                field_score = 0.0

        scores[field] = {
            "coverage": round(field_score, 3),
            "weight": weight,
            "weighted_score": round(field_score * weight, 3),
        }
        total_score += field_score * weight

    overall = total_score / total_weight if total_weight > 0 else 0.0

    # Status vocabulary compatibility
    status_values = set()
    for a in antraege:
        s = (a.get("status") or "").lower().strip()
        if s:
            status_values.add(s)

    known = status_values & BERLIN_STATUSES
    unknown = status_values - BERLIN_STATUSES

    return {
        "overall_compatibility": round(overall, 3),
        "fields": scores,
        "status_vocabulary": {
            "known": sorted(known),
            "unknown": sorted(unknown),
            "compatibility": round(len(known) / len(status_values), 3) if status_values else 0.0,
        },
    }


def parse_kuerzel_format(antraege: list[dict]) -> dict:
    """Analyze the Antragsnummer format used by this LV."""
    formats = {
        "berlin_style": 0,  # "Antrag 150/I/2022"
        "number_only": 0,  # "123"
        "other": 0,
    }
    examples = {"berlin_style": [], "number_only": [], "other": []}

    for a in antraege[:50]:
        k = a.get("kuerzel", "")
        if re.match(r"^Antrag\s+\d+.*?/.*?/\d{4}$", k):
            formats["berlin_style"] += 1
            if len(examples["berlin_style"]) < 3:
                examples["berlin_style"].append(k)
        elif re.match(r"^\d+$", k.strip()):
            formats["number_only"] += 1
            if len(examples["number_only"]) < 3:
                examples["number_only"].append(k)
        else:
            formats["other"] += 1
            if len(examples["other"]) < 3:
                examples["other"].append(k)

    dominant = max(formats, key=formats.get)
    return {
        "counts": formats,
        "examples": examples,
        "dominant_format": dominant,
        "berlin_compatible": dominant == "berlin_style",
    }


def run_audit(base_url: str, output_dir: Path, sample_count: int = SAMPLE_COUNT):
    """Run full dry-run audit on a cvtx portal."""
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"AUDIT: {base_url}")
    print(f"{'='*60}\n")

    # Step 1: Discover events
    events = discover_events(base_url)
    if not events:
        print("ERROR: No events found. Is this a cvtx portal?")
        return None

    # Step 2: Fetch listing for each event
    all_antraege = []
    event_summaries = []

    for event in events:
        time.sleep(SCRAPE_DELAY)
        print(f"  Event: {event['label']} (ID {event['event_id']})...", end=" ", flush=True)
        try:
            rows = fetch_event_listing(base_url, event["event_id"])
            print(f"{len(rows)} Anträge")
            all_antraege.extend(rows)
            event_summaries.append({
                "event_id": event["event_id"],
                "label": event["label"],
                "antrag_count": len(rows),
            })
        except Exception as e:
            print(f"ERROR: {e}")
            event_summaries.append({
                "event_id": event["event_id"],
                "label": event["label"],
                "antrag_count": 0,
                "error": str(e),
            })

    total = len(all_antraege)
    print(f"\n  Total: {total} Anträge across {len(events)} events")

    # Step 3: Fetch sample Anträge (full content)
    print(f"\n  Fetching {sample_count} sample Anträge for content analysis...")
    samples = []

    # Pick samples from different events for diversity
    sample_indices = []
    if total > 0:
        step = max(1, total // sample_count)
        sample_indices = list(range(0, total, step))[:sample_count]

    for idx in sample_indices:
        antrag = all_antraege[idx]
        url = antrag.get("source_url", "")
        if not url:
            continue

        time.sleep(SCRAPE_DELAY)
        print(f"    {antrag.get('kuerzel', '?')}...", end=" ", flush=True)
        try:
            content = fetch_antrag_content(url)
            samples.append({
                "kuerzel": antrag.get("kuerzel", ""),
                "source_url": url,
                "content": content,
                "content_length": len(content),
            })
            print(f"{len(content)} chars")
        except Exception as e:
            print(f"ERROR: {e}")

    # Step 4: Score schema compatibility
    print("\n  Scoring schema compatibility...")
    compat = score_schema_compatibility(all_antraege, samples)
    kuerzel_format = parse_kuerzel_format(all_antraege)

    # Step 5: Build report
    report = {
        "audit_date": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "technology": "cvtx (WordPress)",
        "events": event_summaries,
        "total_antraege": total,
        "sample_count": len(samples),
        "schema_compatibility": compat,
        "kuerzel_format": kuerzel_format,
        "summary": {
            "overall_score": compat["overall_compatibility"],
            "status_compat": compat["status_vocabulary"]["compatibility"],
            "kuerzel_berlin_compatible": kuerzel_format["berlin_compatible"],
            "avg_content_length": (
                sum(s["content_length"] for s in samples) // len(samples)
                if samples else 0
            ),
            "verdict": _verdict(compat, kuerzel_format, total),
        },
    }

    # Save outputs
    report_path = output_dir / "discovery.json"
    with open(report_path, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # Save sample content for manual review
    samples_dir = output_dir / "samples"
    samples_dir.mkdir(exist_ok=True)
    for s in samples:
        slug = re.sub(r"[^a-z0-9]", "_", s["kuerzel"].lower())[:60]
        sample_path = samples_dir / f"{slug}.txt"
        sample_path.write_text(
            f"Kuerzel: {s['kuerzel']}\nURL: {s['source_url']}\n\n{s['content']}",
            encoding="utf-8",
        )

    # Save full listing (metadata only, no content)
    listing_path = output_dir / "all_antraege.json"
    with open(listing_path, "w") as f:
        json.dump(all_antraege, f, ensure_ascii=False, indent=2)

    # Print summary
    print(f"\n{'='*60}")
    print(f"AUDIT RESULTS: {base_url}")
    print(f"{'='*60}")
    print(f"  Events:            {len(events)}")
    print(f"  Total Anträge:     {total}")
    print(f"  Schema compat:     {compat['overall_compatibility']:.0%}")
    print(f"  Status compat:     {compat['status_vocabulary']['compatibility']:.0%}")
    print(f"  Kürzel Berlin-fmt: {'YES' if kuerzel_format['berlin_compatible'] else 'NO'}")
    print(f"  Avg content:       {report['summary']['avg_content_length']} chars")
    print(f"  Verdict:           {report['summary']['verdict']}")
    print()
    print(f"  Unknown statuses:  {compat['status_vocabulary']['unknown']}")
    print(f"  Kürzel examples:   {kuerzel_format['examples']}")
    print()

    for field, data in compat["fields"].items():
        marker = "+" if data["coverage"] >= 0.8 else "~" if data["coverage"] >= 0.5 else "-"
        print(f"    {marker} {field}: {data['coverage']:.0%}")

    print(f"\n  Report saved to {report_path}")
    print(f"  Listing saved to {listing_path}")
    print(f"  Samples saved to {samples_dir}/")

    return report


def _verdict(compat: dict, kuerzel: dict, total: int) -> str:
    score = compat["overall_compatibility"]
    if score >= 0.8 and kuerzel["berlin_compatible"] and total >= 50:
        return "READY — high compatibility, Berlin scraper adaptable"
    elif score >= 0.8 and total >= 50:
        return "ADAPTABLE — high field compat, kuerzel format needs mapping"
    elif score >= 0.6 and total >= 20:
        return "POSSIBLE — moderate compatibility, custom parser needed"
    elif total < 20:
        return "SKIP — too few Anträge to justify effort"
    else:
        return "SKIP — low compatibility, high effort"


def main():
    parser = argparse.ArgumentParser(description="Dry-run audit of cvtx SPD portals")
    parser.add_argument("--url", required=True, help="Base URL of cvtx portal")
    parser.add_argument("--output", required=True, help="Output directory for audit results")
    parser.add_argument("--samples", type=int, default=SAMPLE_COUNT, help="Number of sample Anträge to fetch")

    args = parser.parse_args()
    run_audit(args.url, Path(args.output), sample_count=args.samples)


if __name__ == "__main__":
    main()
