git clone https://github.com/yourusername/webtool.git   # replace with your URL
# WebTool MCP Server (webtool-mcp)

Browser & info access helper for local LLMs via the **Model Context Protocol (MCP)**. Exposes a single HTTP JSON-RPC endpoint LM Studio (and other MCP clients) can call. Optimized for iterative, low‑token browsing: outline first → selective drill‑down → optional link follow.

## Features

Tools currently exposed:

| Tool | Purpose |
|------|---------|
| `fetch_url` | Fetch & parse a webpage. Outline-only mode, per‑section retrieval, single‑hop link follow (`link_id`), or focused chunk view. |
| `web_search` | Multi-engine search (duckduckgo, bing, google_cse, multi aggregate). |
| `search_wikipedia` | Concise summary of a topic from Wikipedia REST API. |
| `latvian_news` | Latest Latvian headlines (Google News RSS) or topic search. |
| `search_duckduckgo` | Legacy single DuckDuckGo lookup (prefer `web_search`). |
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

## System Prompt

See `sysprompt.md` for the fully maintained prompt (ranking heuristics, fallbacks, efficiency rules). Minimal inline guidance:

> Broad topic → `web_search` (multi) → choose URL → `fetch_url(mode='outline')` → pick `chunk_id` OR `link_id` → summarize with cited sources before deeper retrieval.

## Manual Testing (curl examples)

Fetch outline only (cheap):
Web search (multi-engine aggregate):
```bash
curl -s -X POST http://localhost:5000/mcp \
  -H 'Content-Type: application/json' \
  -d '{"name":"web_search","arguments":{"query":"open source vector databases","engine":"multi","engines":["duckduckgo","bing"],"max_results":5}}'
```
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
## Google Custom Search (Optional)

To enable the `google_cse` engine inside `web_search`, export environment variables prior to launch:

```bash
export GOOGLE_API_KEY="your_api_key"
export GOOGLE_CSE_ID="your_cse_id"   # Programmable Search Engine ID
python app.py
```

Then call (example):
```json
{"name":"web_search","arguments":{"query":"vector db benchmarks","engine":"google_cse","max_results":5}}
```

## Search Strategy & Fallbacks

- Ambiguous / exploratory: `web_search` with `engine="multi"` and `engines=["duckduckgo","bing"]`.
- Weak results: refine query (add distinguishing noun, remove stopwords) or switch engine.
- After outline: rank links (authority > freshness > relevance) and follow only one `link_id` per step.
- Avoid re-fetching the same outline unless stale.
- Parsing issue: retry once with `mode='outline'` then choose alternate source.

## JSON-RPC Tool Call Examples

Payloads MCP client sends (wrapping examples):

```jsonc
{"jsonrpc":"2.0","id":1,"method":"tools/list"}
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"fetch_url","arguments":{"url":"https://example.com","mode":"outline"}}}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"fetch_url","arguments":{"url":"https://example.com","chunk_id":"sec-2"}}}
{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"fetch_url","arguments":{"url":"https://example.com","link_id":"L5"}}}
{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"web_search","arguments":{"query":"open source vector database","engine":"multi","engines":["duckduckgo","bing"],"max_results":5}}}
{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"web_search","arguments":{"query":"vector db benchmarks","engine":"google_cse","max_results":5}}}
{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"latvian_news","arguments":{}}}
{"jsonrpc":"2.0","id":8,"method":"tools/call","params":{"name":"search_wikipedia","arguments":{"query":"Milvus"}}}
{"jsonrpc":"2.0","id":9,"method":"tools/call","params":{"name":"stock_quotes","arguments":{"symbols":"AAPL MSFT"}}}
```
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