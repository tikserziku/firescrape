#!/usr/bin/env python3
"""
FireScrape vs Firecrawl — Benchmark Suite.
Tests both on the same URLs, compares speed, output quality, features.

Usage:
  FIRECRAWL_API_KEY=fc-... python benchmark.py
"""

import time
import json
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Test URLs — mix of simple and complex sites
TEST_URLS = [
    ("Simple HTML", "https://example.com"),
    ("Anthropic News", "https://www.anthropic.com/news"),
    ("GitHub Repo", "https://github.com/anthropics/claude-code"),
    ("Wikipedia", "https://en.wikipedia.org/wiki/Artificial_intelligence"),
    ("Dynamic SPA", "https://news.ycombinator.com"),
]

FIRECRAWL_KEY = os.environ.get("FIRECRAWL_API_KEY", "")


def test_firescrape(url: str) -> dict:
    """Test our FireScrape."""
    from firescrape.scraper import scrape
    t0 = time.time()
    try:
        result = scrape(url, formats=["markdown"], only_main_content=True, max_age=0)
        elapsed = time.time() - t0
        md = result.get("markdown", "")
        return {
            "tool": "FireScrape",
            "success": result.get("success", False),
            "time": round(elapsed, 1),
            "chars": len(md),
            "lines": len(md.split("\n")),
            "title": result.get("metadata", {}).get("title", ""),
            "preview": md[:150].replace("\n", " "),
        }
    except Exception as e:
        return {
            "tool": "FireScrape",
            "success": False,
            "time": round(time.time() - t0, 1),
            "error": str(e)[:100],
            "chars": 0, "lines": 0, "title": "", "preview": "",
        }


def test_firecrawl(url: str) -> dict:
    """Test Firecrawl via HTTP API."""
    if not FIRECRAWL_KEY:
        return {"tool": "Firecrawl", "success": False, "error": "No API key", "time": 0, "chars": 0, "lines": 0, "title": "", "preview": ""}

    import urllib.request

    t0 = time.time()
    try:
        payload = json.dumps({
            "url": url,
            "formats": ["markdown"],
            "onlyMainContent": True,
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://api.firecrawl.dev/v1/scrape",
            data=payload,
            headers={
                "Authorization": f"Bearer {FIRECRAWL_KEY}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        elapsed = time.time() - t0
        success = data.get("success", False)
        md = data.get("data", {}).get("markdown", "")
        title = data.get("data", {}).get("metadata", {}).get("title", "")

        return {
            "tool": "Firecrawl",
            "success": success,
            "time": round(elapsed, 1),
            "chars": len(md),
            "lines": len(md.split("\n")),
            "title": title[:60] if title else "",
            "preview": md[:150].replace("\n", " ") if md else "",
        }
    except Exception as e:
        return {
            "tool": "Firecrawl",
            "success": False,
            "time": round(time.time() - t0, 1),
            "error": str(e)[:100],
            "chars": 0, "lines": 0, "title": "", "preview": "",
        }


def run_benchmark():
    """Run full benchmark."""
    print("=" * 70)
    print("  BENCHMARK: FireScrape (FREE) vs Firecrawl ($16+/mo)")
    print("=" * 70)
    print()

    results = []

    for name, url in TEST_URLS:
        print(f"Testing: {name} ({url})")
        print("-" * 50)

        fs = test_firescrape(url)
        print(f"  FireScrape: {'OK' if fs['success'] else 'FAIL'} | {fs['time']}s | {fs['chars']} chars | {fs.get('error', '')}")

        fc = test_firecrawl(url)
        print(f"  Firecrawl:  {'OK' if fc['success'] else 'FAIL'} | {fc['time']}s | {fc['chars']} chars | {fc.get('error', '')}")

        results.append({"name": name, "url": url, "firescrape": fs, "firecrawl": fc})
        print()

    # Summary
    print("=" * 70)
    print("  RESULTS")
    print("=" * 70)
    print()
    print(f"| {'Site':20s} | {'Tool':12s} | {'Time':6s} | {'Chars':7s} | {'Status':6s} |")
    print(f"|{'-'*22}|{'-'*14}|{'-'*8}|{'-'*9}|{'-'*8}|")

    for r in results:
        fs = r["firescrape"]
        fc = r["firecrawl"]
        name = r["name"]
        print(f"| {name:20s} | {'FireScrape':12s} | {fs['time']:5.1f}s | {fs['chars']:7d} | {'OK' if fs['success'] else 'FAIL':6s} |")
        print(f"| {'':20s} | {'Firecrawl':12s} | {fc['time']:5.1f}s | {fc['chars']:7d} | {'OK' if fc['success'] else 'FAIL':6s} |")

    # Save
    out = Path("benchmark_results.json")
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nResults saved to {out}")

    return results


if __name__ == "__main__":
    run_benchmark()
