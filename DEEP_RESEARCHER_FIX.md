# Deep Researcher Behavior Fixes

## Issues Identified

1. **Premature stopping** - Current limit: 10 tool calls (configurable via `WEBTOOL_MAX_TOOL_CALLS`)
2. **Ignoring initial prompt** - Weak instruction to "start immediately"
3. **Vague execution guidance** - "Be exhaustive but efficient" is too ambiguous
4. **No continuation triggers** - LLM doesn't know when to keep going

## Root Causes

### 1. Hard Tool Call Limit (app.py:897-900)
```python
env_max = int(os.environ.get('WEBTOOL_MAX_TOOL_CALLS', '10'))
MAX_TOOL_CALLS = max(1, min(15, env_max))
```
- Default: 10 tool calls maximum
- Researcher needs 6-12+ for thorough reports
- **Fix**: Increase default and add persona-aware limits

### 2. Weak Persona Instructions (presets.ts)
Old:
```
- Use high-authority sources...
- Prefer web_search(engine='multi')...
- Be exhaustive but efficient...
```
Problems:
- No clear protocol
- No minimum requirements
- No anti-patterns
- No explicit "continue autonomously" instruction

### 3. LLM Behavior Patterns
- Models often stop and "ask permission" without explicit autonomy instructions
- They interpret "efficient" as "minimal tool calls"
- They wait for user confirmation unless told otherwise

## Solutions Implemented

### ✅ 1. Enhanced Deep Researcher Persona (presets.ts)

**NEW**: Explicit research protocol with 5 phases:
1. SCOPE - Search 3-5 diverse sources
2. DEPTH - Fetch outlines + best chunks
3. SYNTHESIS - Combine findings
4. VALIDATION - Cross-reference
5. COMPLETION - Structured report

**NEW**: Clear execution rules:
- "ALWAYS respond immediately... IMMEDIATELY execute first tool call"
- "NEVER wait for permission"
- "MINIMUM 4-6 tool calls per research task"
- "If you have <3 sources, explicitly state... and continue"

**NEW**: Anti-patterns section (tells model what NOT to do):
- ❌ Stopping after 1-2 tool calls
- ❌ Asking "should I continue?"
- ❌ Providing surface-level answers
- ❌ Ignoring the initial prompt
- ❌ Waiting for explicit continuation

**NEW**: Continuation trigger:
- "If <4 tool calls OR <3 sources OR key aspects unexplored → continue automatically"

### 🔧 2. Recommended Backend Configuration

**Option A: Environment Variable** (Quick fix)
```bash
# In your shell or .env file
export WEBTOOL_MAX_TOOL_CALLS=20
```

**Option B: Code Change** (app.py line 897)
```python
# Before:
env_max = int(os.environ.get('WEBTOOL_MAX_TOOL_CALLS', '10'))

# After (persona-aware):
env_max = int(os.environ.get('WEBTOOL_MAX_TOOL_CALLS', '20'))
```

**Option C: Persona-Specific Limits** (Advanced - requires app.py changes)
```python
# Add to proxy_chat_stream function
def _get_max_tools_for_persona(system_prompt: str) -> int:
    if 'Deep Researcher' in system_prompt or 'ROLE: Deep Researcher' in system_prompt:
        return int(os.environ.get('WEBTOOL_RESEARCHER_MAX_CALLS', '20'))
    elif 'News Crawler' in system_prompt:
        return int(os.environ.get('WEBTOOL_NEWS_MAX_CALLS', '12'))
    else:
        return int(os.environ.get('WEBTOOL_MAX_TOOL_CALLS', '10'))
```

### 🎯 3. LM Studio Model Settings

Adjust your LM Studio settings for better Deep Researcher behavior:

**Temperature**: 0.3-0.5 (higher = more creative research paths)
**Top P**: 0.9
**Repeat Penalty**: 1.05
**Context Length**: 8192+ (essential for multi-source research)
**Max Tokens**: 2048-4096 (allow long reports)

