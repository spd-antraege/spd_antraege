# SPD Hamburg

**Config:** `scraper/configs/hamburg.yaml`
**Technologie:** cvtx
**Portal:** https://beschlossen.spd-hamburg.de
**Antraege:** ~918
**Zeitraum:** 2019-2026
**Status:** Indexiert

## Scrapen

```bash
# Discover
python -m scraper.pipeline hamburg --discover

# Vollstaendig scrapen
python -m scraper.pipeline hamburg
```

## Besonderheiten

- 13 Events erfasst
- Kuerzel-Format weicht stark ab: `{year}/{session}/{category}/{number}` (z.B. "2026/I/Woh/1")
- Kategorien im Kuerzel enthalten (z.B. "Woh" fuer Wohnen)

## Datenqualitaet

- Schema-Kompatibilitaet: 0.95
- Status-Kompatibilitaet: 0.83
- Kuerzel-Format: `{year}/{session}/{category}/{number}`
