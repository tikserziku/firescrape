# FireScrape

Free, local Firecrawl alternative. Built by Claude Code in 15 minutes.

**Playwright + Markdown + Actions + AI extraction + Cache. Zero cost, unlimited scraping.**

## Quick Start

```bash
pip install playwright markdownify readability-lxml beautifulsoup4
python -m playwright install chromium
```

```python
from firescrape import scrape

result = scrape("https://example.com")
print(result["markdown"])
```

## CLI

```bash
python -m firescrape.scraper https://example.com
python -m firescrape.scraper https://example.com --format json --prompt "Extract all prices"
python -m firescrape.scraper https://example.com --actions '[{"type":"click","selector":"#btn"}]'
```

## Features

| Feature | FireScrape | Firecrawl |
|---------|-----------|----------|
| Cost | **$0 forever** | $16+/month |
| Scraping | Playwright (local) | Cloud API |
| Markdown conversion | readability + markdownify | Built-in |
| Actions (click/scroll/type) | Yes | Yes |
| Batch scraping | Yes (parallel) | Yes |
| Cache | File-based (2 days) | Server-side |
| AI extraction | Plug in any LLM | Built-in ($) |
| MCP Server | Yes | Yes ($) |
| Rate limits | None | 500 credits |

## MCP Server (for Claude Code)

```bash
claude mcp add firescrape -- python path/to/firescrape/mcp_server.py
```

3 tools available:
- `firescrape_scrape` — Scrape a single URL
- `firescrape_batch` — Scrape multiple URLs in parallel
- `firescrape_extract` — AI-powered structured data extraction

## Benchmark Results

| Site | FireScrape | Firecrawl | Content |
|------|-----------|-----------|--------|
| example.com | 2.4s | 0.5s | Equal |
| anthropic.com/news | 10.6s | 0.6s | Comparable |
| github.com | 7.9s | 0.6s | FS 2.4x more |
| Wikipedia | 7.7s | 1.5s | Both large |
| Hacker News | 3.0s | 0.6s | Comparable |

Firecrawl is faster at raw scraping (cloud CDN), but in a full AI pipeline, scraping is only ~3% of total time. The bottleneck is AI analysis, not scraping.

**With an AI orchestrator (3 free models in parallel):**
- FireScrape Team: 20.2s, 3 analyses, 8,167 chars output, **$0**
- Firecrawl Solo: 16.8s, 1 analysis, 1,361 chars output, $0.032

## Visual Comparison

See the [interactive comparison page](https://tikserziku.github.io/firescrape/) for charts and detailed analysis.

## Tech Stack

- Python 3
- Playwright (browser automation)
- markdownify (HTML to Markdown)
- readability-lxml (content extraction)
- BeautifulSoup4 (boilerplate removal)
- asyncio (parallel scraping)

## License

MIT
