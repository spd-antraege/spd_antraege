# SPD Mecklenburg-Vorpommern

**Config:** `scraper/configs/mecklenburg_vorpommern.yaml`
**Technologie:** pdf
**Portal:** https://spd-mv.de
**Antraege:** 233 Motions (378 Chunks in ES)
**Zeitraum:** 2013-2024
**PDFs:** 7 (LPT 2024, 2022, 2019, 2018, 2017, 2015, 2013 — alle Beschlussbuecher)
**Status:** Indexiert

## Scrapen

```bash
python -m scraper.pipeline mecklenburg_vorpommern
```

## Besonderheiten

- 7 PDFs von spd-mv.de/downloads-presse — umfangreichste PDF-Abdeckung
- Meist Beschlussbuecher (nicht Antragsbuecher), daher hohe Status-Quote
- LPT 2017 einziges echtes Antragsbuch
- Durchgaengige Abdeckung 2013-2024 (12 Jahre)

## Datenqualitaet

- Antragsteller: 88-100% (sehr gut)
- Status: 20-100% (Beschlussbuecher enthalten Status, Antragsbuch 2017 weniger)
- Text >50c: 91-100%
- LPT 2013: 100% auf allen Feldern (bestes Einzelergebnis)
