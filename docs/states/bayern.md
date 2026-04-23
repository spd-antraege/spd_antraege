# BayernSPD

**Config:** `scraper/configs/bayern.yaml`
**Technologie:** cvtx
**Portal:** https://www.parteitag-bayernspd.de
**Antraege:** ~944
**Zeitraum:** 2017-2025
**Status:** Indexiert

## Scrapen

```bash
# Discover
python -m scraper.pipeline bayern --discover

# Vollstaendig scrapen
python -m scraper.pipeline bayern
```

## Besonderheiten

- 11 Events erfasst
- Kuerzel-Format nutzt Kurzcodes statt Nummern: `{code}` (z.B. "LAT1", "W6", "S11")
- Berlin-kompatible ID: `{code}/{event_label}` (z.B. "LAT1/I-2024-Landeskonferenz")

## Datenqualitaet

- Schema-Kompatibilitaet: 0.92
- Status-Kompatibilitaet: 0.86
- Kuerzel-Format: `{code}` (nicht nummernbasiert)
