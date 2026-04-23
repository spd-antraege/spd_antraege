# SPD Hessen

**Config:** `scraper/configs/hessen.yaml`
**Technologie:** pdf
**Portal:** https://www.spd-hessen.de
**Antraege:** 320 Motions (608 Chunks in ES)
**Zeitraum:** 2017-2024
**PDFs:** 5 (LPT 2024, 2022 Antraege, 2022 Beschluesse, 2019 Beschluesse, 2017 Beschluesse)
**Status:** Indexiert

## Scrapen

```bash
python -m scraper.pipeline hessen
```

## Besonderheiten

- 5 PDF-Quellen konfiguriert, 3 extrahiert (2 blockiert: LPT 2024 Bildformat, LPT 2019 403)
- LPT 2022 Beschlussbuch: 192 Motions (groesstes PDF)
- LPT 2024 Antragsbuch laesst sich downloaden, aber pdfplumber extrahiert keinen Text (wahrscheinlich gescannt/Bild-PDF)
- LPT 2023 gibt 403 Forbidden zurueck

## Datenqualitaet

- Antragsteller: 76-86%
- Status: 61-62%
- LPT 2017: nur 40% Text >50 Zeichen (kurze Beschlusstexte)
