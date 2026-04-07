"""
MCP (Model Context Protocol) client integration.

Loads MCP server configs and wraps their tools as LangChain tools
so agents can use them transparently.
"""

import json
import os
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool, tool
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


MCP_CONFIG_PATH = Path(__file__).parent.parent.parent / "mcp_config.json"


def load_mcp_config() -> dict:
    if not MCP_CONFIG_PATH.exists():
        return {"servers": {}}
    with open(MCP_CONFIG_PATH) as f:
        return json.load(f)


async def get_mcp_tools(server_name: str) -> list[BaseTool]:
    """Connect to a named MCP server and return its tools as LangChain tools."""
    config = load_mcp_config()
    server_cfg = config.get("servers", {}).get(server_name)
    if not server_cfg:
        return []

    server_params = StdioServerParameters(
        command=server_cfg["command"],
        args=server_cfg.get("args", []),
        env=server_cfg.get("env", {}),
    )

    tools = []
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            mcp_tools = await session.list_tools()
            for mcp_tool in mcp_tools.tools:
                tools.append(_wrap_mcp_tool(session, mcp_tool))
    return tools


def _wrap_mcp_tool(session: Any, mcp_tool: Any) -> BaseTool:
    """Wrap an MCP tool as a LangChain BaseTool."""
    tool_name = mcp_tool.name
    tool_desc = mcp_tool.description or ""

    @tool(tool_name, description=tool_desc)
    async def _tool(**kwargs) -> str:
        result = await session.call_tool(tool_name, kwargs)
        return str(result.content)

    return _tool
