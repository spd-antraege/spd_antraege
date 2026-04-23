# SPD Thueringen

**Config:** `scraper/configs/thueringen.yaml`
**Technologie:** antragsgruen
**Portal:** https://inhalte.spd-thueringen.de
**Antraege:** ~60
**Zeitraum:** 2025
**Status:** Indexiert

## Scrapen

```bash
# Discover
python -m scraper.pipeline thueringen --discover

# Vollstaendig scrapen
python -m scraper.pipeline thueringen
```

## Besonderheiten

- Einziger Landesverband mit Antragsgruen-Technologie
- Bisher nur eine Consultation konfiguriert: `lpt25` (Landesparteitag 2025)
- Kleinstes Korpus aller Landesverbaende (60 Antraege)

## Datenqualitaet

- Schema-Kompatibilitaet: 0.80
- Kuerzel-Format: aus Antragsgruen-Slugs
