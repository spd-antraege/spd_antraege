# SPD Antraege — Project Rules

## Commit

`type(scope): description` — types: feat, fix, docs, refactor, chore

## Architecture

- **Backend**: FastAPI (API + static file server) + MCP, served by uvicorn
- **Frontend**: Astro + React + Tailwind + shadcn/ui — static build in `frontend/dist/`
- **Search**: Haystack v2 pipelines with Elasticsearch (BM25 + vector + RRF)
- **Secrets**: Doppler (`andx_main/prd`), never hardcode

## Development

```bash
# Backend
.venv/bin/uvicorn spdbe.server:app --reload --port 7860

# Frontend
cd frontend && npm run dev
```

## Deploy

```bash
git push origin main
ssh pis-vm "cd /opt/pis && git pull origin main && systemctl restart spd-antraege-app.service"
# If frontend changed, also build on server or rsync dist/
```

## Testing

```bash
pytest                                    # unit tests
pytest -m integration                     # needs ES running
pytest -m contract                        # needs ANTHROPIC_API_KEY
```
