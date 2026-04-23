# SPD Brandenburg

**Config:** `scraper/configs/brandenburg.yaml`
**Technologie:** cvtx
**Portal:** https://www.parteitag-spd-brandenburg.de
**Antraege:** ~1.723
**Zeitraum:** 2015-2026
**Status:** Indexiert

## Scrapen

```bash
# Discover
python -m scraper.pipeline brandenburg --discover

# Vollstaendig scrapen
python -m scraper.pipeline brandenburg
```

## Besonderheiten

- 20 Events erfasst
- Kuerzel-Format ohne Prefix: `{number}/{session}/{year}` (Berlin nutzt "Antrag " als Prefix)
- Vollstaendige Status-Abdeckung inkl. "zurueckgezogen" und "nicht abgestimmt"

## Datenqualitaet

- Schema-Kompatibilitaet: 1.0
- Status-Kompatibilitaet: 1.0
- Kuerzel-Format: `{number}/{session}/{year}`
