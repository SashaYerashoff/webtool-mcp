git clone https://github.com/yourusername/webtool.git   # replace with your URL
# WebTool MCP Server (webtool-mcp)

Browser & info access helper for local LLMs via the **Model Context Protocol (MCP)**. Exposes a single HTTP JSON-RPC endpoint LM Studio (and other MCP clients) can call. Optimized for iterative, low‑token browsing: outline first → selective drill‑down → optional link follow.

## Features

Tools currently exposed:

| Tool | Purpose |
|------|---------|
| `fetch_url` | Fetch & parse a webpage. Supports: outline-only mode, per‑section (chunk) retrieval, single‑hop link follow (`link_id`), or focused chunk view. Returns META / OUTLINE / LINKS / CHUNKS / (optionally CHUNK / KEYPOINTS / ENTITIES etc.). |
| `search_wikipedia` | Concise summary of a topic from Wikipedia REST API. |
| `latvian_news` | Latest Latvian headlines (Google News RSS) or topic search. |
| `search_duckduckgo` | DuckDuckGo Instant Answer + related links to bootstrap browsing. |
| `stock_quotes` | Basic market quote snapshot (unofficial Yahoo Finance). |
| `get_system_prompt` | Returns the internal system prompt with usage guidance. |

All tools are discoverable through the MCP `tools/list` (or `tools.list`) JSON-RPC method.

## Repo

GitHub: https://github.com/SashaYerashoff/webtool-mcp

## Quick Start (Ubuntu / Debian / WSL)

```bash
sudo apt update && sudo apt install -y python3 python3-venv git
git clone https://github.com/SashaYerashoff/webtool-mcp.git
cd webtool-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python app.py  # serves on http://0.0.0.0:5000 (http://localhost:5000)
```

Keep the process running (e.g. with `tmux`, `screen`, or a systemd service) if you want persistent availability.

### Quick Start (Windows 10/11 PowerShell)

```pwsh
# Ensure Python 3.11+ from Microsoft Store or python.org is installed
git clone https://github.com/SashaYerashoff/webtool-mcp.git
cd webtool-mcp
python -m venv .venv
. .venv/Scripts/Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
python app.py  # http://localhost:5000
```

If Windows Firewall prompts, allow local network access (loopback is enough for LM Studio).

### Install as a dependency (optional)

You can also just install straight from Git:

```bash
pip install git+https://github.com/SashaYerashoff/webtool-mcp.git
```

Then run (clone not strictly required, but the above is simplest for development):

```bash
python -m webtool_mcp  # (future packaging plan) – for now use app.py directly
```

## Running Behind a Different Port

Change the `app.run(... port=5000)` line or export `PORT` and modify code to read it (not yet implemented). If you change the port you must update LM Studio config accordingly.

## LM Studio Integration

1. Start this server locally: `python app.py` → `http://localhost:5000/mcp`
2. In LM Studio (0.3.17+ with MCP support):
   * Open: Program → Install → (scroll) Edit MCP Configuration (or locate `mcp.json`).
3. Add / merge the entry:

```jsonc
{
  "mcpServers": {
    "webtool-mcp": {
      "url": "http://localhost:5000/mcp"  // or your LAN IP
    }
  }
}
```

4. Save and click Reload MCPs (or restart LM Studio).
5. Open a chat with your local model. The tools should appear in the UI or be callable automatically.

### Verifying from LM Studio

Ask the model: "List the tools you have." It should respond (or you can request a `tools/list` internally) with the tools defined above.

## System Prompt (You Can Paste This Into Your Model Setup)

