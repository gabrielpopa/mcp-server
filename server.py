"""
Minimal MCP server exposing a simple Notes system via tools.
- Transports: stdio (default) and streamable HTTP (uvicorn)
- Python: 3.11+

Tools:
1) list_notes() -> List of {id, title, created_at, updated_at}
2) read_notes(ids: Optional[List[str]] = None, all: bool = False) -> List of full notes
3) add_note(title: str, body: str) -> Created note {id, title, body, created_at, updated_at}

Notes are persisted to a JSON file for durability.
Set NOTES_PATH env var to customize the store location (default: ./notes.json).
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

from mcp.server.fastmcp import FastMCP

ISO = "%Y-%m-%dT%H:%M:%S.%fZ"


# ------------------------------- Data Model ---------------------------------
@dataclass
class Note:
    id: str
    title: str
    body: str
    created_at: str
    updated_at: str


class NoteStore:
    def __init__(self, path: str):
        self._path = path
        self._lock = threading.RLock()
        self._notes: Dict[str, Note] = {}
        self._load()

    def _load(self) -> None:
        with self._lock:
            if not os.path.exists(self._path):
                self._notes = {}
                return
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                self._notes = {n["id"]: Note(**n) for n in raw}
            except Exception:
                # Corrupt or empty file -> start clean but keep the file so we don't overwrite unintentionally.
                self._notes = {}

    def _save(self) -> None:
        with self._lock:
            tmp = self._path + ".tmp"
            data = [asdict(n) for n in self._notes.values()]
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path)

    def list(self) -> List[Note]:
        with self._lock:
            # Return sorted by updated_at desc
            return sorted(self._notes.values(), key=lambda n: n.updated_at, reverse=True)

    def get_many(self, ids: Optional[List[str]] = None) -> List[Note]:
        with self._lock:
            if ids is None:
                return list(self._notes.values())
            out: List[Note] = []
            for i in ids:
                n = self._notes.get(i)
                if n:
                    out.append(n)
            return out

    def add(self, title: str, body: str) -> Note:
        now = datetime.now(timezone.utc).strftime(ISO)
        note = Note(id=str(uuid.uuid4()), title=title.strip(), body=body, created_at=now, updated_at=now)
        with self._lock:
            self._notes[note.id] = note
            self._save()
        return note

    def touch(self, note_id: str) -> Optional[Note]:
        with self._lock:
            n = self._notes.get(note_id)
            if not n:
                return None
            n.updated_at = datetime.now(timezone.utc).strftime(ISO)
            self._save()
            return n


# ----------------------------- MCP Server -----------------------------------
NOTES_PATH = os.getenv("NOTES_PATH", os.path.abspath("./notes.json"))
store = NoteStore(NOTES_PATH)

# Name your server (what clients will see)
mcp = FastMCP("mcp-notes", stateless_http=True)


# ---- Tools ------------------------------------------------------------------
@mcp.tool()
def list_notes() -> List[Dict[str, str]]:
    """List notes with minimal metadata.

    Returns a list of dicts: {id, title, created_at, updated_at} sorted by updated_at desc.
    """
    return [
        {
            "id": n.id,
            "title": n.title,
            "created_at": n.created_at,
            "updated_at": n.updated_at,
        }
        for n in store.list()
    ]


@mcp.tool()
def read_notes(ids: Optional[List[str]] = None, all: bool = False) -> List[Dict[str, str]]:
    """Read notes by ID or read all when `all=True`.

    Args:
        ids: Optional list of note IDs to read. Ignored when `all=True`.
        all: When True, returns every note in the store.

    Returns:
        List of full notes: {id, title, body, created_at, updated_at}
    """
    sel: List[Note]
    if all:
        sel = store.get_many(None)
    else:
        sel = store.get_many(ids or [])
    return [asdict(n) for n in sel]


@mcp.tool()
def add_note(title: str, body: str) -> Dict[str, str]:
    """Insert a new note with title and body and return the created note.

    Title and body are trimmed minimally; UUIDv4 is used for the note id.
    """
    if not title or not title.strip():
        raise ValueError("title is required")
    note = store.add(title=title, body=body or "")
    return asdict(note)


# ---- Entrypoint -------------------------------------------------------------
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
