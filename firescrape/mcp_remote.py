#!/usr/bin/env python3
"""
FireScrape Remote MCP Server — connects to FireScrape API on remote server.
No local browser needed. Just HTTP calls to the remote service.

Register in Claude Code:
  claude mcp add firescrape-remote -- python firescrape/mcp_remote.py

Set API_BASE via env var or edit the default below:
  export FIRESCRAPE_API=https://your-server.example.com
"""

import json
import os
import sys
import urllib.request

API_BASE = os.environ.get("FIRESCRAPE_API", "http://localhost:5003")

SERVER_INFO = {"name": "firescrape-remote", "version": "1.0.0"}

TOOLS = [
    {
        "name": "firescrape_scrape",
        "description": "Scrape any URL and get clean markdown. Runs on remote server with Playwright browser. Free, no limits.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to scrape"},
                "formats": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["markdown", "html", "links"]},
                    "description": "Output formats (default: ['markdown'])",
                },
                "onlyMainContent": {"type": "boolean", "description": "Extract main content only (default: true)"},
                "noCache": {"type": "boolean", "description": "Skip cache"},
                "waitFor": {"type": "string", "description": "CSS selector to wait for"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "firescrape_batch",
        "description": "Scrape multiple URLs in parallel on remote server.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "urls": {"type": "array", "items": {"type": "string"}, "description": "URLs to scrape"},
                "formats": {"type": "array", "items": {"type": "string"}},
                "onlyMainContent": {"type": "boolean"},
            },
            "required": ["urls"],
        },
    },
]


def api_call(endpoint, data):
    """Call FireScrape API."""
    payload = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        f"{API_BASE}{endpoint}",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def handle_scrape(args):
    result = api_call("/scrape", args)
    parts = []
    if result.get("success"):
        title = result.get("metadata", {}).get("title", "")
        if title:
            parts.append(f"**{title}**\n")
        if "markdown" in result:
            md = result["markdown"]
            if len(md) > 50000:
                md = md[:50000] + f"\n\n...(truncated, {len(result['markdown'])} total)"
            parts.append(md)
        if "links" in result:
            links = result["links"][:30]
            parts.append(f"\n**Links ({len(result['links'])} total):**")
            for l in links:
                parts.append(f"- [{l['text'][:60]}]({l['url']})")
    else:
        parts.append(f"Error: {result.get('error', 'unknown')}")
    return "\n".join(parts)


def handle_batch(args):
    result = api_call("/batch", args)
    results = result.get("results", [])
    urls = args.get("urls", [])
    parts = []
    for i, r in enumerate(results):
        url = urls[i] if i < len(urls) else "?"
        if r.get("success"):
            title = r.get("metadata", {}).get("title", url)
            md = r.get("markdown", "")[:10000]
            parts.append(f"## {i+1}. {title}\n{md}")
        else:
            parts.append(f"## {i+1}. FAILED: {url}\n{r.get('error', '?')}")
    return "\n---\n".join(parts)


def send_response(req_id, result):
    msg = json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result})
    data = f"Content-Length: {len(msg.encode('utf-8'))}\r\n\r\n{msg}".encode("utf-8")
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def send_error(req_id, code, message):
    msg = json.dumps({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})
    data = f"Content-Length: {len(msg.encode('utf-8'))}\r\n\r\n{msg}".encode("utf-8")
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def handle_request(req):
    method = req.get("method", "")
    req_id = req.get("id")
    params = req.get("params", {})

    if method == "initialize":
        send_response(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        })
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        send_response(req_id, {"tools": TOOLS})
    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        try:
            if name == "firescrape_scrape":
                text = handle_scrape(args)
            elif name == "firescrape_batch":
                text = handle_batch(args)
            else:
                send_error(req_id, -32601, f"Unknown tool: {name}")
                return
            send_response(req_id, {"content": [{"type": "text", "text": text}]})
        except Exception as e:
            send_response(req_id, {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True})
    elif method == "ping":
        send_response(req_id, {})
    else:
        if req_id is not None:
            send_error(req_id, -32601, f"Unknown method: {method}")


def main():
    stdin = sys.stdin.buffer
    while True:
        headers = {}
        while True:
            line = stdin.readline()
            if not line:
                return
            line = line.decode("utf-8").strip()
            if not line:
                break
            if ":" in line:
                key, val = line.split(":", 1)
                headers[key.strip()] = val.strip()
        length = int(headers.get("Content-Length", 0))
        if length == 0:
            continue
        body = stdin.read(length)
        if not body:
            return
        try:
            handle_request(json.loads(body.decode("utf-8")))
        except json.JSONDecodeError:
            send_error(None, -32700, "Parse error")


if __name__ == "__main__":
    main()
