import asyncio

from forge.mcp_server import PUBLIC_TOOLS, mcp


def test_public_surface_is_exactly_five_tools():
    tools = asyncio.run(mcp.list_tools())
    assert {tool.name for tool in tools} == set(PUBLIC_TOOLS)

