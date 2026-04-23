"""MCP server with Streamable HTTP transport for public access.

Anyone can connect their Claude Code with:

    {"mcpServers": {"spd-antraege": {"type": "url", "url": "https://spd-antraege.de/mcp/"}}}
"""

from __future__ import annotations

import asyncio
import logging

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

logger = logging.getLogger(__name__)

_session_manager: StreamableHTTPSessionManager | None = None
_started = False


def get_session_manager() -> StreamableHTTPSessionManager:
    global _session_manager
    if _session_manager is None:
        from spdbe.mcp_server import app as mcp_server
        _session_manager = StreamableHTTPSessionManager(
            app=mcp_server,
            stateless=True,
            json_response=False,
        )
    return _session_manager


async def mcp_asgi(scope, receive, send):
    """ASGI handler for MCP. Starts session manager on first call."""
    global _started
    manager = get_session_manager()

    if not _started:
        # Enter the run() context — this starts the task group
        manager._run_ctx = manager.run()
        await manager._run_ctx.__aenter__()
        _started = True
        logger.info("MCP session manager started")

    await manager.handle_request(scope, receive, send)
