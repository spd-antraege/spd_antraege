# SPD Rheinland-Pfalz

**Config:** `scraper/configs/rlp.yaml`
**Technologie:** cvtx
**Portal:** https://antraege.spd-rlp.de
**Antraege:** ~610
**Zeitraum:** 2018-2026
**Status:** Indexiert

## Scrapen

```bash
# Discover
python -m scraper.pipeline rlp --discover

# Vollstaendig scrapen
python -m scraper.pipeline rlp
```

## Besonderheiten

- 8 Events erfasst
- Kuerzel-Format: `{year}/{session}/{number}` (z.B. "2025/KL/4")
- Status "geaendert angenommen" wird auf "Annahme mit Aenderungen" gemappt

## Datenqualitaet

- Schema-Kompatibilitaet: 1.0
- Status-Kompatibilitaet: 0.86
- Kuerzel-Format: `{year}/{session}/{number}`
