"""Gradio frontend for SPD Antragskorpus search.

Usage:
    python -m spdbe.app                          # local dev
    python -m spdbe.app --es-host http://localhost:9200  # custom ES
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import tempfile

import gradio as gr

from spdbe.haystack.document_store import DEFAULT_ES_HOST, DEFAULT_INDEX
from spdbe.haystack.pipelines.search import run_search

_config = {
    "es_host": os.environ.get("ES_HOST", DEFAULT_ES_HOST),
    "es_index": os.environ.get("ES_INDEX", DEFAULT_INDEX),
}

LANDESVERBAND_CHOICES = [
    ("Alle", ""),
    ("Berlin", "berlin"),
    ("Brandenburg", "brandenburg"),
    ("Hamburg", "hamburg"),
    ("Rheinland-Pfalz", "rlp"),
    ("Bayern", "bayern"),
    ("Schleswig-Holstein", "schleswig_holstein"),
    ("Bund", "bund"),
    ("Niedersachsen", "niedersachsen"),
    ("Thüringen", "thueringen"),
]

# Store last search results for export and detail view
_last_results: list[dict] = []


def _fetch_full_document(kuerzel: str) -> dict | None:
    """Fetch full Antrag text from ES by kuerzel (split_id=0 has text_md)."""
    from haystack_integrations.document_stores.elasticsearch import (
        ElasticsearchDocumentStore,
    )

    store = ElasticsearchDocumentStore(
        hosts=_config["es_host"],
        index=_config["es_index"],
    )
    # Use raw ES client to fetch by kuerzel + split_id=0
    resp = store._client.search(
        index=_config["es_index"],
        body={
            "query": {
                "bool": {
                    "must": [
                        {"term": {"kuerzel": kuerzel}},
                        {"term": {"split_id": 0}},
                    ]
                }
            },
            "size": 1,
            "_source": [
                "kuerzel", "title", "year", "status_raw", "submitter_raw",
                "landesverband", "text_md", "text_plain", "content",
                "source_url", "doc_type", "tags_raw", "ueberwiesen_an",
                "veranstaltung_raw",
            ],
        },
    )
    hits = resp["hits"]["hits"]
    if not hits:
        return None
    return hits[0]["_source"]


def search_corpus(
    query: str,
    landesverband: str,
    year_min: float | None,
    year_max: float | None,
    mode: str,
    top_k: int,
) -> list[list]:
    """Run hybrid search and return results as table rows."""
    global _last_results
    if not query.strip():
        _last_results = []
        return []

    results = run_search(
        query=query,
        es_host=_config["es_host"],
        index_name=_config["es_index"],
        top_k=int(top_k),
        landesverband=landesverband or None,
        year_min=int(year_min) if year_min else None,
        year_max=int(year_max) if year_max else None,
        mode=mode,
    )

    # Deduplicate by kuerzel (chunked docs produce duplicates)
    seen = set()
    deduped = []
    for r in results:
        k = r["kuerzel"]
        if k in seen:
            continue
        seen.add(k)
        deduped.append(r)

    _last_results = deduped

    rows = []
    for r in deduped:
        rows.append([
            r["score"],
            r["kuerzel"],
            r.get("year", ""),
            r["title"][:80],
            r.get("landesverband", ""),
            r.get("status", ""),
            r["snippet"][:200],
        ])
    return rows


def show_document(kuerzel: str) -> str:
    """Fetch and display full Antrag text."""
    if not kuerzel or not kuerzel.strip():
        return "*Kürzel eingeben und klicken.*"

    doc = _fetch_full_document(kuerzel.strip())
    if not doc:
        return f"*Kein Dokument gefunden für: {kuerzel}*"

    title = doc.get("title", "")
    year = doc.get("year", "")
    status = doc.get("status_raw", "")
    submitter = doc.get("submitter_raw", "")
    lv = doc.get("landesverband", "")
    source_url = doc.get("source_url", "")
    veranstaltung = doc.get("veranstaltung_raw", "")
    tags = doc.get("tags_raw", "")
    ueberwiesen = doc.get("ueberwiesen_an", "")
    text = doc.get("text_md", "") or doc.get("text_plain", "") or doc.get("content", "")

    # Build metadata header
    header = f"## {title}\n\n"
    header += f"**Kürzel:** {doc.get('kuerzel', '')}  \n"
    header += f"**Jahr:** {year}  \n"
    header += f"**Status:** {status}  \n"
    if submitter:
        header += f"**Antragsteller:** {submitter}  \n"
    if lv:
        header += f"**Landesverband:** {lv}  \n"
    if veranstaltung:
        header += f"**Veranstaltung:** {veranstaltung}  \n"
    if tags:
        tag_str = ", ".join(tags) if isinstance(tags, list) else str(tags)
        header += f"**Schlagworte:** {tag_str}  \n"
    if ueberwiesen:
        header += f"**Überwiesen an:** {ueberwiesen}  \n"
    if source_url:
        header += f"**Quelle:** [{source_url}]({source_url})  \n"
    header += "\n---\n\n"

    return header + text


def run_rag_query(
    query: str,
    landesverband: str,
) -> tuple[str, str]:
    """Run RAG query: search + Claude generation. Returns (answer, sources)."""
    if not query.strip():
        return "", ""

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return (
            "*ANTHROPIC_API_KEY nicht konfiguriert. RAG benötigt einen API-Schlüssel.*",
            "",
        )

    # Retrieve relevant documents
    results = run_search(
        query=query,
        es_host=_config["es_host"],
        index_name=_config["es_index"],
        top_k=10,
        landesverband=landesverband or None,
        mode="hybrid",
    )

    # Deduplicate
    seen = set()
    docs = []
    for r in results:
        k = r["kuerzel"]
        if k in seen:
            continue
        seen.add(k)
        docs.append(r)
        if len(docs) >= 5:
            break

    if not docs:
        return "*Keine relevanten Dokumente gefunden.*", ""

    # Fetch full document text for top results (much better than 300-char snippets)
    context_parts = []
    for d in docs:
        full_doc = _fetch_full_document(d["kuerzel"])
        text = ""
        if full_doc:
            text = full_doc.get("text_md", "") or full_doc.get("text_plain", "") or ""
            # Truncate very long documents to ~3000 chars each
            if len(text) > 3000:
                text = text[:3000] + "\n[...]"
        if not text:
            text = d["snippet"]

        context_parts.append(
            f"Kuerzel: {d['kuerzel']}\n"
            f"Jahr: {d.get('year', '?')}\n"
            f"Status: {d.get('status', '')}\n"
            f"Titel: {d['title']}\n\n"
            f"{text}"
        )
    context = "\n\n---\n\n".join(context_parts)

    prompt = (
        "Du bist ein Experte fuer SPD-Parteipolitik. Beantworte die Frage "
        "basierend ausschliesslich auf den folgenden Parteitagsantraegen.\n\n"
        f"{context}\n\n---\n\n"
        f"Frage: {query}\n\n"
        "Antworte praezise auf Deutsch und belege jede Aussage mit dem Kuerzel "
        "des Antrags in Klammern. Wenn die Antraege die Frage nicht beantworten, "
        "sage das klar."
    )

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )

    answer = response.content[0].text

    # Format sources
    source_lines = []
    for d in docs:
        status_str = f" ({d.get('status', '')})" if d.get("status") else ""
        source_lines.append(
            f"- **{d['kuerzel']}** ({d.get('year', '?')}){status_str}: "
            f"{d['title'][:60]}"
        )
    sources_md = "### Quellen\n\n" + "\n".join(source_lines)

    return answer, sources_md


def export_csv() -> str | None:
    """Export last search results to CSV file."""
    if not _last_results:
        return None

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8",
    )
    writer = csv.writer(tmp)
    writer.writerow(["Score", "Kuerzel", "Jahr", "Titel", "Landesverband", "Status", "Auszug"])
    for r in _last_results:
        writer.writerow([
            r["score"],
            r["kuerzel"],
            r.get("year", ""),
            r["title"],
            r.get("landesverband", ""),
            r.get("status", ""),
            r["snippet"][:300],
        ])
    tmp.close()
    return tmp.name


def build_app() -> gr.Blocks:
    """Build the Gradio Blocks app."""
    with gr.Blocks(
        title="SPD Antragskorpus",
    ) as app:
        # Set theme directly — Gradio v6 moved it from constructor to launch(),
        # but ASGI usage (no launch) still needs it for body_css in template
        app.theme = gr.themes.Soft(primary_hue="red")
        gr.Markdown(
            "# SPD Antragskorpus\n"
            "Durchsuche tausende SPD-Parteitagsanträge aus Berlin und weiteren "
            "Landesverbänden. Hybride Suche: BM25 + Embedding + Reciprocal Rank Fusion.\n\n"
            "*Datenquelle: [parteitag.spd.berlin](https://parteitag.spd.berlin/antragsverfolgung/)*"
        )

        # --- Tab 1: Suche ---
        with gr.Tab("Suche"):
            with gr.Row():
                query_input = gr.Textbox(
                    label="Suchbegriff",
                    placeholder="z.B. Mietpreisbremse, Digitalisierung, Klimaschutz...",
                    scale=3,
                )
                search_btn = gr.Button("Suchen", variant="primary", scale=1)

            with gr.Row():
                lv_dropdown = gr.Dropdown(
                    choices=LANDESVERBAND_CHOICES,
                    value="",
                    label="Landesverband",
                )
                year_min_input = gr.Number(
                    label="Jahr von",
                    value=None,
                    precision=0,
                )
                year_max_input = gr.Number(
                    label="Jahr bis",
                    value=None,
                    precision=0,
                )
                mode_dropdown = gr.Dropdown(
                    choices=["hybrid", "bm25", "vector"],
                    value="hybrid",
                    label="Suchmodus",
                )
                topk_slider = gr.Slider(
                    minimum=5,
                    maximum=50,
                    value=20,
                    step=5,
                    label="Ergebnisse",
                )

            results_table = gr.Dataframe(
                headers=["Score", "Kürzel", "Jahr", "Titel", "Land", "Status", "Auszug"],
                datatype=["number", "str", "str", "str", "str", "str", "str"],
                label="Ergebnisse",
                wrap=True,
            )

            with gr.Row():
                csv_btn = gr.Button("CSV herunterladen", size="sm")
                csv_output = gr.File(label="Download", visible=False)

            search_inputs = [
                query_input, lv_dropdown, year_min_input,
                year_max_input, mode_dropdown, topk_slider,
            ]
            search_btn.click(fn=search_corpus, inputs=search_inputs, outputs=results_table)
            query_input.submit(fn=search_corpus, inputs=search_inputs, outputs=results_table)
            csv_btn.click(fn=export_csv, outputs=csv_output).then(
                fn=lambda: gr.update(visible=True), outputs=csv_output,
            )

            # --- Document detail view ---
            gr.Markdown("---")
            with gr.Row():
                detail_kuerzel = gr.Textbox(
                    label="Antrag anzeigen",
                    placeholder="Kürzel aus den Ergebnissen eingeben, z.B. Antrag 134/I/2017",
                    scale=3,
                )
                detail_btn = gr.Button("Anzeigen", scale=1)

            detail_output = gr.Markdown(
                value="*Kürzel eingeben und klicken, um den vollständigen Antragstext zu sehen.*",
            )

            def on_row_select(evt: gr.SelectData):
                """When a row is clicked, extract kuerzel and show document."""
                if evt.index is not None and evt.value is not None:
                    # Column 1 is Kürzel
                    row_idx = evt.index[0] if isinstance(evt.index, (list, tuple)) else evt.index
                    if _last_results and row_idx < len(_last_results):
                        return _last_results[row_idx]["kuerzel"]
                return ""

            results_table.select(fn=on_row_select, outputs=detail_kuerzel).then(
                fn=show_document, inputs=detail_kuerzel, outputs=detail_output,
            )
            detail_btn.click(fn=show_document, inputs=detail_kuerzel, outputs=detail_output)
            detail_kuerzel.submit(fn=show_document, inputs=detail_kuerzel, outputs=detail_output)

        # --- Tab 2: Fragen (RAG) ---
        with gr.Tab("Fragen (RAG)"):
            gr.Markdown(
                "### Fragen an den Antragskorpus\n\n"
                "Stelle eine Frage und erhalte eine Antwort basierend auf den "
                "relevantesten Parteitagsanträgen. Jede Aussage wird mit dem "
                "Kürzel des Quell-Antrags belegt."
            )

            with gr.Row():
                rag_query = gr.Textbox(
                    label="Frage",
                    placeholder="z.B. Was hat die SPD Berlin zu Mieten beschlossen?",
                    scale=3,
                )
                rag_btn = gr.Button("Fragen", variant="primary", scale=1)

            rag_lv = gr.Dropdown(
                choices=LANDESVERBAND_CHOICES,
                value="",
                label="Landesverband (optional)",
            )

            rag_answer = gr.Markdown(label="Antwort")
            rag_sources = gr.Markdown(label="Quellen")

            rag_btn.click(
                fn=run_rag_query,
                inputs=[rag_query, rag_lv],
                outputs=[rag_answer, rag_sources],
            )
            rag_query.submit(
                fn=run_rag_query,
                inputs=[rag_query, rag_lv],
                outputs=[rag_answer, rag_sources],
            )

        # --- Tab 3: Info ---
        with gr.Tab("Info"):
            gr.Markdown(
                "## Über dieses Tool\n\n"
                "Dieses Tool durchsucht den SPD-Antragskorpus mit einer hybriden Suchpipeline:\n\n"
                "1. **BM25** (Schlüsselwortsuche) mit deutschem politischem Analyzer\n"
                "2. **Embedding-Suche** (semantisch) mit multilingual MiniLM\n"
                "3. **Reciprocal Rank Fusion** kombiniert beide Ergebnislisten\n\n"
                "### Datenumfang\n\n"
                "- 32.000+ Dokumente aus 5 Landesverbänden\n"
                "- Berlin, Brandenburg, Hamburg, Bayern, Rheinland-Pfalz\n"
                "- Weitere Landesverbände werden laufend ergänzt\n\n"
                "### Funktionen\n\n"
                "- **Suche**: Hybride Suche mit Filtern (Landesverband, Jahr, Modus)\n"
                "- **Dokumentansicht**: Vollständiger Antragstext per Kürzel\n"
                "- **Fragen (RAG)**: KI-gestützte Antworten mit Quellenbelegen\n"
                "- **CSV-Export**: Suchergebnisse herunterladen\n\n"
                "### Suchmodi\n\n"
                "- **hybrid**: Kombiniert BM25 + Embedding (empfohlen)\n"
                "- **bm25**: Nur Schlüsselwortsuche\n"
                "- **vector**: Nur semantische Ähnlichkeit\n\n"
                "---\n\n"
                "*Quellcode: [github.com/spd-antraege](https://github.com/spd-antraege/spd_antraege)*"
            )

    return app


def main():
    parser = argparse.ArgumentParser(description="SPD Antragskorpus Gradio frontend")
    parser.add_argument("--es-host", default=_config["es_host"], help="Elasticsearch host URL")
    parser.add_argument("--index", default=_config["es_index"], help="ES index name")
    parser.add_argument("--host", default="0.0.0.0", help="Server bind address")
    parser.add_argument("--port", type=int, default=7860, help="Server port")
    parser.add_argument("--share", action="store_true", help="Create public Gradio link")
    args = parser.parse_args()

    _config["es_host"] = args.es_host
    _config["es_index"] = args.index

    app = build_app()
    app.launch(
        server_name=args.host,
        server_port=args.port,
        share=args.share,
        theme=gr.themes.Soft(primary_hue="red"),
        css=".gradio-container { max-width: 1100px; margin: auto; }",
    )


if __name__ == "__main__":
    main()
