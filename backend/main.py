import os, json, re, uuid, asyncio
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx

LM_STUDIO_BASE = os.environ.get("LM_STUDIO_BASE", "http://localhost:1234")
WEBTOOL_MCP_BASE = os.environ.get("WEBTOOL_MCP_BASE", "http://localhost:5000/mcp")

app = FastAPI(title="webtool proxy", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory sessions (simple; can swap to redis later)
SESSIONS: Dict[str, List[Dict[str, Any]]] = {}

class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    user: str
    model: Optional[str] = None
    system_prompt: Optional[str] = None
    stream: bool = True

class ChatChunk(BaseModel):
    type: str
    data: Dict[str, Any]

TOOL_JSON_RE = re.compile(r'^\{\s*"name"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:\s*\{.*\}\s*\}\s*$', re.DOTALL)

async def call_lm_studio(messages: List[Dict[str, str]], model: Optional[str], stream: bool) -> str:
    # Minimal non-stream call; adapt to LM Studio API (assuming /v1/chat/completions like OpenAI compatible)
    endpoint = f"{LM_STUDIO_BASE.rstrip('/')}/v1/chat/completions"
    payload = {"messages": messages, "temperature": 0.2}
    if model:
        payload["model"] = model
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(endpoint, json=payload)
        if r.status_code >= 400:
            raise HTTPException(r.status_code, r.text)
        data = r.json()
    # naive extraction
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    return content or ""

async def mcp_tool_call(name: str, arguments: Dict[str, Any]) -> Any:
    jsonrpc = {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": "tools/call", "params": {"name": name, "arguments": arguments}}
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(WEBTOOL_MCP_BASE, json=jsonrpc)
        if r.status_code >= 400:
            raise HTTPException(r.status_code, r.text)
        data = r.json()
    # Extract content
    try:
        result_text = data["result"]["content"][0]["text"]
    except Exception:
        result_text = json.dumps(data)[:4000]
    return result_text

@app.get("/models")
async def list_models():
    # LM Studio list fallback; if not available return placeholder
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{LM_STUDIO_BASE.rstrip('/')}/v1/models")
            if r.status_code < 400:
                data = r.json()
                ids = [m.get("id") for m in data.get("data", []) if m.get("id")]
                return {"models": ids}
    except Exception:
        pass
    return {"models": ["auto"]}

@app.post("/chat")
async def chat(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())
    history = SESSIONS.setdefault(session_id, [])
    if req.system_prompt and not any(m for m in history if m.get("role") == "system"):
        history.insert(0, {"role": "system", "content": req.system_prompt})
    history.append({"role": "user", "content": req.user})
    content = await call_lm_studio(history, req.model, req.stream)
    history.append({"role": "assistant", "content": content})

    tool_output = None
    if TOOL_JSON_RE.match(content.strip()):
        try:
            obj = json.loads(content)
            name = obj.get("name")
            arguments = obj.get("arguments") or {}
            tool_output = await mcp_tool_call(name, arguments)
            history.append({"role": "tool", "content": tool_output, "name": name})
        except Exception as e:
            tool_output = f"Tool parse/exec error: {e}"
            history.append({"role": "tool", "content": tool_output})
    return {"session_id": session_id, "assistant": content, "tool_output": tool_output}

@app.websocket("/ws")
async def ws_chat(ws: WebSocket):
    await ws.accept()
    session_id = None
    try:
        while True:
            data = await ws.receive_json()
            req = ChatRequest(**data)
            if not session_id:
                session_id = req.session_id or str(uuid.uuid4())
            req.session_id = session_id
            resp = await chat(req)
            await ws.send_json(resp)
    except WebSocketDisconnect:
        return

@app.get("/session/{session_id}")
async def get_session(session_id: str):
    return {"session_id": session_id, "messages": SESSIONS.get(session_id, [])}

@app.get("/health")
async def health():
    return {"status": "ok"}
