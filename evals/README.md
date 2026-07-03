# Evals

This directory contains two separate eval tracks:

- `run.py`: extraction quality against cached fixture documents.
- `run_retrieval.py`: retrieval quality for search and RAG source selection.

## Retrieval Eval

The retrieval eval uses `retrieval_questions.yaml` and scores search results before answer generation.

Run against production:

```bash
python -m evals.run_retrieval --backend api --base-url https://spd-antraege.de
```

Run against local Elasticsearch:

```bash
python -m evals.run_retrieval --backend local-haystack --es-host http://localhost:9200
```

Run against checked-in local parquet fallback data:

```bash
python -m evals.run_retrieval --backend local-federated --data-dir data --modes bm25
```

`local-federated` is intentionally BM25-only for offline runs. Use the API or a local Elasticsearch backend for vector and hybrid mode comparisons.

Metrics are calculated after deduplicating chunks by motion:

- Recall@5
- Recall@10
- MRR
- Irrelevant-hit rate
- No-result rate
- Mode failure rate

Generated reports are written to `evals/reports/` and ignored by git.
