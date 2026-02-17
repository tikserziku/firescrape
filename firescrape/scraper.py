#!/usr/bin/env python3
"""
FireScrape — Local Firecrawl alternative.
Playwright + Markdown + Actions + AI extraction + Cache.
Zero cost, unlimited scraping.

Usage:
  from firescrape.scraper import scrape, scrape_batch
  result = scrape("https://example.com")
  print(result["markdown"])

CLI:
  python -m firescrape.scraper https://example.com
  python -m firescrape.scraper https://example.com --format json --prompt "Extract prices"
  python -m firescrape.scraper https://example.com --actions '[{"type":"click","selector":"#btn"}]'
"""

import asyncio
import json
import hashlib
import time
import sys
import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

# Lazy imports for speed
_playwright = None
_browser = None

ROOT = Path(__file__).parent.parent.resolve()
CACHE_DIR = Path(__file__).parent / ".cache"
CACHE_DIR.mkdir(exist_ok=True)
CACHE_MAX_AGE = 172800  # 2 days default


async def _get_browser():
    """Lazy browser init — reuse across calls."""
    global _playwright, _browser
    if _browser is None:
        from playwright.async_api import async_playwright
        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ]
        )
    return _browser


def _strip_boilerplate(html: str) -> str:
    """Remove nav, footer, sidebar, header — keep only content areas."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        # Remove common noise elements
        for tag in soup.find_all(["nav", "footer", "header", "aside", "noscript"]):
            tag.decompose()
        # Remove by common class/id patterns
        for attr in ["class", "id"]:
            for el in soup.find_all(attrs={attr: True}):
                val = " ".join(el.get(attr, [])) if isinstance(el.get(attr), list) else str(el.get(attr, ""))
                val_lower = val.lower()
                if any(x in val_lower for x in ["nav", "footer", "sidebar", "cookie", "banner", "menu", "popup", "modal", "ad-", "advert"]):
                    el.decompose()
        # Try to find main content container
        main = soup.find("main") or soup.find(attrs={"role": "main"}) or soup.find(id="content") or soup.find(class_="content")
        if main and len(main.get_text(strip=True)) > 200:
            return str(main)
        return str(soup)
    except Exception:
        return html


def _html_to_markdown(html: str, only_main: bool = True) -> str:
    """Convert HTML to clean markdown."""
    from markdownify import markdownify as md

    title = ""
    if only_main:
        try:
            from readability import Document
            doc = Document(html)
            main_html = doc.summary()
            title = doc.title()
            # Test: convert readability result and check MARKDOWN length (not HTML)
            test_md = md(main_html, heading_style="ATX", strip=["img", "script", "style"]).strip()
            if len(test_md) > 500:
                html = main_html
            else:
                # Readability returned noise — strip boilerplate from original
                html = _strip_boilerplate(html)
        except Exception:
            html = _strip_boilerplate(html)

    markdown = md(html, heading_style="ATX", strip=["img", "script", "style"])
    # Clean up excessive whitespace
    lines = []
    prev_empty = False
    for line in markdown.split("\n"):
        stripped = line.rstrip()
        if not stripped:
            if not prev_empty:
                lines.append("")
                prev_empty = True
        else:
            lines.append(stripped)
            prev_empty = False

    result = "\n".join(lines).strip()
    if title and not result.startswith(f"# {title}"):
        result = f"# {title}\n\n{result}"
    return result


def _cache_key(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


def _cache_get(url: str, max_age: int = CACHE_MAX_AGE) -> Optional[dict]:
    """Get from SQLite-free file cache."""
    key = _cache_key(url)
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - data.get("_cached_at", 0) < max_age:
                return data
        except Exception:
            pass
    return None


def _cache_set(url: str, data: dict):
    """Save to file cache."""
    key = _cache_key(url)
    data["_cached_at"] = time.time()
    path = CACHE_DIR / f"{key}.json"
    path.write_text(json.dumps(data, ensure_ascii=False)[:500000], encoding="utf-8")


async def _execute_actions(page, actions: list) -> dict:
    """Execute Firecrawl-compatible actions on page."""
    results = {"screenshots": [], "scrapes": []}

    for action in actions:
        atype = action.get("type", "")

        if atype == "wait":
            ms = action.get("milliseconds", 1000)
            await asyncio.sleep(ms / 1000)

        elif atype == "click":
            selector = action.get("selector", "")
            if selector:
                try:
                    await page.click(selector, timeout=5000)
                except Exception:
                    pass

        elif atype == "write":
            text = action.get("text", "")
            selector = action.get("selector")
            if selector:
                await page.fill(selector, text)
            else:
                await page.keyboard.type(text)

        elif atype == "press":
            key = action.get("key", "Enter")
            await page.keyboard.press(key)

        elif atype == "scroll":
            direction = action.get("direction", "down")
            amount = action.get("amount", 500)
            if direction == "down":
                await page.evaluate(f"window.scrollBy(0, {amount})")
            else:
                await page.evaluate(f"window.scrollBy(0, -{amount})")

        elif atype == "screenshot":
            full_page = action.get("fullPage", False)
            ss = await page.screenshot(full_page=full_page)
            # Save to temp file
            ss_path = CACHE_DIR / f"screenshot_{int(time.time())}.png"
            ss_path.write_bytes(ss)
            results["screenshots"].append(str(ss_path))

        elif atype == "scrape":
            html = await page.content()
            results["scrapes"].append({
                "url": page.url,
                "html": html[:10000]
            })

    return results


async def _scrape_async(
    url: str,
    formats: list = None,
    actions: list = None,
    only_main_content: bool = True,
    max_age: int = CACHE_MAX_AGE,
    timeout: int = 30000,
    wait_for: str = None,
    prompt: str = None,
    location: dict = None,
) -> dict:
    """Core scrape function."""
    formats = formats or ["markdown"]

    # Check cache (skip if actions or maxAge=0)
    if not actions and max_age > 0:
        cached = _cache_get(url, max_age)
        if cached:
            cached["_from_cache"] = True
            return cached

    browser = await _get_browser()

    # Create context with optional location
    context_opts = {
        "viewport": {"width": 1280, "height": 720},
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    }
    if location:
        if "languages" in location:
            context_opts["locale"] = location["languages"][0] if location["languages"] else "en-US"

    context = await browser.new_context(**context_opts)
    page = await context.new_page()

    result = {
        "success": True,
        "url": url,
        "metadata": {},
    }

    try:
        # Navigate
        response = await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass  # Don't fail on networkidle timeout — domcontentloaded is enough

        if wait_for:
            await page.wait_for_selector(wait_for, timeout=10000)

        # Status
        result["metadata"]["statusCode"] = response.status if response else 0

        # Execute actions if any
        action_results = None
        if actions:
            action_results = await _execute_actions(page, actions)
            result["actions"] = action_results

        # Get page data
        html = await page.content()
        title = await page.title()
        result["metadata"]["title"] = title
        result["metadata"]["sourceURL"] = url

        # Extract meta tags
        try:
            metas = await page.evaluate("""() => {
                const m = {};
                document.querySelectorAll('meta').forEach(el => {
                    const name = el.getAttribute('name') || el.getAttribute('property') || '';
                    const content = el.getAttribute('content') || '';
                    if (name && content) m[name] = content;
                });
                return m;
            }""")
            result["metadata"]["description"] = metas.get("description", metas.get("og:description", ""))
            result["metadata"]["language"] = metas.get("language", await page.evaluate("document.documentElement.lang || 'en'"))
            result["metadata"]["ogTitle"] = metas.get("og:title", "")
            result["metadata"]["ogImage"] = metas.get("og:image", "")
        except Exception:
            pass

        # Generate requested formats
        if "markdown" in formats:
            result["markdown"] = _html_to_markdown(html, only_main_content)

        if "html" in formats:
            result["html"] = html

        if "rawHtml" in formats:
            result["rawHtml"] = html

        if "links" in formats:
            links = await page.evaluate("""() =>
                [...document.querySelectorAll('a[href]')].map(a => ({
                    text: a.textContent.trim().slice(0, 100),
                    url: a.href
                })).filter(l => l.url.startsWith('http'))
            """)
            result["links"] = links

        if "screenshot" in formats:
            ss = await page.screenshot(full_page=True)
            ss_path = CACHE_DIR / f"ss_{_cache_key(url)}.png"
            ss_path.write_bytes(ss)
            result["screenshot"] = str(ss_path)

        # JSON extraction via AI
        if "json" in formats and prompt:
            try:
                md_text = _html_to_markdown(html, False)
                extract_prompt = f"{prompt}\n\nRespond ONLY with valid JSON, no markdown formatting.\n\nPage content:\n{md_text[:8000]}"
                # You can plug in any free LLM API here
                result["json"] = {"note": "Plug in your preferred LLM API for JSON extraction", "prompt": prompt}
            except Exception as e:
                result["json"] = {"error": str(e)}

        # Cache result (without screenshots binary)
        if not actions and max_age > 0:
            cache_data = {k: v for k, v in result.items() if k != "screenshot"}
            _cache_set(url, cache_data)

    except Exception as e:
        result["success"] = False
        result["error"] = str(e)
    finally:
        await context.close()

    return result


def scrape(url: str, **kwargs) -> dict:
    """Synchronous scrape wrapper."""
    global _browser, _playwright
    # Reset browser — asyncio.run() kills the event loop, making old browser unusable
    _browser = None
    _playwright = None
    return asyncio.run(_scrape_async(url, **kwargs))


async def _batch_async(urls: list, **kwargs) -> list:
    """Scrape multiple URLs concurrently."""
    tasks = [_scrape_async(url, **kwargs) for url in urls]
    return await asyncio.gather(*tasks, return_exceptions=True)


def scrape_batch(urls: list, **kwargs) -> list:
    """Scrape multiple URLs in parallel."""
    results = asyncio.run(_batch_async(urls, **kwargs))
    return [r if isinstance(r, dict) else {"success": False, "error": str(r)} for r in results]


async def cleanup():
    """Close browser."""
    global _browser, _playwright
    if _browser:
        await _browser.close()
        _browser = None
    if _playwright:
        await _playwright.stop()
        _playwright = None


# --- CLI ---
def main():
    import argparse
    parser = argparse.ArgumentParser(description="FireScrape — local web scraper")
    parser.add_argument("url", help="URL to scrape")
    parser.add_argument("--format", "-f", default="markdown", help="Output formats: markdown,html,json,links,screenshot")
    parser.add_argument("--actions", "-a", help="JSON array of actions")
    parser.add_argument("--prompt", "-p", help="AI extraction prompt")
    parser.add_argument("--no-cache", action="store_true", help="Skip cache")
    parser.add_argument("--full", action="store_true", help="Full page (not just main content)")
    args = parser.parse_args()

    formats = args.format.split(",")
    actions = json.loads(args.actions) if args.actions else None
    max_age = 0 if args.no_cache else CACHE_MAX_AGE

    if args.prompt and "json" not in formats:
        formats.append("json")

    t0 = time.time()
    result = scrape(
        args.url,
        formats=formats,
        actions=actions,
        only_main_content=not args.full,
        max_age=max_age,
        prompt=args.prompt,
    )
    elapsed = time.time() - t0

    cached = result.pop("_from_cache", False)
    source = "CACHE" if cached else "LIVE"

    if "json" in result:
        print(json.dumps(result["json"], indent=2, ensure_ascii=False)[:3000])
    elif "markdown" in result:
        print(result["markdown"][:3000])
    elif "links" in result:
        for link in result["links"][:20]:
            print(f"  {link['text'][:50]:50s} -> {link['url']}")

    print(f"\n--- [{source}] {elapsed:.1f}s | {result['metadata'].get('title', '?')} ---")


if __name__ == "__main__":
    main()
