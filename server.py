# server.py
"""
Minimal MCP server in Python exposing BOTH transports:
- stdio (local)
- Streamable HTTP (remote)

Tested with: Python 3.11+
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
import re
import socket
import subprocess
from typing import List, Dict, Optional

from mcp.server.fastmcp import FastMCP  # Official Python SDK

# Name your server (what clients will see)
mcp = FastMCP("ryzen", stateless_http=True)


# ---- Tools -----------------------------------------------------------------
@mcp.tool()
def echo(text: str) -> str:
    """Return the same text back. Useful for wiring tests."""
    return text + " h1ello"


@mcp.tool()
def now(utc: bool = True) -> str:
    """Return current time (UTC by default) in ISO 8601."""
    dt = datetime.now(timezone.utc if utc else None)
    return dt.isoformat()


def _get_service_name(port: int, proto: str) -> Optional[str]:
    try:
        return socket.getservbyport(port, proto)
    except Exception:
        return None

def _parse_ss_line(line: str) -> Optional[Dict]:
    # Expected (with -H): Netid State Recv-Q Send-Q Local Address:Port Peer Address:Port Process
    # Split to max 6 fields to keep the 'Process' column intact even if it contains spaces.
    parts = line.split(None, 6)
    if len(parts) < 6:
        return None

    proto = parts[0]  # tcp/udp
    state = parts[1]
    local = parts[4]
    process_blob = parts[6] if len(parts) >= 7 else ""

    # Extract address and port from "IP:PORT" (IPv6 might be [::]:80 or [::ffff:127.0.0.1]:8080)
    port = None
    local_addr = local
    m = re.search(r':(\d+)$', local)
    if m:
        port = int(m.group(1))
        local_addr = local[: m.start()]

    # Extract process name and pid from users:(("proc",pid=123,fd=3),(...))
    proc_name = None
    pid = None
    m2 = re.search(r'users:\(\("([^"]+)"(?:,pid=(\d+))?', process_blob)
    if m2:
        proc_name = m2.group(1)
        if m2.lastindex and m2.group(2):
            pid = int(m2.group(2))

    return {
        "proto": proto.lower(),
        "port": port,
        "service": _get_service_name(port, proto.lower()) if port else None,
        "process": proc_name,
        "pid": pid,
        "state": state,
        "local_addr": local_addr,
    }

def _run_ss(tcp: bool, udp: bool) -> List[Dict]:
    results: List[Dict] = []
    cmds = []
    if tcp:
        cmds.append(["ss", "-H", "-lptn"])  # listening, process, tcp numeric
    if udp:
        cmds.append(["ss", "-H", "-lpnu"])  # listening, process, udp numeric

    for cmd in cmds:
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
        for line in out.strip().splitlines():
            item = _parse_ss_line(line.strip())
            if item and item.get("port"):
                results.append(item)
    return results

def _run_lsof(tcp: bool, udp: bool) -> List[Dict]:
    # lsof -nP -iTCP -sTCP:LISTEN  and lsof -nP -iUDP
    results: List[Dict] = []

    def parse_lsof(out: str, proto_hint: str) -> None:
        # Columns are variable; we’ll regex for COMMAND, PID, NODE (TCP/UDP), NAME (addr:port)
        for line in out.strip().splitlines():
            if line.startswith("COMMAND"):
                continue
            # Example NAME: *:22 (LISTEN)  or  0.0.0.0:53  or [::]:3000
            m = re.search(r'\s(\*|[\[\]0-9a-fA-F\.:]+):(\d+)', line)
            if not m:
                continue
            port = int(m.group(2))

            # Grab PID and COMMAND
            m_pid = re.search(r'\s(\d+)\s', line)  # first number after COMMAND is usually PID
            pid = int(m_pid.group(1)) if m_pid else None
            m_cmd = re.match(r'^(\S+)', line)
            cmd_name = m_cmd.group(1) if m_cmd else None

            results.append({
                "proto": proto_hint,
                "port": port,
                "service": _get_service_name(port, proto_hint),
                "process": cmd_name,
                "pid": pid,
                "state": "LISTEN",
                "local_addr": None,
            })

    if tcp:
        try:
            out = subprocess.check_output(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"], stderr=subprocess.STDOUT, text=True)
            parse_lsof(out, "tcp")
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass
    if udp:
        try:
            out = subprocess.check_output(["lsof", "-nP", "-iUDP"], stderr=subprocess.STDOUT, text=True)
            parse_lsof(out, "udp")
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass

    return results

def _dedupe(items: List[Dict]) -> List[Dict]:
    seen = set()
    deduped = []
    for it in items:
        key = (it.get("proto"), it.get("port"), it.get("pid"), it.get("process"))
        if key not in seen:
            seen.add(key)
            deduped.append(it)
    return deduped

@mcp.tool()
def list_open_ports(tcp: bool = True, udp: bool = True) -> List[Dict]:
    """
    List listening (open) ports and associated service/process using local system commands.
    Args:
      tcp (bool): include TCP listening sockets
      udp (bool): include UDP listening sockets
    Returns:
      List[Dict]: [{proto, port, service, process, pid, state, local_addr}]
    Notes:
      - Uses `ss` with -p to include process info; non-root users may see only their own processes.
      - Falls back to `lsof` if `ss` is unavailable or restricted.
      - Service is derived from /etc/services via socket.getservbyport and may be None for custom apps (e.g., port 3000).
    """
    data = _run_ss(tcp, udp)
    if not data:
        data = _run_lsof(tcp, udp)
    data = _dedupe(data)
    # nice sort: by proto, then port
    data.sort(key=lambda d: (d.get("proto") or "", d.get("port") or 0))
    return data

@mcp.prompt()
def check_port_service(port: int) -> str:
    """
    Check what service/process is running on a given port.
    Args:
      port (int): Port number to check
    Returns:
      A human-readable string describing what (if anything) is bound to that port.
    """

    # Reuse our open ports tool
    all_ports = list_open_ports()

    matches = [p for p in all_ports if p.get("port") == port]
    if not matches:
        return f"No process is currently listening on port {port}."

    lines = []
    for m in matches:
        proc = m.get("process") or "unknown"
        pid = m.get("pid") or "?"
        svc = m.get("service") or "unknown/custom"
        proto = m.get("proto") or "?"
        lines.append(
            f"Port {port}/{proto}: service '{svc}', process '{proc}' (pid {pid}), state {m.get('state')}"
        )

    return "\n".join(lines)

# ---- Resources (example: a simple in-memory resource) ----------------------
@mcp.resource("demo:readme")
def readme() -> str:
    """A tiny resource example clients can `read_resource` from."""
    return "Demo MCP server is up. Tools: echo, now. Resource: demo:readme"


# ---- Entrypoint ------------------------------------------------------------
if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio").lower()
    if transport == "http":
        # Streamable HTTP: the SDK serves an ASGI app, run with uvicorn
        import uvicorn

        host = os.getenv("HOST", "0.0.0.0")
        port = int(os.getenv("PORT", "3000"))
        uvicorn.run(mcp.streamable_http_app(), host=host, port=port)
    else:
        # STDIO (default). IMPORTANT: don't print to stdout.
        mcp.run()
