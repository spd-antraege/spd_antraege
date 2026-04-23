#!/usr/bin/env python3
"""Generate deterministic year-by-year trend reports per strategist theme."""

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from sync_antraege import MD_DIR, parse_markdown_frontmatter

STRATEGIST_DIR = Path("/home/andx/spd_antraege/tools/strategist")
OUTPUT_DIR = Path("/home/andx/spd_antraege/tools/data/trends")
WORD_RE = re.compile(r"[a-zA-Z0-9äöüÄÖÜß]{3,}")

STOPWORDS = {
    "und",
    "oder",
    "der",
    "die",
    "das",
    "dem",
    "den",
    "ein",
    "eine",
    "einer",
    "eines",
    "mit",
    "auf",
    "für",
    "von",
    "ist",
    "sind",
    "wird",
    "werden",
    "nicht",
    "kein",
    "keine",
    "mehr",
    "durch",
    "auch",
    "sowie",
    "zum",
    "zur",
    "berlin",
    "spd",
    "antrag",
}



def utc_now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()



def parse_year_from_kuerzel(kuerzel):
    m = re.search(r"/(\d{4})$", kuerzel or "")
    return m.group(1) if m else "unknown"



def theme_keywords(theme_id, theme_data):
    words = []

    words.extend(theme_id.split("_"))

    label = (theme_data.get("label") or "").lower()
    words.extend(WORD_RE.findall(label))

    summary = (theme_data.get("summary") or "").lower()
    words.extend(WORD_RE.findall(summary)[:40])

    out = []
    seen = set()
    for w in words:
        wl = w.lower()
        if len(wl) < 4 or wl in STOPWORDS:
            continue
        if wl in seen:
            continue
        seen.add(wl)
        out.append(wl)

    return out[:30]



def load_themes():
    index_path = STRATEGIST_DIR / "index.json"
    themes_dir = STRATEGIST_DIR / "themes"

    if index_path.exists() and themes_dir.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
        themes = {}
        for theme_id in (index.get("themes") or {}).keys():
            theme_path = themes_dir / f"{theme_id}.json"
            if theme_path.exists():
                themes[theme_id] = json.loads(theme_path.read_text(encoding="utf-8"))
        if themes:
            return themes

    state_path = STRATEGIST_DIR / "state.json"
    if not state_path.exists():
        return {}

    state = json.loads(state_path.read_text(encoding="utf-8"))
    return state.get("themes") or {}



def corpus_documents():
    docs = []
    for path in sorted(MD_DIR.rglob("*.md")):
        fm, body = parse_markdown_frontmatter(path)
        if not isinstance(fm, dict):
            continue
        kuerzel = fm.get("kuerzel")
        if not kuerzel:
            continue
        docs.append(
            {
                "kuerzel": kuerzel,
                "year": parse_year_from_kuerzel(kuerzel),
                "status": fm.get("status_in_tabelle", "unknown"),
                "antragsteller": fm.get("antragsteller", "unknown"),
                "text": f"{fm.get('titel', '')}\n\n{body}".lower(),
            }
        )
    return docs



def score_doc_for_theme(doc_text, keywords):
    hits = 0
    for kw in keywords:
        if kw in doc_text:
            hits += 1
    return hits



def write_theme_report(theme_id, theme_data, matched_docs):
    by_year = defaultdict(list)
    for doc in matched_docs:
        by_year[doc["year"]].append(doc)

    years = sorted(by_year.keys())

    lines = []
    lines.append(f"# Trend Report: {theme_data.get('label', theme_id)}")
    lines.append("")
    lines.append(f"Theme: `{theme_id}`")
    lines.append(f"Generated: {utc_now_iso()}")
    lines.append(f"Matched docs: {len(matched_docs)}")
    lines.append("")

    lines.append("## Yearly Counts")
    lines.append("")
    lines.append("| Year | Count |")
    lines.append("|---|---:|")
    for year in years:
        lines.append(f"| {year} | {len(by_year[year])} |")

    lines.append("")
    lines.append("## Status Distribution")
    lines.append("")
    status_counter = Counter(doc["status"] for doc in matched_docs)
    for status, count in status_counter.most_common():
        lines.append(f"- {status}: {count}")

    lines.append("")
    lines.append("## Key Antragsteller")
    lines.append("")
    actor_counter = Counter(doc["antragsteller"] for doc in matched_docs)
    for actor, count in actor_counter.most_common(10):
        lines.append(f"- {actor}: {count}")

    lines.append("")
    lines.append("## Recent Examples")
    lines.append("")
    recent = sorted(matched_docs, key=lambda d: (d["year"], d["kuerzel"]), reverse=True)[:20]
    for doc in recent:
        lines.append(f"- {doc['kuerzel']} ({doc['year']}, {doc['status']})")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / f"{theme_id}.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")



def main():
    parser = argparse.ArgumentParser(description="Generate trend analysis markdown reports")
    parser.add_argument(
        "--min-score",
        type=int,
        default=2,
        help="Minimum keyword hits to assign a document to a theme",
    )
    args = parser.parse_args()

    themes = load_themes()
    if not themes:
        print("No themes found in strategist state/index.")
        return

    docs = corpus_documents()

    overview = {
        "generated_at": utc_now_iso(),
        "themes": {},
    }

    for theme_id, theme_data in themes.items():
        keywords = theme_keywords(theme_id, theme_data)
        matched = []
        for doc in docs:
            if score_doc_for_theme(doc["text"], keywords) >= args.min_score:
                matched.append(doc)

        write_theme_report(theme_id, theme_data, matched)

        by_year = Counter(doc["year"] for doc in matched)
        overview["themes"][theme_id] = {
            "label": theme_data.get("label", theme_id),
            "match_count": len(matched),
            "years": dict(sorted(by_year.items())),
            "keywords": keywords,
        }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    overview_path = OUTPUT_DIR / "overview.json"
    overview_path.write_text(json.dumps(overview, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote trend reports to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
