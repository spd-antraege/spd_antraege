# SPD Schleswig-Holstein

**Config:** `scraper/configs/schleswig_holstein.yaml`
**Technologie:** mediawiki
**Portal:** http://beschluesse.spd-schleswig-holstein.de
**Antraege:** ~2.003
**Zeitraum:** 1971-2023
**Status:** Indexiert

## Scrapen

```bash
# Discover
python -m scraper.pipeline schleswig_holstein --discover

# Vollstaendig scrapen
python -m scraper.pipeline schleswig_holstein
```

## Besonderheiten

- Einziger Landesverband mit MediaWiki-Technologie
- Beschluss-Template-Felder werden auf Schema gemappt (Gremium, Gliederung, Sitzung, Nr, etc.)
- Laengster Zeitraum aller Landesverbaende: ab 1971
- Sub-Wikis auf KV-Ebene vorhanden: KV Kiel (163 Seiten), KV Steinburg (79 Seiten)
- API-Endpoint: `http://beschluesse.spd-schleswig-holstein.de/api.php`

## Datenqualitaet

- Schema-Kompatibilitaet: 0.85
- Kuerzel-Format: aus Template-Feld "Nr"
