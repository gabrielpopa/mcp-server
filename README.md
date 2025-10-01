
# Local Server MCP

This project provides a local server for MCP (Modular Communication Protocol) using Python.

## Getting Started

To run the server with HTTP transport:

```bash
export MCP_TRANSPORT=http
export HOST=0.0.0.0
export PORT=3000
python server.py
```

Internally, this will call:

```python
uvicorn.run(mcp.streamable_http_app(), host=HOST, port=PORT)
```

To run the server in stdio mode:

```bash
python server.py
```

## Features

- Supports HTTP and stdio transport modes
- Configurable host and port
- Easy to run and extend

## Requirements

- Python 3.7+
- Uvicorn
- Any other dependencies listed in `requirements.txt`

## License

See `LICENSE` for details.


