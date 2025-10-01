
export MCP_TRANSPORT=http HOST=0.0.0.0 PORT=3000
python server.py
# internally calls: uvicorn.run(mcp.streamable_http_app(), host=HOST, port=PORT)

python server.py → stdio mode.

