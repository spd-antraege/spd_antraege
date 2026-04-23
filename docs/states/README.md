# Landesverbände — Scraper-Dokumentation

Jeder Landesverband hat eine eigene Konfiguration in `scraper/configs/`.
Diese Docs beschreiben pro Staat: Portal-Typ, URL, Besonderheiten, Status.

## Übersicht

| Staat | Technologie | Chunks (ES) | PDFs | Status |
|---|---|---|---|---|
| [Berlin](berlin.md) | cvtx (sync_antraege.py) | 18.297 | — | Indexiert |
| [Schleswig-Holstein](schleswig_holstein.md) | mediawiki | 10.235 | — | Indexiert |
| [Brandenburg](brandenburg.md) | cvtx | 5.060 | — | Indexiert |
| [Hamburg](hamburg.md) | cvtx | 4.549 | — | Indexiert |
| [Rheinland-Pfalz](rlp.md) | cvtx | 3.644 | — | Indexiert |
| [Bund](bund.md) | pdf | 1.441 | 6 | Indexiert |
| [NRW](nrw.md) | pdf (LLM) | 1.251 | 7 | Indexiert |
| [Baden-Württemberg](baden_wuerttemberg.md) | pdf (LLM) | 697 | 5 | Indexiert |
| [Hessen](hessen.md) | pdf (LLM) | 608 | 5 | Indexiert |
| [Thüringen](thueringen.md) | antragsgruen | 483 | — | Indexiert |
| [Sachsen-Anhalt](sachsen_anhalt.md) | pdf (LLM) | 451 | 3 | Indexiert |
| [Bayern](bayern.md) | cvtx | 421 | — | Indexiert |
| [Mecklenburg-Vorpommern](mecklenburg_vorpommern.md) | pdf (LLM) | 378 | 7 | Indexiert |
| [Sachsen](sachsen.md) | pdf (LLM) | 300 | 2 | Indexiert |
| [Bremen](bremen.md) | pdf (LLM) | 183 | 1 | Indexiert |
| [Niedersachsen](niedersachsen.md) | pdf | 156 | 1 | Indexiert |

## Technologien

### cvtx (WordPress-Plugin)
Strukturiertes HTML-Portal. Scraper nutzt BeautifulSoup. Zuverlässigste Quelle: Kürzel, Antragsteller, Status, Volltext einzeln abrufbar.

### mediawiki
Wikipedia-API. Anträge als Wiki-Seiten. Gute Metadaten, API-basiert.

### antragsgruen
REST-API (antragsgruen.de). Strukturierte JSON-Daten.

### pdf
PDF-Antragsbücher. Zwei Parser:
- **PdfParser** (regex): `scraper/parsers/pdf.py` — schnell, aber fragil bei unbekannten Formaten
- **LlmPdfParser** (Mistral Small): `scraper/parsers/pdf_llm.py` — zuverlässiger, braucht MISTRAL_API_KEY