**Stop Sequences** (REMOVE these if present):
- Remove: `User:`, `Human:`, `Assistant:`
- Keep only: `</s>`, `<|endoftext|>`

## Expected Behavior After Fix

### Before:
```
User: Research quantum computing error correction
Assistant: Let me search for that...
[1 tool call: web_search]
Here's a basic overview... [stops]
```

### After:
```
User: Research quantum computing error correction
Assistant: I'll conduct comprehensive research on quantum error correction methods. 
Starting with multi-engine search then diving into authoritative sources.

[Tool 1: web_search(engine='multi')]
Found 5 promising sources. Fetching IEEE and arxiv papers...

[Tool 2: fetch_url(mode='outline') - IEEE paper]
Excellent technical depth. Extracting key section on surface codes...

[Tool 3: fetch_url(chunk_id='sec-3') - Surface codes section]
[Tool 4: fetch_url(mode='outline') - Arxiv paper]
[Tool 5: fetch_url(chunk_id='sec-2') - Different approach]
[Tool 6: fetch_url(mode='outline') - Google quantum blog]

Cross-referencing findings across 3 sources...

## Comprehensive Report: Quantum Error Correction
[Structured report with citations]
```

## Testing the Fix

1. **Restart the UI dev server**:
```bash
cd ui && npm run dev
```

2. **Set environment variable** (Terminal where you run Flask):
```bash
export WEBTOOL_MAX_TOOL_CALLS=20
make run-mcp
```

3. **Test with Deep Researcher**:
- Select "Deep Researcher" persona
- Ask: "Provide a comprehensive analysis of retrieval-augmented generation (RAG) architectures"
- Expected: 6-12 tool calls, 3-5 sources, structured report

4. **Verify behavior**:
- ✓ Responds immediately with research plan + first tool call
- ✓ Continues autonomously without asking permission
- ✓ Gathers from multiple sources
- ✓ Provides structured report with citations
- ✓ Doesn't stop prematurely

## Monitoring and Debugging

**Check tool call count** in SSE stream:
- Browser DevTools → Network → chat_stream → EventStream
- Count `tool_start` events
- Should see 6-12 for research tasks

**Check for premature stops**:
- If assistant stops at exactly 10 tools → backend limit hit
- If stops earlier → prompt issue (check anti-patterns)

**Common Issues**:

| Symptom | Cause | Fix |
|---------|-------|-----|
| Stops at exactly 10 tools | Backend limit | Set `WEBTOOL_MAX_TOOL_CALLS=20` |
| Stops after 2-3 tools | Model not following instructions | Check LM Studio temp/top-p, verify persona loaded |
| Ignores initial prompt | Context overflow | Reduce sysprompt.md size or increase context window |
| Asks "should I continue?" | Weak autonomy instructions | Enhanced persona now includes explicit anti-pattern |

## Rollback

If the enhanced persona is too aggressive:

**Moderate version** (presets.ts):
```typescript
researcher: `
ROLE: Deep Researcher
- Research protocol: Search → Outline → Fetch best chunks → Synthesize
- Minimum: 4-6 tool calls from 3+ diverse authoritative sources
- Continue autonomously until sufficient coverage
- Provide structured reports with citations and images
- Source priority: official docs > papers > industry reports > blogs`
```

## Next Steps

1. ✅ Enhanced persona instructions deployed
2. ⏳ Set `WEBTOOL_MAX_TOOL_CALLS=20` environment variable
3. ⏳ Test with sample research query
4. ⏳ Monitor tool call count and report quality
5. Optional: Implement persona-specific limits in app.py

---

**Summary**: The enhanced Deep Researcher persona now has explicit autonomy instructions, clear research protocol, minimum requirements, and anti-patterns to avoid premature stopping. Combined with increased tool call limit, this should resolve all three issues you described.
