"""
SPD multi-state scraper pipeline.

Stage-based architecture adapted from amtsguide_scraper.
Each state has its own config, parser, and output directory.

Usage:
    python -m scraper.pipeline brandenburg
    python -m scraper.pipeline --all
    python -m scraper.pipeline brandenburg --discover
    python -m scraper.pipeline --list
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
CONFIGS_DIR = Path(__file__).parent / "configs"
DATA_DIR = ROOT / "data"


def load_config(state: str) -> dict:
    """Load state config from YAML."""
    config_path = CONFIGS_DIR / f"{state}.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"No config for state '{state}'. Available: {list_states()}")
    with open(config_path) as f:
        return yaml.safe_load(f)


def list_states() -> list[str]:
    """List available state configs."""
    return sorted(p.stem for p in CONFIGS_DIR.glob("*.yaml"))


def get_parser(config: dict):
    """Get the appropriate parser for a state's technology."""
    tech = config.get("technology", "cvtx")
    if tech == "cvtx":
        from scraper.parsers.cvtx import CvtxParser
        return CvtxParser(config)
    elif tech == "mediawiki":
        from scraper.parsers.mediawiki import MediaWikiParser
        return MediaWikiParser(config)
    elif tech == "antragsgruen":
        from scraper.parsers.antragsgruen import AntragsgruenParser
        return AntragsgruenParser(config)
    elif tech == "pdf":
        # Use LLM-powered parser if MISTRAL_API_KEY is available
        if os.environ.get("MISTRAL_API_KEY"):
            from scraper.parsers.pdf_llm import LlmPdfParser
            return LlmPdfParser(config)
        from scraper.parsers.pdf import PdfParser
        return PdfParser(config)
    else:
        raise ValueError(f"Unknown technology: {tech}")


def run_pipeline(
    state: str,
    discover_only: bool = False,
    limit: int | None = None,
):
    """Run the full scraping pipeline for a state."""
    config = load_config(state)
    parser = get_parser(config)
    display = config.get("display_name", state)
    delay = config.get("scrape_delay", 1.0)
    checkpoint_interval = config.get("checkpoint_interval", 50)

    output_dir = DATA_DIR / "derived" / state
    vectors_dir = DATA_DIR / "vectors" / state / "documents"
    checkpoint_path = output_dir / f".checkpoint_{state}.json"

    print(f"\n{'='*60}")
    print(f"SCRAPING: {display}")
    print(f"Portal: {config.get('portal_url', 'N/A')}")
    print(f"Technology: {config.get('technology', 'unknown')}")
    print(f"{'='*60}\n")

    # --- Stage 1: Discover events ---
    print("Stage 1: Discovering events...")
    events = parser.discover_events()
    print(f"  Found {len(events)} events")
    for e in events:
        print(f"    {e.get('label', e.get('event_id', '?'))}")

    # --- Stage 2: List all motions ---
    print("\nStage 2: Listing motions...")
    all_motions = []

    # Load checkpoint if exists
    scraped_urls = set()
    if checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_text())
        scraped_urls = set(checkpoint.get("scraped_urls", []))
        print(f"  Checkpoint: {len(scraped_urls)} already scraped")

    for event in events:
        time.sleep(delay)
        motions = parser.list_motions(event)
        all_motions.extend(motions)
        print(f"  {event.get('label', '?')}: {len(motions)} motions")

    print(f"  Total: {len(all_motions)} motions")

    if discover_only:
        # Save discovery results and exit
        output_dir.mkdir(parents=True, exist_ok=True)
        discovery_path = output_dir / "discovery.json"
        with open(discovery_path, "w") as f:
            json.dump({
                "state": state,
                "events": events,
                "total_motions": len(all_motions),
                "motions": all_motions,
            }, f, ensure_ascii=False, indent=2)
        print(f"\n  Discovery saved to {discovery_path}")
        return

    # --- Stage 3: Fetch full content ---
    print("\nStage 3: Fetching content...")
    from scraper.normalize import normalize_motion

    results = []
    errors = 0
    skipped = 0

    if limit:
        all_motions = all_motions[:limit]

    for i, motion in enumerate(all_motions):
        # For PDF motions, all share the same source_url (the PDF file).
        # Use kuerzel as dedup key instead.
        dedup_key = motion.get("kuerzel", "") or motion.get("source_url", "")
        if dedup_key in scraped_urls:
            skipped += 1
            continue

        time.sleep(delay)
        if (i + 1) % 20 == 0 or i == 0:
            print(f"  [{i+1}/{len(all_motions)}] {motion.get('kuerzel', '?')}", flush=True)

        try:
            content = parser.fetch_content(motion)
            motion["text_content"] = content

            # --- Stage 4: Normalize ---
            normalized = normalize_motion(motion, config)
            results.append(normalized)
            scraped_urls.add(dedup_key)

        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"    ERROR: {motion.get('kuerzel', '?')}: {e}")

        # Checkpoint
        if (i + 1) % checkpoint_interval == 0:
            output_dir.mkdir(parents=True, exist_ok=True)
            checkpoint_path.write_text(json.dumps({
                "scraped_urls": list(scraped_urls),
                "results_count": len(results),
            }))

    print(f"  Fetched: {len(results)}, Skipped: {skipped}, Errors: {errors}")

    # --- Stage 5: Build parquet ---
    print("\nStage 5: Building parquet...")
    output_dir.mkdir(parents=True, exist_ok=True)

    import pandas as pd
    df = pd.DataFrame(results)
    parquet_path = output_dir / "antraege.parquet"
    df.to_parquet(parquet_path, index=False, engine="pyarrow")
    print(f"  {len(df)} rows → {parquet_path}")

    # --- Stage 6: Build vector index ---
    print("\nStage 6: Building vector index...")
    try:
        from spdbe.search import build_vector_index
        vectors_dir.mkdir(parents=True, exist_ok=True)
        build_vector_index(parquet_path, vectors_dir, batch_size=8)
        print(f"  Vectors → {vectors_dir}")
    except Exception as e:
        print(f"  SKIPPED (install sentence-transformers): {e}")

    # --- Stage 7: Summary ---
    print(f"\n{'='*60}")
    print(f"DONE: {display}")
    print(f"  Motions: {len(results)}")
    print(f"  Parquet: {parquet_path}")
    print(f"  Errors: {errors}")
    print(f"{'='*60}\n")

    # Clean up checkpoint on success
    if checkpoint_path.exists():
        checkpoint_path.unlink()

    return results


def main():
    parser = argparse.ArgumentParser(description="SPD multi-state scraper")
    parser.add_argument("state", nargs="?", help="State to scrape (e.g. brandenburg)")
    parser.add_argument("--all", action="store_true", help="Scrape all configured states")
    parser.add_argument("--discover", action="store_true", help="Discover only, don't fetch content")
    parser.add_argument("--list", action="store_true", help="List available state configs")
    parser.add_argument("--limit", type=int, help="Limit number of motions to fetch")

    args = parser.parse_args()

    if args.list:
        states = list_states()
        print(f"Available states ({len(states)}):")
        for s in states:
            config = load_config(s)
            print(f"  {s:25s} {config.get('display_name', '')} ({config.get('technology', '?')})")
        return

    if args.all:
        for state in list_states():
            config = load_config(state)
            if config.get("technology") in ("cvtx", "mediawiki"):
                run_pipeline(state, discover_only=args.discover, limit=args.limit)
        return

    if not args.state:
        parser.print_help()
        sys.exit(1)

    run_pipeline(args.state, discover_only=args.discover, limit=args.limit)


if __name__ == "__main__":
    main()
