# SPD Baden-Wuerttemberg

**Config:** `scraper/configs/baden_wuerttemberg.yaml`
**Technologie:** pdf
**Portal:** https://www.spd-bw.de
**Antraege:** 300 Motions (697 Chunks in ES)
**Zeitraum:** 2010-2024
**PDFs:** 5 (LPT 2024, 2023, 2022, 2011, 2010)
**Status:** Indexiert

## Scrapen

```bash
python -m scraper.pipeline baden_wuerttemberg
```

## Besonderheiten

- PDF-basiert: Antragsbuecher mit LlmPdfParser (Mistral Small)
- 5 PDF-Quellen konfiguriert, alle extrahiert und indexiert
- LPT 2022 groesstes Antragsbuch: 140 Motions
- LPT 2024 mit Begruendungen (Antragsbuch_mit_Begruendungen_web.pdf)

## Datenqualitaet

- Antragsteller: 64-86% je nach PDF
- Status: 39-91%
- 3 Motions mit NaN-Feldern (ignoriert beim Indexieren)
