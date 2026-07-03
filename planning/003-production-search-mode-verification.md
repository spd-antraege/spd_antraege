# Production Search Mode Verification

## Context

Commit `fc19963` split search execution into mode-specific pipeline shapes:

- `bm25`: BM25-only pipeline.
- `vector`: vector-only pipeline.
- `hybrid`: BM25 + vector + RRF pipeline.

This was deployed to production on 2026-07-03 by pulling `origin/main` on `pis-vm` and restarting `spd-antraege-app.service`.

## Verification

Production service state:

- Service: `active`
- Deployed commit: `fc19963`
- Health endpoint: `{"status":"ok","documents":48154}`

Direct public API checks returned HTTP 200 for:

- `/api/search?q=Mietpreisbremse&top_k=3&mode=bm25`
- `/api/search?q=Mietpreisbremse&top_k=3&mode=vector`
- `/api/search?q=Mietpreisbremse&top_k=3&mode=hybrid`

Full retrieval eval against production completed with zero mode failures:

| Mode | Failure | Recall@5 | Recall@10 | MRR | Irrelevant hits | Negative false positives |
|---|---:|---:|---:|---:|---:|---:|
| bm25 | 0.0% | 73.3% | 76.7% | 0.666 | 77.9% | 100.0% |
| vector | 0.0% | 63.3% | 63.3% | 0.490 | 81.2% | 100.0% |
| hybrid | 0.0% | 73.3% | 76.7% | 0.642 | 77.1% | 100.0% |
| hybrid_with_filters | 0.0% | 93.3% | 93.3% | 0.867 | 63.0% | 100.0% |

## Result

The search mode availability bug is fixed in production. `bm25` and `vector` no longer return HTTP 500.

The remaining issue is retrieval quality and response discipline:

- Negative cases still return results in every mode.
- Irrelevant-hit rates remain high.
- Filtered hybrid is materially better than unfiltered hybrid.

## Next

The next implementation unit should add `/api/rag` retrieval controls and a relevance gate so weak retrieval does not produce confident generated answers.
