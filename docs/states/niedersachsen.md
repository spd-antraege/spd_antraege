# SPD Niedersachsen

**Config:** `scraper/configs/niedersachsen.yaml`
**Technologie:** pdf
**Portal:** https://www.spdnds.de
**Antraege:** ~600
**Zeitraum:** 2020-2025
**Status:** Teilweise

## Scrapen

```bash
# Discover
python -m scraper.pipeline niedersachsen --discover

# Vollstaendig scrapen
python -m scraper.pipeline niedersachsen
```

## Besonderheiten

- PDF-basiert: Antragsbuecher mit LlmPdfParser verarbeitet (MISTRAL_API_KEY aus Doppler)
- Bisher nur 1 PDF-Quelle konfiguriert: LPT 2025 Wolfenbuettel
- Nur 156 Chunks bisher indexiert -- weiterer Ausbau noetig
- Hoeherer Scrape-Delay (2.0s) wegen PDF-Download

## Datenqualitaet

- Schema-Kompatibilitaet: nicht auditiert (PDF-Extraktion)
- Kuerzel-Format: aus PDF extrahiert
