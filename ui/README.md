# Web UI (work in progress)

A polished single-page app to drive the webtool-mcp server via LM Studio.

Goals:
- Select model (from LM Studio REST listing) and system prompt version.
- Maintain continuous chat session (stream tool outputs).
- Visual diff of tool calls & responses (timeline).
- Elegant dark/light theme, responsive, keyboard friendly.

Stack (proposed):
- Frontend: React + TypeScript + Vite + TailwindCSS + Radix UI primitives.
- Backend proxy: FastAPI (Python) to unify LM Studio and webtool-mcp calls (avoid CORS + add server-sent events fan-out).

This folder will hold UI source once scaffolded.
