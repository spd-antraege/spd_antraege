# NRWSPD

**Config:** `scraper/configs/nrw.yaml`
**Technologie:** pdf
**Portal:** https://www.nrwspd.de
**Antraege:** 441 Motions (1.251 Chunks in ES)
**Zeitraum:** 2011-2025
**PDFs:** 7 (LPT 2025, 2023, a.o. 2022, 2021 Leitantraege, 2021 Antraege, 2011)
**Status:** Indexiert

## Scrapen

```bash
python -m scraper.pipeline nrw
```

## Besonderheiten

- PDF-basiert: Antragsbuecher mit LlmPdfParser (Mistral Small)
- 7 PDF-Quellen konfiguriert, alle extrahiert und indexiert
- LPT 2025: 78 Motions, 58% Submitter, 65% Status
- LPT 2023: 172 Motions, 90% Submitter, 90% Status (bestes Ergebnis)

## Datenqualitaet

- Kuerzel-Format: aus PDF extrahiert, normalisiert (Praefix "Antrag " entfernt)
- Antragsteller: 36-90% je nach PDF (aeltere PDFs schlechter)
- Status: 5-90% (Leitantraege haben oft keinen Status im Antragsbuch)