```
You are an autonomous browsing and data assistant. Tools available:
- fetch_url(url, chunk_id?, section?, mode?='outline', link_id?). Use mode='outline' first to get structure cheaply. Only request specific sections (sec-#) or follow link ids (L#) that you actually need. Avoid refetching the same page unless mode/section differ. Single-hop link follow returns HISTORY + target page.
- search_wikipedia(query) for concise background.
- latvian_news(query?) for latest Latvian headlines or topic-specific headlines.
- search_duckduckgo(query) for quick related topics when you lack a starting URL.
- stock_quotes(symbols) for basic market data (not investment advice).
Decision Guidance:
1. When given a broad topic: use search_duckduckgo or search_wikipedia to ground terms, then fetch_url on the most relevant authoritative link.
2. When given a specific URL: call fetch_url with mode='outline' first, inspect OUTLINE/LINKS, then drill into a needed section via chunk_id (sec-#) OR follow a promising link_id (L#). Do not request multiple large sections at once—iterate.
3. For news monitoring (Latvia or topic): use latvian_news (optionally with a query). Only fetch individual articles if deeper detail is requested—then follow their link via fetch_url.
4. Minimize token usage: prefer outline mode -> targeted chunk -> optional follow-up. Avoid reprocessing full page repeatedly.
5. If an error occurs (network/parser), retry once with a simpler mode (outline) before giving up. Report the failing URL succinctly.
6. Always cite the source URL(s) you used in your final answer.
7. Financial data: use stock_quotes only when user explicitly asks about symbols; do not infer trades or give advice.
Output Discipline:
- Summaries should differentiate between source facts and your synthesis.
- When combining multiple chunks/pages, list sources with their role.
- If insufficient data gathered, state what next tool call would retrieve missing info.
```

## Manual Testing (curl examples)

Fetch outline only (cheap):
```bash
curl -s -X POST http://localhost:5000/mcp \
  -H 'Content-Type: application/json' \
  -d '{"name":"fetch_url","arguments":{"url":"https://example.com","mode":"outline"}}' | jq -r '.result.content[0].text' | head
```

Fetch a specific section after outline (example `sec-2`):
```bash
curl -s -X POST http://localhost:5000/mcp \
  -H 'Content-Type: application/json' \
  -d '{"name":"fetch_url","arguments":{"url":"https://example.com","chunk_id":"sec-2"}}'
```

Follow a link from outline (`L5`):
```bash
curl -s -X POST http://localhost:5000/mcp \
  -H 'Content-Type: application/json' \
  -d '{"name":"fetch_url","arguments":{"url":"https://example.com","link_id":"L5"}}'
```

Wikipedia summary:
```bash
curl -s -X POST http://localhost:5000/mcp \
  -H 'Content-Type: application/json' \
  -d '{"name":"search_wikipedia","arguments":{"query":"Python (programming language)"}}'
```

Latvian news:
```bash
curl -s -X POST http://localhost:5000/mcp \
  -H 'Content-Type: application/json' \
  -d '{"name":"latvian_news"}'
```

## JSON-RPC Notes

LM Studio now uses JSON-RPC 2.0 methods like `initialize`, `tools/list`, and `tools/call`. This server supports:

* `POST /mcp` body: `{ "jsonrpc":"2.0","id":1,"method":"tools/list" }`
* Tool call shape: `{ "jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"fetch_url","arguments":{"url":"https://example.com","mode":"outline"}} }`

Legacy (non JSON-RPC) payloads with `{"name": "fetch_url", "arguments": {...}}` are still handled for quick manual curl tests.

## Production & Security Considerations

This is a demo / local helper:

- No auth, rate limiting, or HTTPS.
- User-provided URLs are fetched server-side; avoid exposing it publicly without safeguards.
- Respect target site robots.txt / Terms of Service.
- Consider caching, backoff and user-agent tuning for high volume usage.
- Add an allowlist if you embed this in an automated system.

## Roadmap / Ideas

- Package as an installable module with console entry point.
- Add configurable max tokens / chunk merging.
- Optional vector store for revisiting context across sessions.
- Better error normalization & retry policy.

## License

Add a license of your choice (MIT recommended) – currently unlicensed.

---
Happy browsing with your local models! 🧭