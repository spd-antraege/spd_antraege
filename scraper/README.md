# SPD Scraper

Multi-state SPD Antragskorpus scraper. Adapted from [amtsguide_scraper](../../business/amtsguide_scraper) architecture.

## Architecture

```
configs/{state}.yaml     — per-state config (portal URL, tech, field mappings)
pipeline.py              — stage orchestration
parsers/
  cvtx.py                — cvtx WordPress plugin (Berlin, Brandenburg, Hamburg, Bayern, RLP)
  mediawiki.py           — MediaWiki API (Schleswig-Holstein, KV wikis)
  antragsgruen.py        — Antragsgrün REST API (Thüringen)
  pdf.py                 — PDF Antragsbuch segmentation (Bund, NRW, BaWü, etc.)
normalize.py             — kuerzel mapping, status normalization, dedup
evals/                   — per-state eval fixtures (inherited from ../evals/)
```

## Pipeline Stages

```
Stage 0: Load config
Stage 1: Discover events/conventions (list Parteitage)
Stage 2: List motions per event (metadata: kuerzel, title, status, submitter)
Stage 3: Fetch full content per motion (HTML/wiki/API/PDF)
Stage 4: Normalize to Berlin schema (kuerzel mapping, status mapping)
Stage 5: Build parquet (data/derived/{state}/antraege.parquet)
Stage 6: Build vector index (data/vectors/{state}/documents/)
Stage 7: Run extraction eval (5 sample docs, score against baseline)
```

## Usage

```bash
# Scrape one state
python -m scraper.pipeline brandenburg

# Scrape all configured states
python -m scraper.pipeline --all

# Discover only (dry run, no content fetch)
python -m scraper.pipeline brandenburg --discover

# List available configs
python -m scraper.pipeline --list
```

## Config Format

```yaml
state: brandenburg
display_name: "SPD Brandenburg"
portal_url: "https://www.parteitag-spd-brandenburg.de"
technology: cvtx          # cvtx | mediawiki | antragsgruen | pdf

kuerzel_format: "{number}/{session}/{year}"
kuerzel_prefix: "Antrag "  # prepended to make Berlin-compatible

status_map:
  "annahme": "Annahme"
  "ablehnung": "Ablehnung"
  # ...

scrape_delay: 1.0         # seconds between requests
checkpoint_interval: 50   # save progress every N motions
```

## Key Differences from amtsguide_scraper

| amtsguide_scraper | spd_scraper |
|---|---|
| Scrapes commercial suppliers + gov pages | Scrapes political motion portals |
| Brave Search for URL discovery | URLs known from audit (configs) |
| Shopify API enrichment | N/A |
| Impressum extraction | N/A |
| Outscraper fallback | N/A |
| Tabstack for gov extraction | N/A (cvtx HTML is simple) |
| Claude for field extraction | Claude for intelligence extraction (topics, demands, actors) |
| Per-supplier output | Per-state parquet + vectors |

## What We Kept

- Stage-based pipeline with checkpointing
- Config-driven field definitions
- Eval harness + regression detection
- Rate limiting + polite crawling
- Normalize + dedup stage
- Hard timeout protection for LLM calls
