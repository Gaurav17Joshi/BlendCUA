"""The MCP server Claude Code talks to: B2's tools, forwarded to the agent process.

Claude Code launches this over stdio (--mcp-config). It owns no state: every
tool call is forwarded to agent_claude.py's RPC port, where the same
Agent.dispatch() that serves the OpenAI baselines runs it against the live
Blender. So the Claude run and the other bake-off runs reach Blender, the host
and the skill library through exactly the same code.

    B2_RPC_PORT   the agent's RPC port
    B2_TOOLSET    "build" (7 tools) or "review" (4 tools)

Speaks MCP over newline-delimited JSON-RPC on stdin/stdout; nothing may be
printed to stdout except protocol messages (diagnostics go to stderr).
"""
from __future__ import annotations

import json
import os
import socket
import struct
import sys

RPC_PORT = int(os.environ["B2_RPC_PORT"])
TOOLSET = os.environ.get("B2_TOOLSET", "build")
PROTOCOL = "2024-11-05"

STR = {"type": "string"}
INT = {"type": "integer"}


def _tool(name, desc, props, required):
    return {"name": name, "description": desc,
            "inputSchema": {"type": "object", "properties": props, "required": required}}


BUILD_TOOLS = [
    _tool("run_python",
          "Execute Python inside the live Blender GUI session (bpy), on Blender's main thread. "
          "Returns everything the code printed plus any traceback. The namespace persists "
          "between calls, like a REPL. The code runs from a timer, so there is no active "
          "3D-view context: operators needing one must run inside bpy.context.temp_override(). "
          "Raise timeout_s for renders and bakes.",
          {"code": STR, "timeout_s": dict(INT, description="seconds, default 600, max 2400")},
          ["code"]),
    _tool("screenshot", "Capture the Blender GUI's 3D viewport and show it to you as an image.",
          {}, []),
    _tool("view_image", "Show you an image file (absolute path): a render, a reference plate, "
          "a generated image.", {"path": STR}, ["path"]),
    _tool("host_python",
          "Run Python 3.12 in a separate process on the host machine (numpy, scipy and Pillow "
          "installed; cwd is your work folder). For image analysis and file work that does not "
          "need Blender. Returns stdout/stderr.",
          {"code": STR, "timeout_s": dict(INT, description="seconds, default 300, max 1800")},
          ["code"]),
    _tool("generate_image",
          "Generate or edit an image with the gpt-image-2 image model and save it as PNG. With "
          "input_images it edits/derives from those images. Takes up to about 2 minutes.",
          {"prompt": STR, "output_path": dict(STR, description="absolute .png path in the work folder"),
           "input_images": {"type": "array", "items": STR,
                            "description": "absolute paths of images to edit/derive from"},
           "size": {"type": "string", "enum": ["1024x1024", "1536x1024", "1024x1536", "auto"]},
           "background": {"type": "string", "enum": ["auto", "opaque", "transparent"]},
           "quality": {"type": "string", "enum": ["low", "medium", "high", "auto"]}},
          ["prompt", "output_path"]),
    _tool("load_skill", "Show the full documentation and code of a skill in your skill library.",
          {"name": STR}, ["name"]),
    _tool("finish",
          "Call when the scene is complete; the live scene is then saved as the deliverable. "
          "The FIRST call hands the scene to an independent reviewer and returns its review to "
          "you -- it may take several minutes -- after which you get one more pass. Your SECOND "
          "call is final.",
          {"summary": STR}, ["summary"]),
]

REVIEW_TOOLS = [t for t in BUILD_TOOLS if t["name"] in ("run_python", "screenshot", "view_image")] + [
    _tool("submit_review", "Hand your review to the builder. This ends your turn.",
          {"review": STR}, ["review"]),
]

TOOLS = BUILD_TOOLS if TOOLSET == "build" else REVIEW_TOOLS
if os.environ.get("B2_NO_LIBRARY"):   # the no-library ablation: nothing to load from
    TOOLS = [t for t in TOOLS if t["name"] != "load_skill"]


def rpc(payload: dict) -> dict:
    """One call to the agent process. Blocking, no timeout: the agent owns the caps."""
    data = json.dumps(payload).encode("utf-8")
    s = socket.create_connection(("127.0.0.1", RPC_PORT))
    try:
        s.settimeout(None)
        s.sendall(struct.pack(">Q", len(data)) + data)
        head = b""
        while len(head) < 8:
            chunk = s.recv(8 - len(head))
            if not chunk:
                raise ConnectionError("agent closed the connection")
            head += chunk
        (n,) = struct.unpack(">Q", head)
        buf = b""
        while len(buf) < n:
            chunk = s.recv(min(65536, n - len(buf)))
            if not chunk:
                raise ConnectionError("agent closed the connection mid-reply")
            buf += chunk
        return json.loads(buf.decode("utf-8"))
    finally:
        s.close()


def call_tool(name: str, args: dict) -> dict:
    try:
        r = rpc({"tool": name, "args": args})
    except Exception as e:  # noqa: BLE001
        return {"content": [{"type": "text", "text": f"harness RPC failed: {type(e).__name__}: {e}"}],
                "isError": True}
    content = [{"type": "text", "text": r.get("text", "")}]
    for im in r.get("images", []):
        content.append({"type": "image", "data": im["data"], "mimeType": im["mime"]})
    return {"content": content, "isError": bool(r.get("is_error"))}


def send(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def main() -> None:
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method, mid = msg.get("method"), msg.get("id")
        if mid is None:          # a notification: never answered
            continue
        if method == "initialize":
            ver = (msg.get("params") or {}).get("protocolVersion") or PROTOCOL
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": ver, "capabilities": {"tools": {}},
                "serverInfo": {"name": "b2", "version": "1.0.0"}}})
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            p = msg.get("params") or {}
            send({"jsonrpc": "2.0", "id": mid,
                  "result": call_tool(p.get("name", ""), p.get("arguments") or {})})
        elif method == "ping":
            send({"jsonrpc": "2.0", "id": mid, "result": {}})
        else:
            send({"jsonrpc": "2.0", "id": mid,
                  "error": {"code": -32601, "message": f"method not found: {method}"}})


if __name__ == "__main__":
    main()
