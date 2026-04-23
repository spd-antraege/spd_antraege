# SPD Sachsen

**Config:** `scraper/configs/sachsen.yaml`
**Technologie:** pdf
**Portal:** https://sachsenspd.de
**Antraege:** 175 Motions (300 Chunks in ES)
**Zeitraum:** 2025
**PDFs:** 2 (LPT 2025 Antragsbuch, LPT 2025 Beschlussbuch)
**Status:** Indexiert

## Scrapen

```bash
python -m scraper.pipeline sachsen
```

## Besonderheiten

- Alte Website (spd-sachsen.de) gibt 500 — migriert zu sachsenspd.de
- Nur LPT 2025 verfuegbar (Antragsbuch + Beschlussbuch)
- Aeltere PDFs (2015, 2019, 2021) nicht mehr erreichbar
- Auch antraege.spd-sachsen.de Web-Portal existiert (nicht gescrapt)

## Datenqualitaet

- Antragsteller: 50-57% (Antragsbuch besser als Beschlussbuch)
- Status: 0% im Antragsbuch, 48% im Beschlussbuch
- Text >50c: 56-66%
