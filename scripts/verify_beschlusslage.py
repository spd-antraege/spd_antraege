#!/usr/bin/env python3
"""Verify strategist Beschlusslage claims against Antrag corpus text."""

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from sync_antraege import MD_DIR, parse_markdown_frontmatter

STRATEGIST_DIR = Path("/home/andx/spd_antraege/tools/strategist")
OUTPUT_DIR = Path("/home/andx/spd_antraege/tools/data/verification")

REF_COMBINED = re.compile(r"\b([0-9A-Za-z]+(?:\+[0-9A-Za-z]+)+)/(I{1,3}V?|IV)/(\d{4})\b")
REF_SINGLE = re.compile(r"\b(?:Antrag\s+)?([0-9A-Za-z]+)/(I{1,3}V?|IV)/(\d{4})\b")
TOKEN_RE = re.compile(r"[a-zA-Z0-9äöüÄÖÜß]{3,}")

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
    "kein",
    "keine",
    "nicht",
    "mehr",
    "sowie",
    "dass",
    "als",
    "bei",
    "auch",
    "durch",
    "zum",
    "zur",
}



def utc_now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()



def canonical_kuerzel(number, session, year):
    return f"Antrag {number}/{session}/{year}"



def normalize_text(text):
    return re.sub(r"\s+", " ", text.lower()).strip()



def extract_refs(text):
    refs = []
    for match in REF_COMBINED.finditer(text):
        numbers = match.group(1).split("+")
        session, year = match.group(2), match.group(3)
        for number in numbers:
            refs.append(canonical_kuerzel(number, session, year))

    for match in REF_SINGLE.finditer(text):
        refs.append(canonical_kuerzel(match.group(1), match.group(2), match.group(3)))

    # Deduplicate preserving order.
    out = []
    seen = set()
    for ref in refs:
        if ref in seen:
            continue
        seen.add(ref)
        out.append(ref)
    return out



def claim_keywords(claim_text):
    words = [w.lower() for w in TOKEN_RE.findall(claim_text)]
    words = [w for w in words if w not in STOPWORDS and len(w) >= 4]
    # Keep order, unique
    seen = set()
    deduped = []
    for w in words:
        if w in seen:
            continue
        seen.add(w)
        deduped.append(w)
    return deduped[:14]



def evaluate_claim(claim_text, body_text):
    claim_norm = normalize_text(claim_text)
    body_norm = normalize_text(body_text)

    if not claim_norm:
        return "partially_supported", 0.0, []

    if claim_norm in body_norm:
        return "confirmed", 1.0, []

    keywords = claim_keywords(claim_text)
    if not keywords:
        return "partially_supported", 0.3, []

    hits = [kw for kw in keywords if kw in body_norm]
    ratio = len(hits) / max(1, len(keywords))

    # Minimal contradiction heuristic for negation claims.
    neg = re.search(r"\bkein(?:e|en|em|er)?\s+([a-z0-9äöüß]{4,})", claim_norm)
    if neg:
        term = neg.group(1)
        if term in body_norm and f"kein {term}" not in body_norm and f"keine {term}" not in body_norm:
            return "contradicted", ratio, hits

    if ratio >= 0.75:
        return "confirmed", ratio, hits
    if ratio >= 0.35:
        return "partially_supported", ratio, hits
    return "not_found", ratio, hits



def load_strategist_themes():
    themes = {}

    index_path = STRATEGIST_DIR / "index.json"
    themes_dir = STRATEGIST_DIR / "themes"

    if index_path.exists() and themes_dir.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
        for theme_id in (index.get("themes") or {}).keys():
            theme_path = themes_dir / f"{theme_id}.json"
            if not theme_path.exists():
                continue
            theme_data = json.loads(theme_path.read_text(encoding="utf-8"))
            themes[theme_id] = theme_data
        if themes:
            return themes

    legacy_state = STRATEGIST_DIR / "state.json"
    if legacy_state.exists():
        state = json.loads(legacy_state.read_text(encoding="utf-8"))
        themes = state.get("themes") or {}

    return themes



def build_corpus_index():
    corpus = {}
    for path in sorted(MD_DIR.rglob("*.md")):
        fm, body = parse_markdown_frontmatter(path)
        kuerzel = fm.get("kuerzel") if isinstance(fm, dict) else None
        if not kuerzel:
            continue
        corpus[kuerzel] = {
            "path": str(path),
            "title": fm.get("titel", ""),
            "body": body,
        }
    return corpus



def parse_beschlusslage_entry(entry):
    # Common form: "150/I/2022: Claim text"
    if ":" in entry:
        left, right = entry.split(":", 1)
        refs = extract_refs(left)
        claim = right.strip()
    else:
        refs = extract_refs(entry)
        claim = entry.strip()

    return refs, claim



def main():
    parser = argparse.ArgumentParser(description="Verify strategist Beschlusslage claims")
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(OUTPUT_DIR),
        help="Directory for JSON+Markdown report",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    themes = load_strategist_themes()
    corpus = build_corpus_index()

    results = []

    for theme_id, theme_data in themes.items():
        entries = theme_data.get("beschlusslage") or []
        for raw_entry in entries:
            refs, claim = parse_beschlusslage_entry(raw_entry)
            if not refs:
                results.append(
                    {
                        "theme_id": theme_id,
                        "entry": raw_entry,
                        "kuerzel": None,
                        "status": "not_found",
                        "score": 0.0,
                        "hits": [],
                        "reason": "No Antrag reference parsed",
                    }
                )
                continue

            for ref in refs:
                doc = corpus.get(ref)
                if not doc:
                    results.append(
                        {
                            "theme_id": theme_id,
                            "entry": raw_entry,
                            "kuerzel": ref,
                            "status": "not_found",
                            "score": 0.0,
                            "hits": [],
                            "reason": "Referenced Antrag not found in corpus",
                        }
                    )
                    continue

                status, score, hits = evaluate_claim(claim, doc["body"])
                results.append(
                    {
                        "theme_id": theme_id,
                        "entry": raw_entry,
                        "kuerzel": ref,
                        "status": status,
                        "score": round(score, 3),
                        "hits": hits,
                        "path": doc["path"],
                    }
                )

    counts = Counter(item["status"] for item in results)

    payload = {
        "generated_at": utc_now_iso(),
        "summary": dict(counts),
        "total": len(results),
        "results": results,
    }

    json_path = output_dir / "beschlusslage_verification.json"
    md_path = output_dir / "beschlusslage_verification.md"

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = []
    lines.append("# Beschlusslage Verification Report")
    lines.append("")
    lines.append(f"Generated: {payload['generated_at']}")
    lines.append(f"Total checks: {payload['total']}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    for key in ["confirmed", "partially_supported", "not_found", "contradicted"]:
        lines.append(f"- {key}: {counts.get(key, 0)}")

    lines.append("")
    lines.append("## Findings")
    lines.append("")
    for item in results:
        lines.append(
            f"- [{item['status']}] {item.get('theme_id')} | {item.get('kuerzel')} | score={item.get('score')} | {item['entry']}"
        )

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Wrote JSON: {json_path}")
    print(f"Wrote Markdown: {md_path}")
    print(f"Summary: {dict(counts)}")


if __name__ == "__main__":
    main()
