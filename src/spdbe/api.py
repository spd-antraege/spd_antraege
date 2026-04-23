"""REST API for SPD Antragskorpus.

Endpoints:
    GET  /api/search?q=...&landesverband=...&year_min=...&year_max=...&top_k=...&mode=...
    GET  /api/motion/{kuerzel}
    POST /api/rag  {query, landesverband?}
    GET  /api/states
    GET  /api/health
"""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from spdbe.haystack.document_store import DEFAULT_ES_HOST, DEFAULT_INDEX
from spdbe.haystack.pipelines.search import run_search

api = FastAPI(
    title="SPD Antragskorpus API",
    version="1.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
)

_es_host = os.environ.get("ES_HOST", DEFAULT_ES_HOST)
_es_index = os.environ.get("ES_INDEX", DEFAULT_INDEX)


def _get_es_client():
    """Get a raw Elasticsearch client for direct queries."""
    from elasticsearch import Elasticsearch
    return Elasticsearch(hosts=_es_host)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class SearchResult(BaseModel):
    doc_id: str
    score: float
    kuerzel: str
    title: str
    year: int | None
    status: str
    submitter_type: str
    landesverband: str
    snippet: str


class MotionDetail(BaseModel):
    kuerzel: str
    title: str
    year: int | None
    status: str | None
    submitter: str | None
    landesverband: str | None
    veranstaltung: str | None
    tags: list[str] | str | None
    text: str | None


class RAGRequest(BaseModel):
    query: str
    landesverband: str | None = None


class RAGResponse(BaseModel):
    answer: str
    sources: list[dict]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@api.get("/health")
async def health():
    try:
        es = _get_es_client()
        count = es.count(index=_es_index)["count"]
        return {"status": "ok", "documents": count}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@api.get("/states")
async def list_states():
    """List available Landesverbände with document counts."""
    es = _get_es_client()
    resp = es.search(
        index=_es_index,
        body={
            "size": 0,
            "aggs": {
                "states": {
                    "terms": {"field": "landesverband", "size": 50}
                }
            },
        },
    )
    buckets = resp["aggregations"]["states"]["buckets"]
    return [{"landesverband": b["key"], "count": b["doc_count"]} for b in buckets]


@api.get("/search", response_model=list[SearchResult])
async def search(
    q: Annotated[str, Query(min_length=1, description="Search query")],
    landesverband: str | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    top_k: int = 20,
    mode: str = "hybrid",
):
    """Search the SPD Antragskorpus with hybrid BM25 + embedding retrieval."""
    if mode not in ("hybrid", "bm25", "vector"):
        raise HTTPException(400, "mode must be hybrid, bm25, or vector")
    if top_k < 1 or top_k > 100:
        raise HTTPException(400, "top_k must be 1-100")

    results = run_search(
        query=q,
        es_host=_es_host,
        index_name=_es_index,
        top_k=top_k,
        landesverband=landesverband or None,
        year_min=year_min,
        year_max=year_max,
        mode=mode,
    )
    return results


@api.get("/motion/{kuerzel:path}", response_model=MotionDetail)
async def get_motion(kuerzel: str):
    """Get full text and metadata for a single motion by Kürzel."""
    es = _get_es_client()
    resp = es.search(
        index=_es_index,
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
                "veranstaltung_raw", "tags_raw",
            ],
        },
    )
    hits = resp["hits"]["hits"]
    if not hits:
        raise HTTPException(404, f"Motion not found: {kuerzel}")

    src = hits[0]["_source"]
    return MotionDetail(
        kuerzel=src.get("kuerzel", kuerzel),
        title=src.get("title", ""),
        year=src.get("year"),
        status=src.get("status_raw"),
        submitter=src.get("submitter_raw"),
        landesverband=src.get("landesverband"),
        veranstaltung=src.get("veranstaltung_raw"),
        tags=src.get("tags_raw"),
        text=src.get("text_md") or src.get("text_plain") or src.get("content"),
    )


@api.post("/rag", response_model=RAGResponse)
async def rag_query(req: RAGRequest):
    """Ask a question answered from the Antragskorpus with source citations."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise HTTPException(503, "ANTHROPIC_API_KEY not configured")

    results = run_search(
        query=req.query,
        es_host=_es_host,
        index_name=_es_index,
        top_k=10,
        landesverband=req.landesverband,
        mode="hybrid",
    )

    # Dedup and take top 5
    seen: set[str] = set()
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
        return RAGResponse(answer="Keine relevanten Dokumente gefunden.", sources=[])

    # Fetch full text for context
    es = _get_es_client()
    context_parts = []
    for d in docs:
        resp = es.search(
            index=_es_index,
            body={
                "query": {"bool": {"must": [
                    {"term": {"kuerzel": d["kuerzel"]}},
                    {"term": {"split_id": 0}},
                ]}},
                "size": 1,
                "_source": ["text_md", "text_plain", "content"],
            },
        )
        hits = resp["hits"]["hits"]
        text = ""
        if hits:
            src = hits[0]["_source"]
            text = src.get("text_md") or src.get("text_plain") or src.get("content", "")
        if not text:
            text = d["snippet"]
        if len(text) > 3000:
            text = text[:3000] + "\n[...]"

        context_parts.append(
            f"Kuerzel: {d['kuerzel']}\nJahr: {d.get('year', '?')}\n"
            f"Status: {d.get('status', '')}\nTitel: {d['title']}\n\n{text}"
        )

    context = "\n\n---\n\n".join(context_parts)
    prompt = (
        "Du bist ein Experte fuer SPD-Parteipolitik. Beantworte die Frage "
        "basierend ausschliesslich auf den folgenden Parteitagsantraegen.\n\n"
        f"{context}\n\n---\n\nFrage: {req.query}\n\n"
        "Antworte praezise auf Deutsch und belege jede Aussage mit dem Kuerzel "
        "des Antrags in Klammern."
    )

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )

    sources = [
        {"kuerzel": d["kuerzel"], "year": d.get("year"), "title": d["title"],
         "status": d.get("status", "")}
        for d in docs
    ]

    return RAGResponse(answer=response.content[0].text, sources=sources)
