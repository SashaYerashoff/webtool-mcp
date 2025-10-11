# Agent Prompt Flow Investigation

## Summary: How the Agent Gets Its Prompt

The system uses a **two-layer prompt architecture**: a base prompt from `sysprompt.md` + persona-specific instructions from `presets.ts`.

---

## Complete Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Backend: sysprompt.md                                    │
│    Location: /home/sasha/Projects/webtool/sysprompt.md     │
│                                                              │
│    Content: Core MCP tool instructions, tool call format,   │
│             workflow rules, Vision guidance, etc.           │
│                                                              │
│    Function: _load_sysprompt_file() in app.py              │
│    • Reads sysprompt.md                                     │
│    • Extracts content from triple-backtick code block       │
│    • Returns as string                                      │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. MCP Tool: get_system_prompt                             │
│    Endpoint: POST /mcp                                      │
│    JSON-RPC: {"method":"tools/call",                        │
│               "params":{"name":"get_system_prompt"}}        │
│                                                              │
│    Returns: {"prompt": "You are an autonomous...",          │
│              "version": "1.5"}                              │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. Frontend: API Call                                       │
│    File: ui/src/modules/services/api.ts                    │
│                                                              │
│    export async function getSystemPrompt() {                │
│      const payload = { jsonrpc: '2.0', id: 1,              │
│        method: 'tools/call',                                │
│        params: { name: 'get_system_prompt', arguments:{} } │
│      };                                                      │
│      const r = await fetch(`${MCP_BASE}`, ...);            │
│      return data.result.content[0].text;                    │
│    }                                                         │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│ 4. Frontend: App Component Initialization                   │
│    File: ui/src/modules/App.tsx                            │
│                                                              │
│    const [basePrompt, setBasePrompt] = useState<string>('');│
│    const [persona, setPersona] = useState<PersonaId>(       │
│      'researcher'  // DEFAULT: Deep Researcher             │
│    );                                                        │
│                                                              │
│    useEffect(()=>{                                          │
│      (async()=>{                                            │
│        const p = await getSystemPrompt();                   │
│        if(p) setBasePrompt(p); // Stores base from .md     │
│      })();                                                  │
│    },[]);                                                   │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│ 5. Frontend: Persona Layer                                  │
│    File: ui/src/modules/presets.ts                         │
│                                                              │
│    export const PERSONA_PROMPTS: Record<PersonaId,string> = {│
│      researcher: `ROLE: Deep Researcher                     │
│        - Use high-authority sources...                      │
│        - Prefer web_search(engine='multi')...`,             │
│      news: `ROLE: News Crawler...`,                         │
│      support: `ROLE: Support Agent (Luxriot First)...`      │
│    };                                                        │
│                                                              │
│    export function combinePrompt(base, persona) {           │
│      const header = `\n---\nPersona: ${LABELS[persona]}\n`; │
│      return `${base.trim()}${header}${PROMPTS[persona]}`;  │
│    }                                                         │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│ 6. Final Combined Prompt Sent to LLM                        │
│    File: ui/src/modules/App.tsx (line 88)                  │
│                                                              │
│    <ChatPanel                                               │
│      systemPrompt={combinePrompt(basePrompt, persona)}     │
│      ...                                                     │
│    />                                                        │
│                                                              │
│    Result: Base (sysprompt.md) + Persona instructions      │
└─────────────────────────────────────────────────────────────┘
```

---

## Deep Researcher Prompt - VERIFIED ✓

**Default Persona:** `researcher` (set in App.tsx line 14)

**Label:** "Deep Researcher" (from PERSONA_LABELS)

**Instructions sent to LLM:**
```
[Full sysprompt.md content from triple-backtick block]

---
Persona: Deep Researcher

ROLE: Deep Researcher
- Use high-authority and scientific sources first (official docs, standards, journals, whitepapers).
- Prefer web_search(engine='multi') → fetch_url(mode='outline') → fetch 1 best chunk.
- Be exhaustive but efficient; justify with citations; avoid blogs unless comparing approaches.
- Embed 1–2 relevant images from the page when helpful (see THUMBS/IMAGES).
```

---

## Key Files Reference

| File | Purpose | Lines of Interest |
|------|---------|-------------------|
| `sysprompt.md` | Base MCP tool instructions | Full file (triple-backtick block) |
| `app.py` | Backend prompt loader | 632-655 (_load_sysprompt_file, get_system_prompt) |
| `ui/src/modules/presets.ts` | Persona-specific instructions | 1-33 (PERSONA_PROMPTS, combinePrompt) |
| `ui/src/modules/App.tsx` | Prompt composition | 14 (default persona), 23 (load base), 88 (combine) |
| `ui/src/modules/services/api.ts` | MCP tool call wrapper | 60-71 (getSystemPrompt function) |

---

## Verification Checklist

- [x] Base prompt source: `sysprompt.md` via `_load_sysprompt_file()`
- [x] MCP tool exposure: `get_system_prompt` tool available in `/mcp` endpoint
- [x] Frontend fetch: `getSystemPrompt()` calls MCP and extracts text
- [x] Default persona: `researcher` set on mount
- [x] Persona instructions: Defined in `PERSONA_PROMPTS['researcher']`
- [x] Combination: `combinePrompt(base, persona)` merges both layers
- [x] Deep Researcher gets instructions: **YES** - includes web_search multi-engine preference, high-authority sources, image embedding guidance

---

## How to Change Personas

**UI Method (Trainer):**
1. Open http://localhost:5173 (trainer UI)
2. In left sidebar: "Persona" radio buttons
3. Select "Deep Researcher", "News Crawler", or "Support Agent (Luxriot)"

**Code Method:**
Edit `ui/src/modules/App.tsx` line 14:
```tsx
const [persona, setPersona] = useState<PersonaId>('researcher'); // or 'news' or 'support'
```

**Add New Persona:**
Edit `ui/src/modules/presets.ts`:
1. Add to `PersonaId` type: `'myNewPersona'`
2. Add to `PERSONA_LABELS`: `myNewPersona: 'My Label'`
3. Add to `PERSONA_PROMPTS`: `myNewPersona: \`ROLE: ...\``

---

## Client vs Trainer Behavior

**Trainer UI (index.html):**
- Shows persona selector
- Uses combined prompt: `combinePrompt(basePrompt, persona)`

**Client UI (client.html):**
- Hardcoded to Luxriot support persona in current implementation
- Could be made configurable by importing presets and adding persona state

---

## Current State Summary

✅ **Deep Researcher DOES receive its instructions**
✅ Base prompt loaded from sysprompt.md on app mount
✅ Persona layer appended via combinePrompt()
✅ Final combined prompt sent to ChatPanel → LLM

The system is working as designed with proper prompt layering.
