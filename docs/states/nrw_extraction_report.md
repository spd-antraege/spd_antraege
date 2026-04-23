# NRW PDF Extraction Report

**Date:** 2026-04-22
**Source:** LPT 2025 Antragsbuch (108 Seiten, 1.7 MB)
**Parser:** LlmPdfParser (Mistral Small)
**API Errors:** 1x 503 (retry successful on all but 1 page)

## Ergebnisse

| Metrik | Wert |
|---|---|
| Extrahierte Anträge | **143** |
| Hat Titel | 143/143 (100%) |
| Hat Antragsteller | 52/143 (36%) |
| Hat Status | 58/143 (41%) |
| Hat Text (>50 Zeichen) | 79/143 (55%) |
| Durchschnittliche Textlänge | 780 Zeichen |

## Sachgebiete

| Prefix | Anzahl | Thema |
|---|---|---|
| (ohne) | 33 | Diverse (aus TOC-Extraktion) |
| B | 14 | Bildung |
| G | 14 | Gesundheit |
| Sä | 19 | Satzungsanträge |
| Ar | 8 | Arbeitsmarkt |
| Au | 8 | Außenpolitik |
| A | 7 | Leitantrag |
| S | 5 | Soziales |
| I | 8 | Innenpolitik |
| O | 8 | Organisation |
| F | 4 | Finanzen |
| K | 2 | Kommunales |
| St | 2 | Stadtentwicklung |

## Probleme und Verbesserungspotenzial

### 1. Antragsteller fehlt bei 64% der Anträge
**Ursache:** Der Antragsteller steht oft auf der gleichen Seite wie der Antragstitel, aber Mistral extrahiert ihn nicht konsistent. Auf Seiten mit vielen kurzen Anträgen fehlt er häufiger.
**Fix:** Prompt anpassen — "Antragsteller*in:" als Pflichtfeld betonen, Beispielformat mitgeben.

### 2. Status fehlt bei 59% der Anträge
**Ursache:** Viele Anträge im Antragsbuch haben keinen Status (er wird erst nach dem Parteitag festgelegt). Die "Empfehlung der Antragskommission" ist vorhanden, wird aber nicht immer als Status erkannt.
**Fix:** Prompt erweitern — "Empfehlung der Antragskommission" als Status-Quelle definieren.

### 3. Text fehlt bei 45% der Anträge
**Ursache:** Zwei Quellen:
  - TOC-Einträge (Seite 3-4) werden als eigene Anträge extrahiert, haben aber keinen Text
  - Multi-Page-Anträge: Der Leitantrag (A01) erstreckt sich über 13 Seiten. Mistral erkennt die Folgeseiten als "0 Anträge" (korrekt), aber die Continuation-Logik greift nicht, weil auf Folgeseiten kein Kürzel genannt wird
**Fix:** 
  - TOC-Seiten erkennen und separat behandeln (Metadaten extrahieren, aber nicht als eigene Anträge zählen)
  - Continuation-Prompt verbessern: "Wenn diese Seite die Fortsetzung eines Antrags ist, gib das Kürzel des Antrags an"

### 4. Kürzel-Duplikate (TOC vs. Volltext)
**Ursache:** Anträge werden sowohl aus dem Inhaltsverzeichnis als auch aus dem Volltext extrahiert. Die merge_continuations-Logik matched nach Kürzel, aber TOC-Einträge haben oft leicht andere Kürzel-Formate ("Antrag Ar01" vs "Ar01").
**Fix:** Kürzel normalisieren ("Antrag " Prefix entfernen) vor dem Merge.

### 5. Mistral 503 Errors
**Häufigkeit:** 1/108 Seiten in diesem Run (mit Retry-Logik).
**Fix:** Bereits implementiert (exponential backoff). Akzeptabel.

## Nächste Schritte

1. **Prompt-Tuning:** Antragsteller + Status Extraktion verbessern
2. **TOC-Handling:** Seiten mit Inhaltsverzeichnis erkennen, nur Metadaten extrahieren
3. **Kürzel-Normalisierung:** "Antrag " Prefix konsistent entfernen
4. **Continuation-Verbesserung:** Folgeseiten dem vorherigen Antrag zuordnen
5. **Validierung:** Extrahierte Kürzel gegen TOC-Liste prüfen (Recall messen)

## Kosten

- 108 API Calls an Mistral Small
- ~50.000 Input-Tokens, ~30.000 Output-Tokens
- Geschätzte Kosten: ~$0.01 (Mistral Small Pricing)
