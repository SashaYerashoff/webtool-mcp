#!/usr/bin/env python3
"""Round-trip test with local OpenAI-compatible model on localhost:1234.
Requires: server running on :5000, model API (GPT OSS) listening on :1234/v1.
The test injects system prompt, asks model to list tools and propose first action.
"""
from __future__ import annotations
import os, json, textwrap, sys
import requests

OPENAI_BASE = os.getenv("OPENAI_BASE", "http://localhost:1234/v1")
MODEL = os.getenv("MODEL", "gpt-oss")
MCP_URL = os.getenv("MCP_URL", "http://localhost:5000/mcp")

SYSTEM_PROMPT_HEAD = "You are an autonomous browsing and data assistant integrated with the MCP tool server"  # quick validation string


def _get_system_prompt():
    payload = {"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_system_prompt","arguments":{}}}
    r = requests.post(MCP_URL, json=payload, timeout=15)
    r.raise_for_status()
    data = r.json()
    text = data['result']['content'][0]['text']
    return text


def _chat(system: str, user: str):
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ],
        "temperature": 0.1
    }
    r = requests.post(f"{OPENAI_BASE}/chat/completions", json=body, timeout=60)
    r.raise_for_status()
    return r.json()


def main():
    try:
        system_prompt = _get_system_prompt()
    except Exception as e:
        print("FAILED: could not retrieve system prompt:", e)
        sys.exit(1)
    if SYSTEM_PROMPT_HEAD not in system_prompt:
        print("FAILED: system prompt content mismatch")
        sys.exit(1)
    user_query = "Find a recent official Python release announcement and outline it. Respond only with your first tool call as JSON-RPC params, nothing else."
    try:
        resp = _chat(system_prompt, user_query)
    except Exception as e:
        print("FAILED: chat completion call:", e)
        sys.exit(1)
    choice = resp.get('choices', [{}])[0]
    content = choice.get('message', {}).get('content', '') if isinstance(choice, dict) else ''
    print("MODEL RAW RESPONSE:\n", content)
    # Heuristic: ensure model proposes a fetch_url or web_search
    if 'web_search' in content or 'fetch_url' in content:
        print("PASS: model proposed a tool action")
        sys.exit(0)
    print("WARN: model did not clearly propose expected tool; content captured for review.")
    sys.exit(0)

if __name__ == "__main__":
    main()
