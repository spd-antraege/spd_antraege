# SPD Bundespartei

**Config:** `scraper/configs/bund.yaml`
**Technologie:** pdf
**Portal:** https://parteitag.spd.de
**Antraege:** ~3.000
**Zeitraum:** 2012-2025
**Status:** Indexiert

## Scrapen

```bash
# Discover
python -m scraper.pipeline bund --discover

# Vollstaendig scrapen
python -m scraper.pipeline bund
```

## Besonderheiten

- PDF-basiert: Antragsbuecher werden als PDF heruntergeladen und mit LlmPdfParser verarbeitet
- LlmPdfParser nutzt MISTRAL_API_KEY (Doppler) wenn verfuegbar
- 7 PDF-Quellen konfiguriert: oBPT 2025, aoBPT 2025, oBPT 2023, aoBPT 2018, aoBPT 2014, aoBPT 2013, aoBPT 2012
- Hoeherer Scrape-Delay (2.0s) wegen PDF-Download

## Datenqualitaet

- Schema-Kompatibilitaet: nicht auditiert (PDF-Extraktion)
- Kuerzel-Format: aus PDF extrahiert
