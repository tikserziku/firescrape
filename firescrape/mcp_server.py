#!/usr/bin/env python3
"""
FireScrape MCP Server — JSON-RPC 2.0 over stdio.
Drop-in Firecrawl replacement. Zero cost, unlimited scraping.

Usage:
  claude mcp add firescrape -- python path/to/firescrape/mcp_server.py
"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SERVER_INFO = {
    "name": "firescrape",
    "version": "1.0.0",
}

TOOLS = [
    {
        "name": "firescrape_scrape",
        "description": "Scrape a URL and return markdown, HTML, links, or structured JSON. Free Firecrawl alternative using local Playwright browser.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to scrape"},
                "formats": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["markdown", "html", "links", "screenshot", "json"]},
                    "description": "Output formats (default: ['markdown'])",
                    "default": ["markdown"],
                },
                "onlyMainContent": {"type": "boolean", "description": "Extract main content only (default: true)", "default": True},
                "prompt": {"type": "string", "description": "AI extraction prompt for JSON format"},
                "actions": {
                    "type": "array",
                    "description": "Firecrawl-compatible actions: click, write, wait, press, scroll, screenshot, scrape",
                    "items": {"type": "object"},
                },
                "waitFor": {"type": "string", "description": "CSS selector to wait for before scraping"},
                "noCache": {"type": "boolean", "description": "Skip cache (default: false)", "default": False},
            },
            "required": ["url"],
        },
    },
    {
        "name": "firescrape_batch",
        "description": "Scrape multiple URLs in parallel. Returns array of results.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of URLs to scrape",
                },
                "formats": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Output formats (default: ['markdown'])",
                    "default": ["markdown"],
                },
                "onlyMainContent": {"type": "boolean", "default": True},
            },
            "required": ["urls"],
        },
    },
    {
        "name": "firescrape_extract",
        "description": "Extract structured data from a URL using AI. Returns JSON.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to extract data from"},
                "prompt": {"type": "string", "description": "What data to extract (e.g. 'Extract all product names and prices')"},
            },
            "required": ["url", "prompt"],
        },
    },
]


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


def handle_scrape(args):
    from firescrape.scraper import scrape
    url = args["url"]
    formats = args.get("formats", ["markdown"])
    only_main = args.get("onlyMainContent", True)
    prompt = args.get("prompt")
    actions = args.get("actions")
    wait_for = args.get("waitFor")
    no_cache = args.get("noCache", False)

    if prompt and "json" not in formats:
        formats.append("json")

    result = scrape(
        url,
        formats=formats,
        actions=actions,
        only_main_content=only_main,
        max_age=0 if no_cache else 172800,
        wait_for=wait_for,
        prompt=prompt,
    )

    # Clean internal fields
    result.pop("_cached_at", None)
    from_cache = result.pop("_from_cache", False)

    # Build text output
    parts = []
    if result.get("success"):
        title = result.get("metadata", {}).get("title", "")
        if title:
            parts.append(f"**{title}**\n")

        if "markdown" in result:
            md = result["markdown"]
            if len(md) > 50000:
                md = md[:50000] + f"\n\n... (truncated, {len(result['markdown'])} total chars)"
            parts.append(md)

        if "json" in result:
            parts.append("\n**Extracted JSON:**\n```json\n" + json.dumps(result["json"], indent=2, ensure_ascii=False)[:5000] + "\n```")

        if "links" in result:
            links_text = "\n".join(f"- [{l['text'][:60]}]({l['url']})" for l in result["links"][:30])
            parts.append(f"\n**Links ({len(result['links'])} total):**\n{links_text}")

        if from_cache:
            parts.append("\n*(from cache)*")
    else:
        parts.append(f"Error scraping {url}: {result.get('error', 'unknown')}")

    return "\n".join(parts)


def handle_batch(args):
    from firescrape.scraper import scrape_batch
    urls = args["urls"]
    formats = args.get("formats", ["markdown"])
    only_main = args.get("onlyMainContent", True)

    results = scrape_batch(urls, formats=formats, only_main_content=only_main, max_age=0)

    parts = []
    for i, r in enumerate(results):
        url = urls[i] if i < len(urls) else "?"
        if r.get("success"):
            title = r.get("metadata", {}).get("title", url)
            md = r.get("markdown", "")[:10000]
            parts.append(f"## {i+1}. {title}\n{md}\n")
        else:
            parts.append(f"## {i+1}. FAILED: {url}\n{r.get('error', '?')}\n")

    return "\n---\n".join(parts)


def handle_extract(args):
    from firescrape.scraper import scrape
    url = args["url"]
    prompt = args["prompt"]

    result = scrape(url, formats=["json"], prompt=prompt, only_main_content=False, max_age=0)

    if "json" in result:
        return json.dumps(result["json"], indent=2, ensure_ascii=False)[:10000]
    return f"Error: {result.get('error', 'extraction failed')}"


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
            elif name == "firescrape_extract":
                text = handle_extract(args)
            else:
                send_error(req_id, -32601, f"Unknown tool: {name}")
                return

            send_response(req_id, {
                "content": [{"type": "text", "text": text}],
            })
        except Exception as e:
            send_response(req_id, {
                "content": [{"type": "text", "text": f"Error: {str(e)}"}],
                "isError": True,
            })

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
            req = json.loads(body.decode("utf-8"))
            handle_request(req)
        except json.JSONDecodeError:
            send_error(None, -32700, "Parse error")


if __name__ == "__main__":
    main()
