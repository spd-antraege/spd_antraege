"""Combined ASGI server: Astro static frontend + REST API + MCP Streamable HTTP.

Routes:
    /           → Astro static frontend (from frontend/dist/)
    /api/...    → FastAPI REST API
    /mcp/       → MCP Streamable HTTP (public, for any Claude Code)

Usage:
    uvicorn spdbe.server:app --host 0.0.0.0 --port 7860
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

# Static frontend build directory
FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


def create_app() -> FastAPI:
    """Build the combined ASGI application."""
    from spdbe.api import api as api_app
    from spdbe.mcp_http import mcp_asgi

    main_app = FastAPI(title="SPD Antragskorpus", docs_url=None, openapi_url=None)

    main_app.mount("/api", api_app)
    main_app.mount("/mcp", mcp_asgi)

    if FRONTEND_DIST.is_dir():
        main_app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True))
    else:
        logger.warning("Frontend dist not found at %s — serving API only", FRONTEND_DIST)

    return main_app


app = create_app()
