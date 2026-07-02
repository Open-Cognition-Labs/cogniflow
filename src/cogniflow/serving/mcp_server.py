"""MCP serving surface for the context API (A.3 T4) - the primary "any model calls it" path.

Exposes a single read-only ``get_context`` tool so any MCP-aware client (Claude Desktop,
Cursor, an agent framework) pulls temporally-correct, auditable context with zero custom
integration. Behind the ``[mcp]`` extra. Self-hostable over stdio - it runs in the caller's
environment, so their data never leaves.

The tool returns the G1 context contract (facts + validity + provenance + valid_at_source +
as_of), never a generated answer. The consuming model does the generation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..context import serve_context
from ..core.contracts import AsyncSubstrate
from ..generation import generate_answer

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as e: # pragma: no cover
    raise RuntimeError(
        "The MCP serving surface needs the 'mcp' extra: pip install 'cogniflow-rag[mcp]'"
    ) from e


def build_mcp_server(
    substrate: AsyncSubstrate,
    generator: Any | None = None,
    *,
    name: str = "cogniflow-context",
) -> FastMCP:
    """Build an MCP server exposing the read-only context tool over ``substrate``. If a
    ``generator`` is provided, a ``get_answer`` tool (answer out) is exposed alongside
    ``get_context`` (context out), so an agent can ask for context or a cited answer."""
    server = FastMCP(name)

    @server.tool()
    async def get_context(
        query: str,
        as_of: str | None = None,
        top_k: int = 5,
        include_expired: bool = False,
    ) -> dict[str, Any]:
        """Retrieve temporally-correct context (facts, not an answer).

        Args:
            query: the question to gather context for.
            as_of: optional ISO-8601 timestamp; context is resolved as of this instant
                (the temporal axis). Omit for "now".
            top_k: max facts to return.
            include_expired: include facts that have been superseded (for audit/why-changed).
        """
        parsed = datetime.fromisoformat(as_of) if as_of else None
        response = await serve_context(
            substrate,
            query,
            as_of=parsed,
            top_k=top_k,
            include_expired=include_expired,
        )
        return response.to_dict()

    if generator is not None:

        @server.tool()
        async def get_answer(
            query: str,
            as_of: str | None = None,
            top_k: int = 5,
            include_expired: bool = False,
        ) -> dict[str, Any]:
            """Answer a question from temporally-correct context (a cited answer, as of the
            given instant), un-knowing what the context un-knows. Carries the facts, their
            valid_at_source confidence, and provenance the answer was built from.

            Args:
                query: the question to answer.
                as_of: optional ISO-8601 timestamp; the answer is resolved as of this instant.
                top_k: max facts to ground the answer in.
                include_expired: include superseded facts (for why-changed answers).
            """
            parsed = datetime.fromisoformat(as_of) if as_of else None
            result = await generate_answer(
                substrate,
                query,
                generator,
                as_of=parsed,
                top_k=top_k,
                include_expired=include_expired,
            )
            return result.to_dict()

    return server
