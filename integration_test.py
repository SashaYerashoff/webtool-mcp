#!/usr/bin/env python3
"""Basic integration smoke tests for webtool-mcp server.
Run server first (python app.py) or rely on background instance.
"""
from __future__ import annotations
import json, sys, time
import requests

BASE = "http://localhost:5000/mcp"

failures = []

def jrpc(method: str, id_: int, params: dict | None = None):
    payload = {"jsonrpc":"2.0","id":id_,"method":method}
    if params is not None:
        payload["params"] = params
    r = requests.post(BASE, json=payload, timeout=15)
    r.raise_for_status()
    return r.json()

print("[1] tools/list")
try:
    data = jrpc("tools/list", 1)
    tools = {t['name'] for t in data['result']['tools']}
    assert 'fetch_url' in tools and 'quick_search' in tools, "Required tools missing"
    print("  tools ok (", ", ".join(sorted(list(tools))[:8]), ")")
except Exception as e:
    failures.append(f"tools/list failed: {e}")

print("[2] fetch_url outline cache test")
try:
    outline1 = jrpc("tools/call", 2, {"name":"fetch_url","arguments":{"url":"https://example.com","mode":"outline"}})
    text1 = outline1['result']['content'][0]['text']
    assert 'Example Domain' in text1, 'outline missing content'
    outline2 = jrpc("tools/call", 3, {"name":"fetch_url","arguments":{"url":"https://example.com","mode":"outline"}})
    text2 = outline2['result']['content'][0]['text']
    assert 'cache_status:' in text2, 'expected cache_status on second call'
    print("  outline + cache ok")
except Exception as e:
    failures.append(f"fetch_url outline failed: {e}")

print("[3] quick_search")
try:
    qs = jrpc("tools/call", 4, {"name":"quick_search","arguments":{"query":"open source vector database"}})
    body = qs['result']['content'][0]['text']
    data = json.loads(body)
    assert data.get('results'), 'quick_search returned no results'
    print("  quick_search returned", len(data['results']), "results")
except Exception as e:
    failures.append(f"quick_search failed: {e}")

print("[4] latvian_news (may timeout)")
try:
    news = jrpc("tools/call", 5, {"name":"latvian_news","arguments":{}})
    txt = news['result']['content'][0]['text']
    if 'error' in txt.lower():
        print("  latvian_news reported error (non-fatal):", txt[:120])
    else:
        print("  latvian_news ok")
except Exception as e:
    failures.append(f"latvian_news failed: {e}")

if failures:
    print("\nFAILURES:")
    for f in failures:
        print(" -", f)
    sys.exit(1)
print("\nAll integration smoke tests passed (allowing latvian_news transient issues).")
