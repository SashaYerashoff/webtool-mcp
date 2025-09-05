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
| `ai_company_news` | Recent headlines per AI/tech company (OpenAI, Google, Anthropic, Microsoft, Nvidia). |
| `get_system_prompt` | Returns the internal system prompt with usage guidance. |
| `luxriot_docs_status` | Status of Luxriot manuals index (ready, files, chunks). |
| `luxriot_docs_search` | BM25 search across Luxriot manuals (query, k?, doc?). |
| `luxriot_docs_get` | Get full text of a matched chunk by chunk_id. |
| `pairs_*` | Save/search conversation pairs; annotate spans; export datasets and summary. |
| `vision_status` | Check availability of SigLIP embeddings and OCR. |
| `vision_encode` | Index an image (URL or base64) with SigLIP embedding + OCR. |
| `vision_search` | Text→image semantic search across indexed images. |
| `vision_extract_from_url` | Fetch a page, extract top images, index with embedding + OCR. |

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

If you encounter `error: externally-managed-environment` (PEP 668) when running `pip install`, you're attempting a system-wide install. Always create and activate a virtual environment first:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
```
Then proceed with dependency installation. Avoid using `--break-system-packages` unless you fully accept system Python modifications.

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

## Backend Proxy & Web UI (Experimental)

Included extras:
- `backend/` FastAPI proxy: mediates LM Studio + MCP tools, detects tool JSON.
- `ui/` React + Vite interface.

### Run All Components (3 terminals)
Terminal 1 (MCP server):
```bash
make install
make run-mcp
```

Terminal 2 (Proxy):
```bash
make install-backend
make run-backend  # http://localhost:7000
```

Terminal 3 (UI):
```bash
cd ui
npm install
npm run dev  # http://localhost:5173
```

Ensure the UI can reach backend routes via Vite proxy (already included). If adding new routes, update `ui/vite.config.ts` accordingly.

Configure endpoints before starting proxy if non-default:
```bash
export LM_STUDIO_BASE=http://localhost:1234
export WEBTOOL_MCP_BASE=http://localhost:5000/mcp
```

### Session Flow
1. User message → proxy `/chat`.
2. Proxy sends full history to LM Studio.
3. Assistant JSON tool call? Proxy invokes MCP tool and appends output.
4. UI shows assistant + tool messages sequentially.

### Roadmap (UI/Proxy)
- WebSocket streaming (partial tokens + tool anticipation).
- Local session history & persistence.
- Tool output folding + JSON highlighting.
- Auth + rate limiting for remote hosting.
- System prompt version selector & diff viewer.

### Verifying from LM Studio

Ask the model: "List the tools you have." It should respond (or you can request a `tools/list` internally) with the tools defined above.

## System Prompt

See `sysprompt.md` for the fully maintained prompt (ranking heuristics, fallbacks, efficiency rules). Minimal inline guidance:

> Broad topic → `web_search` (multi) → choose URL → `fetch_url(mode='outline')` → pick `chunk_id` OR `link_id` → summarize with cited sources before deeper retrieval.

Vision tool usage is also documented in `sysprompt.md` with JSON call examples.

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

## Luxriot Manuals RAG

Place the two PDFs in the project root (or set absolute env paths):

- Luxriot-EVO-S-Administration-Guide.pdf  (env: LUXRIOT_ADMIN_GUIDE)
- Luxriot-EVO-Monitor-User-Guide.pdf      (env: LUXRIOT_MONITOR_GUIDE)

On first use, the server builds a lightweight BM25 index in memory. Tools:

- luxriot_docs_status
- luxriot_docs_search { query, k?=5, doc? }
- luxriot_docs_get { chunk_id }

## Vision (SigLIP + OCR) – Local Setup

Goal: Give a text‑only LLM vision capabilities via tools. You can run embeddings (SigLIP) and OCR locally.

1) System OCR
```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr  # and languages as needed, e.g. tesseract-ocr-all
```

2) Python deps (in your venv)
```bash
pip install Pillow pytesseract transformers sentencepiece protobuf numpy
# Torch (choose ONE):
# CPU-only
pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision
# NVIDIA CUDA 12.1 (example)
# pip install --index-url https://download.pytorch.org/whl/cu121 torch torchvision
```

3) Choose a SigLIP model and start the server
```bash
export WEBTOOL_VISION_MODEL=google/siglip-base-patch16-224
# or larger:
# export WEBTOOL_VISION_MODEL=google/siglip-so400m-patch14-384
python app.py
```

4) Verify
```bash
curl -s http://localhost:5000/vision/status | jq
# expect: ready:true, has_ocr:true, model: "google/siglip-..."
```

5) Smoke test
```bash
curl -s -X POST http://localhost:5000/vision/encode \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://upload.wikimedia.org/wikipedia/commons/3/3a/Cat03.jpg"}' | jq

curl -s -X POST http://localhost:5000/vision/search \
  -H 'Content-Type: application/json' \
  -d '{"q":"a cat","limit":5}' | jq
```

Notes:
- First call downloads model weights to your HF cache (set `HF_HOME` to change location).
- OCR is optional; embeddings enable visual search. OCR is used when text exists.
- We filter OCR noise; empty/garbled text won’t pollute results.

### Vision via the UI
- The Sidebar shows Vision status. You can Extract images from a URL, Upload a file, and Search by text.
- In OCR‑only mode, Extract/Upload is still enabled; Search requires SigLIP loaded.

### Troubleshooting
- SentencePiece error: `pip install -U sentencepiece protobuf`
- Ready=false: ensure `WEBTOOL_VISION_MODEL` is exported in the same terminal as Flask.
- Memory errors: switch to the smaller model (`siglip-base-patch16-224`).
- Vite can’t reach backend: ensure `/vision` is proxied in `ui/vite.config.ts`.

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

Licensed under the MIT License – see `LICENSE`.

Dependency license compatibility (all permissive / MIT‑compatible):
- Flask (BSD-3-Clause)
- Requests (Apache-2.0)
- BeautifulSoup4 / bs4 (MIT)
- duckduckgo-search (MIT)

No copyleft or restrictive GPL dependencies are included, so MIT distribution is appropriate.

---
Happy browsing with your local models! 🧭