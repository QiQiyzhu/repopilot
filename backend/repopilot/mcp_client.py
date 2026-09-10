from __future__ import annotations

import json
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .models import ToolResult
from .security import child_environment


class MCPTools:
    def __init__(self, session: ClientSession):
        self.session = session

    async def invoke(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        result = await self.session.call_tool(name, arguments)
        if result.isError:
            return ToolResult(
                ok=False,
                error="MCP tool error",
                output="\n".join(getattr(c, "text", "") for c in result.content)[:16000],
            )
        structured = getattr(result, "structuredContent", None)
        if structured:
            return ToolResult.model_validate(structured)
        text = "".join(getattr(c, "text", "") for c in result.content)
        return ToolResult.model_validate(json.loads(text))


@asynccontextmanager
async def connect_mcp(root: Path, trust_code: bool) -> AsyncIterator[MCPTools]:
    args = ["-m", "repopilot.mcp_server", "--workspace", str(root)]
    if trust_code:
        args.append("--trust-code")
    params = StdioServerParameters(command=sys.executable, args=args, env=child_environment())
    async with stdio_client(params) as (reader, writer), ClientSession(reader, writer) as session:
        await session.initialize()
        yield MCPTools(session)
