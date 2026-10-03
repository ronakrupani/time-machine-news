# Vercel entrypoint for the time-machine-news MCP server.
#
# This file will expose the MCP server over streamable HTTP at /mcp.
# vercel.json rewrites /mcp to this function, and Vercel's Python runtime
# loads the top-level ASGI `app` defined here. It will be built from the
# server in src/time_machine_news/server.py with MCPServer.streamable_http_app()
# (mcp 2.x renamed FastMCP to MCPServer), whose default route is already /mcp.
#
# No code yet.
