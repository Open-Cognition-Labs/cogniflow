"""Serving surfaces for the context API (A.3 T4): MCP first, HTTP underneath.

Both are read-only and self-hostable - they run in the caller's environment, so their data
never leaves. Each is behind an optional extra (``[serve]`` for HTTP, ``[mcp]`` for MCP) so
the core library carries no web/agent framework dependency.
"""

from __future__ import annotations

__all__ = ["create_app", "build_mcp_server", "create_audit_app"]


def __getattr__(name: str): # lazy: importing serving must not require the optional extras
    if name == "create_app":
        from .http import create_app

        return create_app
    if name == "build_mcp_server":
        from .mcp_server import build_mcp_server

        return build_mcp_server
    if name == "create_audit_app":
        from .audit import create_audit_app

        return create_audit_app
    raise AttributeError(name)
