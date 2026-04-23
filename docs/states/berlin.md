# SPD Berlin

**Config:** Kein YAML-Config -- nutzt separates Sync-Skript `scripts/sync_antraege.py`
**Technologie:** cvtx
**Portal:** https://parteitag.spd.berlin/antragsverfolgung/
**Antraege:** ~4.087
**Zeitraum:** 2010-2026
**Status:** Indexiert

## Scrapen

```bash
# Discover (dry run)
python scripts/sync_antraege.py --discover

# Scrapen (neueste 3 Events)
python scripts/sync_antraege.py --scrape

# Bestimmte Events scrapen
python scripts/sync_antraege.py --scrape --events "II/2025"
```

## Besonderheiten

- Nutzt NICHT die scraper.pipeline, sondern ein eigenes Skript (`scripts/sync_antraege.py`)
- Referenz-Landesverband: Alle anderen Scraper orientieren sich am Berlin-Schema
- Kuerzel-Format: `Antrag {number}/{session}/{year}`
- Antraege landen in `corpus/berlin/`

## Datenqualitaet

- Schema-Kompatibilitaet: 1.0 (Referenz)
- Kuerzel-Format: `Antrag {number}/{session}/{year}`
