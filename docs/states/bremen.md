# SPD Bremen

**Config:** `scraper/configs/bremen.yaml`
**Technologie:** pdf
**Portal:** https://www.spd-land-bremen.de
**Antraege:** 53 Motions (183 Chunks in ES)
**Zeitraum:** 2025
**PDFs:** 1 (LPT 2025)
**Status:** Indexiert

## Scrapen

```bash
python -m scraper.pipeline bremen
```

## Besonderheiten

- Bisher nur 1 PDF-Quelle: LPT 2025 Antragsbuch
- 100% Submitter, 98% Status — beste Extraktionsqualitaet aller Staaten
- Zusaetzlich 437 Online-Beschluesse (HTML) auf spd-land-bremen.de — noch nicht gescrapt
- Aeltere Antragsbuecher nicht online verfuegbar

## Datenqualitaet

- Sehr gut: 53/53 Submitter, 52/53 Status, 53/53 Text
- Kuerzel-Format: aus PDF extrahiert
