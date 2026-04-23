"""Combined ASGI server: Gradio + REST API + MCP Streamable HTTP.

Routes:
    /           → Gradio frontend
    /api/...    → FastAPI REST API
    /mcp/       → MCP Streamable HTTP (public, for any Claude Code)

Usage:
    uvicorn spdbe.server:app --host 0.0.0.0 --port 7860
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def create_app():
    """Build the combined ASGI application.

    Mount API and MCP onto Gradio's FastAPI app so Gradio handles
    its own lifecycle properly.
    """
    from spdbe.api import api as fastapi_app
    from spdbe.app import build_app as build_gradio
    from spdbe.mcp_http import mcp_asgi

    gradio_blocks = build_gradio()
    # Gradio v6 requires queue() before using as ASGI app
    gradio_blocks.queue()
    gradio_fastapi = gradio_blocks.app

    gradio_fastapi.mount("/api", fastapi_app)
    gradio_fastapi.mount("/mcp", mcp_asgi)

    return gradio_blocks


blocks = create_app()
app = blocks.app
