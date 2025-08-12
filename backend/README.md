# Backend Proxy

FastAPI service that:
- Manages chat sessions (in-memory).
- Forwards conversation to LM Studio completion endpoint.
- Detects JSON tool call objects and invokes webtool-mcp tools.
- Provides WebSocket endpoint for incremental UI updates.

## Endpoints
- GET /models
- POST /chat { user, model?, system_prompt?, session_id? }
- GET /session/{id}
- WS /ws (send same payloads as POST /chat)

Configure with env vars:
- LM_STUDIO_BASE (default http://localhost:1234)
- WEBTOOL_MCP_BASE (default http://localhost:5000/mcp)

## Run
pip install -r requirements.txt
uvicorn main:app --reload --port 7000
