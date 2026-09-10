"""Run with repopilot-mcp --workspace /isolated/task --trust-code (optional).

Uses the official MCP SDK's stdio JSON-RPC transport and initialized client session.
"""

import argparse
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from .tools import ToolRouter


def create_server(workspace: Path, trust_code: bool = False) -> FastMCP:
    server = FastMCP("RepoPilot repository tools")
    router = ToolRouter(workspace, allow_repository_code=trust_code)

    @server.tool(name="repo.search", description="Bounded lexical search within this workspace")
    async def search(query: str) -> dict[str, Any]:
        return (await router.invoke("search_code", {"query": query})).model_dump()

    @server.tool(name="repo.read", description="Read a bounded range of a workspace text file")
    async def read(path: str, start_line: int = 1, line_count: int = 180) -> dict[str, Any]:
        return (
            await router.invoke(
                "read_file", {"path": path, "start_line": start_line, "line_count": line_count}
            )
        ).model_dump()

    @server.tool(name="tests.run", description="Run an approved test command in this workspace")
    async def tests(command: list[str], timeout: float = 30) -> dict[str, Any]:
        return (
            await router.invoke("run_tests", {"command": command, "timeout": timeout})
        ).model_dump()

    @server.tool(name="git.diff", description="Read the actual tracked and new-file workspace diff")
    async def diff() -> dict[str, Any]:
        return (await router.invoke("git_diff", {})).model_dump()

    return server


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--trust-code", action="store_true")
    args = parser.parse_args()
    if not args.workspace.resolve().is_dir():
        parser.error("Workspace must exist")
    create_server(args.workspace.resolve(), args.trust_code).run(transport="stdio")


if __name__ == "__main__":
    main()
