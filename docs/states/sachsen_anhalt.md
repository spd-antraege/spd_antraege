# SPD Sachsen-Anhalt

**Config:** `scraper/configs/sachsen_anhalt.yaml`
**Technologie:** pdf
**Portal:** https://spdsachsenanhalt.de
**Antraege:** 176 Motions (451 Chunks in ES)
**Zeitraum:** 2024
**PDFs:** 1 (LPT 2024 — einzige erreichbare Quelle)
**Status:** Indexiert

## Scrapen

```bash
python -m scraper.pipeline sachsen_anhalt
```

## Besonderheiten

- Nur LPT 2024 verfuegbar (spdsachsenanhalt.de, neue Website)
- Alte Website (spd-sachsen-anhalt.de) PDFs von 2010 und 2013 geben 404
- 176 Motions aus einem einzigen Antragsbuch — dennoch substantiell

## Datenqualitaet

- Antragsteller: 94% (165/176)
- Status: 77% (135/176)
- Text >50c: 91% (161/176)
