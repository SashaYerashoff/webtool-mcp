#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Flask MCP server fetch any URL, Wikipedia summary or Latvian news.
"""

from flask import Flask, request, jsonify, Response
import requests
import xml.etree.ElementTree as ET
import time
import json
from bs4 import BeautifulSoup
from bs4.element import Tag
from bs4 import NavigableString
import re
from urllib.parse import urljoin, urlparse, quote_plus
from typing import cast  # added
import os
import typing
import threading
from collections import deque, OrderedDict
import uuid
from dataclasses import dataclass
import sqlite3
import base64
import io

# Optional lightweight RAG deps
try:
    from pypdf import PdfReader  # type: ignore
    from rank_bm25 import BM25Okapi  # type: ignore
    # Optional semantic embeddings (only used if available)
    try:
        import numpy as _np  # type: ignore
        from sentence_transformers import SentenceTransformer  # type: ignore
        try:
            from sentence_transformers import CrossEncoder  # type: ignore
        except Exception:
            CrossEncoder = None  # type: ignore
    except Exception:
        _np = None  # type: ignore
        SentenceTransformer = None  # type: ignore
        CrossEncoder = None  # type: ignore
except Exception:  # graceful fallback if not installed
    PdfReader = None  # type: ignore
    BM25Okapi = None  # type: ignore

app = Flask(__name__)

# Optional vision deps (SigLIP via transformers, Pillow for image IO, pytesseract for OCR)
try:
    from PIL import Image, ImageOps, ImageFilter  # type: ignore
except Exception:
    try:
        from PIL import Image  # type: ignore
        ImageOps = None  # type: ignore
        ImageFilter = None  # type: ignore
    except Exception:
        Image = None  # type: ignore
        ImageOps = None  # type: ignore
        ImageFilter = None  # type: ignore
try:
    import torch  # type: ignore
    from transformers import AutoProcessor, AutoModel  # type: ignore
except Exception:
    torch = None  # type: ignore
    AutoProcessor = None  # type: ignore
    AutoModel = None  # type: ignore
try:
    import pytesseract  # type: ignore
except Exception:
    pytesseract = None  # type: ignore

# Early small helper used by search helpers before full parsing helpers are defined later
def _collapse(text: str) -> str:
    try:
        return re.sub(r"\s+", " ", text or "").strip()
    except Exception:
        return (text or "").strip()

# System prompt loader (reads from sysprompt.md)
_SYSPROMPT_PATH = os.path.join(os.path.dirname(__file__), 'sysprompt.md')
LM_STUDIO_BASE = os.environ.get("LM_STUDIO_BASE", "http://localhost:1234")

# Simple in-memory session store for integrated proxy (avoids FastAPI when Python 3.13 pydantic build fails)
_CHAT_SESSIONS: dict[str, list[dict]] = {}
_TOOL_JSON_RE = re.compile(r'^\{\s*"name"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:\s*\{.*\}\s*\}\s*$', re.DOTALL)

def _extract_tool_json(raw: str) -> str | None:
    """Extract a JSON tool call object from model text (handles code fences & noise)."""
    if not raw:
        return None
    text = raw.strip()
    # Remove control tokens like <|...|>
    text = re.sub(r'<\|[^>]+\|>', '', text).strip()
    # Code fence first
    fence = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text)
    if fence:
        candidate = fence.group(1).strip()
        if _TOOL_JSON_RE.match(candidate):
            return candidate
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict) and 'name' in obj and 'arguments' in obj:
                return json.dumps(obj)
        except Exception:
            pass
    # Whole text
    if _TOOL_JSON_RE.match(text):
        return text
    # Heuristic scan for first JSON object containing name & arguments
    idx = text.find('"name"')
    while idx != -1:
        start = text.rfind('{', 0, idx)
        if start == -1:
            break
        depth = 0
        for j in range(start, len(text)):
            ch = text[j]
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    snippet = text[start:j+1].strip()
                    if '"arguments"' in snippet:
                        try:
                            obj = json.loads(snippet)
                            if isinstance(obj, dict) and 'name' in obj and 'arguments' in obj:
                                return json.dumps(obj)
                        except Exception:
                            pass
                    break
        idx = text.find('"name"', idx + 6)
    return None

def _extract_all_tool_jsons(raw: str) -> list[str]:
    """Extract all tool-call JSON objects (as JSON strings) in document order.
    Handles fenced blocks first, then scans raw text for balanced JSON objects containing name & arguments.
    """
    if not raw:
        return []
    text = re.sub(r'<\|[^>]+\|>', '', raw).strip()
    results: list[str] = []
    used_spans: list[tuple[int,int]] = []
    # Fenced blocks
    for m in re.finditer(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text):
        candidate = m.group(1).strip()
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict) and 'name' in obj and 'arguments' in obj:
                results.append(json.dumps(obj))
                used_spans.append((m.start(), m.end()))
        except Exception:
            continue
    # Mask fenced spans to avoid double-parsing
    masked = []
    last = 0
    for s,e in sorted(used_spans):
        masked.append(text[last:s])
        masked.append(' ' * (e - s))
        last = e
    masked.append(text[last:])
    masked_text = ''.join(masked)
    # Raw scan similar to _extract_tool_json
    idx = masked_text.find('"name"')
    while idx != -1:
        start = masked_text.rfind('{', 0, idx)
        if start == -1:
            break
        depth = 0
        end = -1
        for j in range(start, len(masked_text)):
            ch = masked_text[j]
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    end = j + 1
                    break
        if end != -1:
            snippet = masked_text[start:end].strip()
            if '"arguments"' in snippet:
                try:
                    obj = json.loads(snippet)
                    if isinstance(obj, dict) and 'name' in obj and 'arguments' in obj:
                        results.append(json.dumps(obj))
                except Exception:
                    pass
        idx = masked_text.find('"name"', idx + 6)
    return results

# -------------------- Pairs storage (SQLite) --------------------
_DB_PATH = os.getenv("WEBTOOL_DB", os.path.join(os.path.dirname(__file__), "pairs.db"))
_DB_LOCK = threading.Lock()

def _db_conn():
    return sqlite3.connect(_DB_PATH, check_same_thread=False)

def _db_init():
    with _DB_LOCK:
        con = _db_conn()
        try:
            cur = con.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS pairs (
                  id TEXT PRIMARY KEY,
                  created_at INTEGER,
                  agent_type TEXT,
                  user_request TEXT,
                  model_response TEXT,
                  thinking TEXT,
                  tool_use_log_json TEXT,
                  parent_pair_id TEXT,
                  topic TEXT,
                  url_citations_json TEXT,
                  tokens_est INTEGER
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS pair_emb (
                    id TEXT PRIMARY KEY,
                    vec TEXT
                )
                """
            )
            # Annotations for fine-tuning: span-level feedback on pairs
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS pair_annotations (
                    id TEXT PRIMARY KEY,
                    pair_id TEXT NOT NULL,
                    created_at INTEGER,
                    target TEXT DEFAULT 'model_response',
                    start INTEGER,
                    end INTEGER,
                    text TEXT,
                    sentiment TEXT,
                    tags_json TEXT,
                    note TEXT,
                    rating INTEGER,
                    FOREIGN KEY(pair_id) REFERENCES pairs(id)
                )
                """
            )
            # Vision: indexed images with optional OCR/tags
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS vision_items (
                    id TEXT PRIMARY KEY,
                    created_at INTEGER,
                    src_url TEXT,
                    mime TEXT,
                    width INTEGER,
                    height INTEGER,
                    ocr_text TEXT,
                    tags_json TEXT,
                    meta_json TEXT
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS vision_emb (
                    id TEXT PRIMARY KEY,
                    vec TEXT
                )
                """
            )
            con.commit()
        finally:
            con.close()

# Initialize DB at import time to avoid decorator type-check noise
try:
    _db_init()
except Exception:
    app.logger.exception("DB init failed")

def _now_ts() -> int:
    return int(time.time())

def _infer_agent_type_from_prompt(system_prompt: str | None) -> str:
    s = (system_prompt or "").lower()
    if "persona: deep researcher" in s or "deep researcher" in s:
        return "researcher"
    if "persona: news" in s or "news crawler" in s or "reporter" in s:
        return "news"
    if "persona: support" in s or "support agent" in s or "luxriot" in s:
        return "support"
    return "unknown"

def _estimate_tokens(txt: str) -> int:
    try:
        return max(1, len((txt or "").split()))
    except Exception:
        return 1

def _guess_topic(user_request: str, model_response: str) -> str:
    req_head = (user_request or "").strip().splitlines()[0][:140]
    if req_head:
        return req_head[:80]
    for line in (model_response or "").splitlines():
        if len(line.strip()) >= 6:
            return line.strip()[:80]
    return ""

def _extract_urls(text: str) -> list[dict]:
    urls = []
    for m in re.finditer(r"https?://[^\s)\]]+", text or ""):
        urls.append({"url": m.group(0)})
    return urls[:12]

_SESSION_LAST_PAIR_ID: dict[str, str] = {}

def _save_reasoning_enabled() -> bool:
    val = (os.getenv("WEBTOOL_SAVE_REASONING", "0") or "").strip().lower()
    return val in {"1","true","yes","on"}

# ---- Simple tokenization for BM25 over pairs ----
_WORD_RE = re.compile(r"\w+", re.UNICODE)
def _tokenize(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text or "") if w]

# ---- Embedding model (optional) ----
_EMB_MODEL = None
def _get_embedding_model():
    global _EMB_MODEL
    if _EMB_MODEL is not None:
        return _EMB_MODEL
    model_name = os.getenv("WEBTOOL_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    try:
        if SentenceTransformer is None:
            return None
        _EMB_MODEL = SentenceTransformer(model_name)
        return _EMB_MODEL
    except Exception as e:
        app.logger.warning(f"Embedding model load failed: {e}")
        _EMB_MODEL = None
        return None

# ---- SigLIP vision model (optional) ----
_VISION_MODEL = None
_VISION_PROCESSOR = None
_VISION_MODEL_NAME = None
def _get_vision_model():
    global _VISION_MODEL, _VISION_PROCESSOR, _VISION_MODEL_NAME
    if _VISION_MODEL is not None and _VISION_PROCESSOR is not None:
        return _VISION_MODEL, _VISION_PROCESSOR
    model_name = os.getenv("WEBTOOL_VISION_MODEL", "google/siglip-so400m-patch14-384")
    if AutoModel is None or AutoProcessor is None or torch is None:
        return None
    try:
        _VISION_PROCESSOR = AutoProcessor.from_pretrained(model_name)
        _VISION_MODEL = AutoModel.from_pretrained(model_name)
        _VISION_MODEL_NAME = model_name
        try:
            _VISION_MODEL.eval()
        except Exception:
            pass
        return _VISION_MODEL, _VISION_PROCESSOR
    except Exception as e:
        app.logger.warning(f"Vision model load failed: {e}")
        _VISION_MODEL = None
        _VISION_PROCESSOR = None
        return None

def _siglip_image_embed(pil_img) -> list[float] | None:
    mp = _get_vision_model()
    if not mp:
        return None
    model, processor = mp
    try:
        import numpy as np  # local optional
        inputs = processor(images=pil_img, return_tensors="pt")
        if torch is not None and hasattr(torch, 'no_grad'):
            with torch.no_grad():
                feats = model.get_image_features(**inputs)
        else:
            feats = model.get_image_features(**inputs)
        # L2 normalize
        v = feats[0].detach().cpu().numpy()
        n = float(np.linalg.norm(v)) or 1.0
        v = (v / n).astype(float)
        return v.tolist()
    except Exception as e:
        app.logger.warning(f"image embed failed: {e}")
        return None

def _siglip_text_embed(text: str) -> list[float] | None:
    mp = _get_vision_model()
    if not mp:
        return None
    model, processor = mp
    try:
        import numpy as np
        inputs = processor(text=[text], padding=True, return_tensors="pt")
        if torch is not None and hasattr(torch, 'no_grad'):
            with torch.no_grad():
                feats = model.get_text_features(**inputs)
        else:
            feats = model.get_text_features(**inputs)
        v = feats[0].detach().cpu().numpy()
        n = float(np.linalg.norm(v)) or 1.0
        v = (v / n).astype(float)
        return v.tolist()
    except Exception as e:
        app.logger.warning(f"text embed failed: {e}")
        return None

def _vision_save_item(src_url: str | None, mime: str | None, w: int | None, h: int | None, ocr_text: str | None, tags: list[str] | None, meta: dict | None, vec: list[float] | None):
    vid = str(uuid.uuid4())
    with _DB_LOCK:
        con = _db_conn()
        try:
            cur = con.cursor()
            cur.execute(
                "INSERT INTO vision_items (id, created_at, src_url, mime, width, height, ocr_text, tags_json, meta_json) VALUES (?,?,?,?,?,?,?,?,?)",
                (vid, _now_ts(), src_url or '', mime or '', w or 0, h or 0, ocr_text or '', json.dumps(tags or [], ensure_ascii=False), json.dumps(meta or {}, ensure_ascii=False))
            )
            if vec is not None:
                try:
                    cur.execute("REPLACE INTO vision_emb (id, vec) VALUES (?,?)", (vid, json.dumps(vec)))
                except Exception:
                    pass
            con.commit()
        finally:
            con.close()
    return vid

def _open_image_from_bytes(data: bytes):
    if Image is None:
        return None
    try:
        return Image.open(io.BytesIO(data)).convert('RGB')
    except Exception:
        return None

def _ocr_image(pil_img) -> str | None:
    """OCR with light preprocessing and multiple Tesseract configs.

    Steps:
    - Flatten alpha to white, grayscale, autocontrast
    - Upscale small images, light denoise
    - Binarize and try psm 6/7/11; fallback to grayscale
    """
    if pytesseract is None or pil_img is None:
        return None
    try:
        img = pil_img
        # Flatten transparency to white background if present
        try:
            if Image is not None and img.mode in ("RGBA", "LA"):
                bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
                img = Image.alpha_composite(bg, img.convert("RGBA")).convert("RGB")
        except Exception:
            pass
        # Convert to grayscale
        try:
            img = img.convert("L")
        except Exception:
            pass
        # Auto-contrast if available
        try:
            if ImageOps is not None:
                img = ImageOps.autocontrast(img)
        except Exception:
            pass
        # Upscale if small to help OCR
        try:
            w, h = img.size
            if max(w, h) < 1000:
                scale = 2 if max(w, h) >= 500 else 3
                img = img.resize((w * scale, h * scale))
        except Exception:
            pass
        # Light denoise
        try:
            if ImageFilter is not None:
                img = img.filter(ImageFilter.MedianFilter(size=3))
        except Exception:
            pass
        # Simple binarization
        try:
            img_bin = img.point(lambda x: 255 if x > 180 else 0, "1")
        except Exception:
            img_bin = img

        configs = [
            "--oem 3 --psm 6 -l eng",
            "--oem 3 --psm 7 -l eng",
            "--oem 3 --psm 11 -l eng",
        ]
        for conf in configs:
            try:
                txt = pytesseract.image_to_string(img_bin, config=conf)
                txt = _collapse(txt)
                if txt:
                    return txt
            except Exception:
                continue
        # Fallback on grayscale without binarization
        try:
            txt = pytesseract.image_to_string(img, config="--oem 3 --psm 6 -l eng")
            txt = _collapse(txt)
            if txt:
                return txt
        except Exception:
            pass
        return ''
    except Exception as e:
        app.logger.warning(f"OCR failed: {e}")
        try:
            return _collapse(pytesseract.image_to_string(pil_img))
        except Exception:
            return None

def save_pair(session_id: str, agent_type: str, user_request: str, model_response: str, thinking: str | None, tool_use_log: list[dict] | None, parent_pair_id: str | None, topic: str | None):
    pid = str(uuid.uuid4())
    item = {
        "id": pid,
        "created_at": _now_ts(),
        "agent_type": agent_type,
        "user_request": user_request,
        "model_response": model_response,
    "thinking": (thinking or "") if _save_reasoning_enabled() else "",
        "tool_use_log_json": json.dumps(tool_use_log or [], ensure_ascii=False),
        "parent_pair_id": parent_pair_id or "",
        "topic": topic or _guess_topic(user_request, model_response),
        "url_citations_json": json.dumps(_extract_urls(model_response), ensure_ascii=False),
        "tokens_est": _estimate_tokens(user_request) + _estimate_tokens(model_response),
    }
    with _DB_LOCK:
        con = _db_conn()
        try:
            cur = con.cursor()
            cur.execute(
                "INSERT INTO pairs (id, created_at, agent_type, user_request, model_response, thinking, tool_use_log_json, parent_pair_id, topic, url_citations_json, tokens_est) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    item["id"], item["created_at"], item["agent_type"], item["user_request"], item["model_response"], item["thinking"], item["tool_use_log_json"], item["parent_pair_id"], item["topic"], item["url_citations_json"], item["tokens_est"],
                ),
            )
            con.commit()
        finally:
            con.close()
    _SESSION_LAST_PAIR_ID[session_id] = pid
    # asynchronously best-effort embed (inline here, quick for MiniLM; in production use a worker)
    try:
        _save_pair_embedding(pid, f"{item['topic']}\n{user_request}\n{model_response}")
    except Exception:
        pass
    return pid

def list_pairs(agent_type: str | None = None, limit: int = 20):
    with _DB_LOCK:
        con = _db_conn()
        try:
            cur = con.cursor()
            if agent_type:
                cur.execute("SELECT id, created_at, agent_type, user_request, model_response, topic FROM pairs WHERE agent_type=? ORDER BY created_at DESC LIMIT ?", (agent_type, limit))
            else:
                cur.execute("SELECT id, created_at, agent_type, user_request, model_response, topic FROM pairs ORDER BY created_at DESC LIMIT ?", (limit,))
            rows = cur.fetchall()
        finally:
            con.close()
    out = []
    for r in rows:
        out.append({
            "id": r[0],
            "created_at": r[1],
            "agent_type": r[2],
            "user_request": r[3],
            "model_response": r[4],
            "topic": r[5],
        })
    return out

def get_pair(pid: str):
    with _DB_LOCK:
        con = _db_conn()
        try:
            cur = con.cursor()
            cur.execute("SELECT id, created_at, agent_type, user_request, model_response, thinking, tool_use_log_json, parent_pair_id, topic, url_citations_json, tokens_est FROM pairs WHERE id=?", (pid,))
            r = cur.fetchone()
        finally:
            con.close()
    if not r:
        return None
    return {
        "id": r[0],
        "created_at": r[1],
        "agent_type": r[2],
        "user_request": r[3],
        "model_response": r[4],
        "thinking": r[5],
        "tool_use_log": json.loads(r[6] or "[]"),
        "parent_pair_id": r[7] or None,
        "topic": r[8],
        "url_citations": json.loads(r[9] or "[]"),
        "tokens_est": r[10],
    }

def delete_pair(pid: str) -> bool:
    with _DB_LOCK:
        con = _db_conn()
        try:
            cur = con.cursor()
            cur.execute("DELETE FROM pairs WHERE id=?", (pid,))
            con.commit()
            return cur.rowcount > 0
        finally:
            con.close()

def _load_sysprompt_file() -> str:
    try:
        with open(_SYSPROMPT_PATH, 'r', encoding='utf-8') as f:
            text = f.read()
        import re as _re
        m = _re.search(r"```\n(.*?)```", text, flags=_re.DOTALL)
        if m:
            block = m.group(1).strip()
            if 'integrated with the MCP tool server' in block:
                return block
        # fallback: find integration line anywhere
        for line in text.splitlines():
            if 'integrated with the MCP tool server' in line:
                # return that line plus following 120 lines as context
                idx = text.splitlines().index(line)
                snippet = "\n".join(text.splitlines()[idx:idx+120])
                return snippet.strip()
        return text.strip()
    except Exception:
        return "You are an autonomous browsing and data assistant integrated with the MCP tool server webtool-mcp. (fallback minimal prompt)"

def get_system_prompt() -> dict:
    prompt = _load_sysprompt_file()
    return {"prompt": prompt, "version": "1.5"}

# -------------------------------------------------------------
# Integrated light proxy endpoints (optional replacement for backend FastAPI)
# -------------------------------------------------------------
def _call_lm_studio(messages: list[dict], model: str | None) -> dict:
    """Call LM Studio OpenAI-compatible chat endpoint; return dict with content and reasoning (non-stream)."""
    try:
        url = LM_STUDIO_BASE.rstrip('/') + '/v1/chat/completions'
        payload = {"messages": messages, "temperature": 0.2}
        if model:
            payload["model"] = model
        r = requests.post(url, json=payload, timeout=60)
        if r.status_code >= 400:
            return {"content": f"LM Studio error {r.status_code}: {r.text[:400]}", "reasoning": ""}
        data = r.json()
        msg = (data.get("choices", [{}])[0] or {}).get("message", {}) or {}
        content = msg.get("content", "") or ""
        reasoning = msg.get("reasoning_content", "") or ""
        return {"content": content, "reasoning": reasoning}
    except Exception as e:
        return {"content": f"LM Studio request failed: {e}"[:500], "reasoning": ""}


def _lm_studio_stream(messages: list[dict], model: str | None):
    """Yield token deltas from LM Studio streaming API. Yields tuples (kind, text) where kind in {"assistant","reasoning"}."""
    url = LM_STUDIO_BASE.rstrip('/') + '/v1/chat/completions'
    payload = {"messages": messages, "temperature": 0.2, "stream": True}
    if model:
        payload["model"] = model
    try:
        with requests.post(url, json=payload, timeout=60, stream=True) as r:
            r.raise_for_status()
            for line in r.iter_lines(decode_unicode=True):
                if not line:
                    continue
                if line.startswith('data: '):
                    data = line[len('data: '):].strip()
                else:
                    # Some servers omit the prefix
                    data = line.strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except Exception:
                    continue
                choice = (obj.get("choices", [{}])[0] or {})
                delta = choice.get("delta") or choice.get("message") or {}
                # OpenAI compatible fields
                if isinstance(delta, dict):
                    if delta.get("content"):
                        yield ("assistant", str(delta.get("content")))
                    # Some models emit reasoning tokens separately
                    if delta.get("reasoning_content"):
                        yield ("reasoning", str(delta.get("reasoning_content")))
    except Exception as e:
        yield ("error", f"LM Studio stream failed: {e}")


def _sse_event(event: str, data: dict | str):
    """Format a Server-Sent Events block (UTF-8 safe)."""
    if isinstance(data, str):
        payload = data
    else:
        payload = json.dumps(data, ensure_ascii=False)
    # SSE requires UTF-8; Flask Response is set with charset. Ensure no stray CRLF
    return f"event: {event}\ndata: {payload}\n\n"

# --- Encoding helpers (mojibake auto-repair) ---
# Expand suspicious set to include Latvian-specific artifacts (Ä, Å) that appear when UTF-8 is mis-decoded
_MOJIBAKE_RE = re.compile(r"[ÃÂÄÅÐÑâœžŸ¢£¥¦§¨©ª«¬®¯°±²³´µ¶·¸¹º»¼½¾¿]")

def _maybe_fix_mojibake_py(text: str) -> str:
    """Best-effort fix for UTF-8 text mis-decoded as Latin-1/Win-1252.
    If suspicious markers found, try latin-1 reencode → utf-8 decode.
    Keep the fix only if it reduces markers or introduces Cyrillic.
    """
    if not isinstance(text, str) or not text:
        return text
    # If it already contains non-Latin1 code points (likely fine), skip
    try:
        if any(ord(ch) > 255 for ch in text):
            return text
    except Exception:
        return text
    if not _MOJIBAKE_RE.search(text):
        return text
    try:
        # If the original already contains Cyrillic, do not attempt to "repair" it
        if re.search(r"[\u0400-\u04FF]", text):
            return text
        raw = text.encode('latin-1', 'ignore')
        fixed = raw.decode('utf-8', 'ignore')
        before = len(_MOJIBAKE_RE.findall(text))
        after = len(_MOJIBAKE_RE.findall(fixed))
        # Accept fix if markers reduced, or if Cyrillic OR Latvian diacritics appear properly
        if (
            after < before
            or re.search(r"[\u0400-\u04FF]", fixed)  # Cyrillic
            or re.search(r"[āčēģīķļņōŗšūžĀČĒĢĪĶĻŅŌŖŠŪŽ]", fixed)  # Latvian letters
        ):
            return fixed
    except Exception:
        pass
    return text

def _fix_args_mojibake(obj):
    if isinstance(obj, dict):
        return {k: _fix_args_mojibake(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_fix_args_mojibake(v) for v in obj]
    if isinstance(obj, str):
        return _maybe_fix_mojibake_py(obj)
    return obj

def _mcp_tool_call(name: str, arguments: dict) -> str:
    """Invoke a tool via internal JSON-RPC call to this same server (loopback)."""
    try:
        rpc = {"jsonrpc":"2.0","id": str(uuid.uuid4()), "method": "tools/call", "params": {"name": name, "arguments": arguments}}
        # Use requests.post to our own /mcp endpoint
        r = requests.post(os.environ.get('WEBTOOL_MCP_BASE','http://localhost:5000/mcp'), json=rpc, timeout=60)
        if r.status_code >= 400:
            return f"tool call HTTP {r.status_code}: {r.text[:400]}"
        data = r.json()
        try:
            return data["result"]["content"][0]["text"][:120000]
        except Exception:
            return json.dumps(data)[:4000]
    except Exception as e:
        return f"tool call failed: {e}"[:500]

@app.after_request
def _cors(resp):
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    return resp

@app.route('/proxy/models', methods=['GET', 'OPTIONS'])
def proxy_models():
    if request.method == 'OPTIONS':
        return ('',204)
    # Try LM Studio list
    try:
        r = requests.get(LM_STUDIO_BASE.rstrip('/') + '/v1/models', timeout=8)
        if r.status_code < 400:
            data = r.json()
            ids = [m.get('id') for m in data.get('data', []) if m.get('id')]
            return jsonify({"models": ids})
    except Exception:
        pass
    return jsonify({"models": ["auto"]})

@app.route('/proxy/chat', methods=['POST','OPTIONS'])
def proxy_chat():
    if request.method == 'OPTIONS':
        return ('',204)
    payload = request.get_json(force=True, silent=True) or {}
    session_id = payload.get('session_id') or str(uuid.uuid4())
    user = (payload.get('user') or '').strip()
    model = payload.get('model') or None
    system_prompt = payload.get('system_prompt') or None
    if not user:
        return jsonify({"error": "user message required"}), 400
    history = _CHAT_SESSIONS.setdefault(session_id, [])
    if system_prompt and not any(m for m in history if m.get('role') == 'system'):
        history.insert(0, {"role": "system", "content": system_prompt})
    history.append({"role": "user", "content": user})
    assistant_res = _call_lm_studio(history, model)
    assistant = assistant_res.get('content','')
    assistant_reasoning = assistant_res.get('reasoning','')
    history.append({"role": "assistant", "content": assistant})
    tool_output = None
    final_assistant = assistant
    final_reasoning = assistant_reasoning
    tool_json = _extract_tool_json(assistant)
    if tool_json:
        try:
            obj = json.loads(tool_json)
            name = obj.get('name')
            arguments = obj.get('arguments') or {}
            if isinstance(name, str):
                tool_output = _mcp_tool_call(name, arguments if isinstance(arguments, dict) else {})
                history.append({"role": "tool", "content": tool_output, "name": name})
                # One follow-up reasoning pass
                final_res = _call_lm_studio(history, model)
                final_assistant = final_res.get('content','')
                final_reasoning = final_res.get('reasoning','')
                history.append({"role": "assistant", "content": final_assistant})
        except Exception as e:
            tool_output = f"Tool parse/exec error: {e}"[:500]
            history.append({"role": "tool", "content": tool_output})
    return jsonify({"session_id": session_id, "assistant": final_assistant, "assistant_reasoning": final_reasoning, "tool_output": tool_output})


@app.route('/proxy/chat_stream', methods=['GET'])
def proxy_chat_stream():
    """SSE streaming chat endpoint.
    Query params: user, session_id?, model?, system_prompt?
    Streams events: session, assistant_token, reasoning_token, assistant_done, tool_start, tool, assistant_final_token, done, error
    """
    user = (request.args.get('user') or '').strip()
    if not user:
        return jsonify({"error": "user message required"}), 400
    session_id = request.args.get('session_id') or str(uuid.uuid4())
    model = request.args.get('model') or None
    system_prompt = request.args.get('system_prompt') or None

    def generate():
        # CORS-friendly initial event
        yield _sse_event('session', {"session_id": session_id})
        history = _CHAT_SESSIONS.setdefault(session_id, [])
        if system_prompt and not any(m for m in history if m.get('role') == 'system'):
            history.insert(0, {"role": "system", "content": system_prompt})
        # Append user
        history.append({"role": "user", "content": user})
        tool_log: list[dict] = []

        # Multi-pass assistant/tool loop
        assistant_content = ''
        reasoning_content = ''
        # First assistant pass (initial tokens)
        for kind, token in _lm_studio_stream(history, model):
            if kind == 'assistant':
                assistant_content += token
                yield _sse_event('assistant_token', {"text": token, "phase": "initial"})
            elif kind == 'reasoning':
                reasoning_content += token
                yield _sse_event('reasoning_token', {"text": token, "phase": "initial"})
            elif kind == 'error':
                yield _sse_event('error', {"message": token})
                return
        yield _sse_event('assistant_done', {"phase": "initial"})
        history.append({"role": "assistant", "content": assistant_content})

        final_assistant = assistant_content
        final_reasoning = reasoning_content
        tool_text = None

        # Iterate tool→assistant cycles up to a safe maximum
        try:
            env_max = int(os.environ.get('WEBTOOL_MAX_TOOL_CALLS', '10'))
        except Exception:
            env_max = 10
        MAX_TOOL_CALLS = max(1, min(15, env_max))
        calls = 0
        while calls < MAX_TOOL_CALLS:
            # Collect all tool calls in the latest assistant text, in order
            tool_calls = []
            for tj in _extract_all_tool_jsons(final_assistant):
                try:
                    obj = json.loads(tj)
                except Exception:
                    continue
                name = obj.get('name')
                arguments = obj.get('arguments') or {}
                if isinstance(name, str):
                    tool_calls.append((name, arguments if isinstance(arguments, dict) else {}))
            if not tool_calls:
                break
            # Execute each tool call (sequential to preserve order; could parallelize with caution)
            for name, arguments in tool_calls:
                if calls >= MAX_TOOL_CALLS:
                    break
                calls += 1
                try:
                    yield _sse_event('tool_start', {"name": name, "arguments": arguments})
                    tool_text = _mcp_tool_call(name, arguments)
                    yield _sse_event('tool', {"name": name, "content": tool_text})
                    try:
                        tool_log.append({"name": name, "arguments": arguments, "content_preview": (tool_text or "")[:500]})
                    except Exception:
                        pass
                    # Append as a tool message so the model can read it next round
                    history.append({"role": "tool", "content": tool_text, "name": name})
                except Exception as e:
                    err = f"Tool exec error: {e}"[:500]
                    yield _sse_event('tool', {"error": err})
                    history.append({"role": "tool", "content": err})

            # Ask the model again after appending all tool outputs
            final_assistant = ''
            final_reasoning = ''
            for kind, token in _lm_studio_stream(history, model):
                if kind == 'assistant':
                    final_assistant += token
                    yield _sse_event('assistant_final_token', {"text": token})
                elif kind == 'reasoning':
                    final_reasoning += token
                    yield _sse_event('reasoning_token', {"text": token, "phase": "final"})
                elif kind == 'error':
                    yield _sse_event('error', {"message": token})
                    return
            history.append({"role": "assistant", "content": final_assistant})

        # Persist pair and Done summary
        try:
            agent_type = _infer_agent_type_from_prompt(system_prompt)
            parent = _SESSION_LAST_PAIR_ID.get(session_id)
            new_pid = save_pair(session_id, agent_type, user, final_assistant, final_reasoning or None, tool_log, parent, topic=None)
        except Exception:
            app.logger.exception("save_pair failed")
            new_pid = None
        # Done summary (tool_output omitted to prevent duplication in UI)
        yield _sse_event('done', {
            "session_id": session_id,
            "assistant": final_assistant,
            "assistant_reasoning": final_reasoning,
            "tool_output": None,
            "pair_id": new_pid
        })

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
        "Content-Type": "text/event-stream; charset=utf-8"
    }
    return Response(generate(), headers=headers)

@app.route('/proxy/session/<sid>', methods=['GET'])
def proxy_session(sid: str):
    return jsonify({"session_id": sid, "messages": _CHAT_SESSIONS.get(sid, [])})

@app.get('/pairs')
def http_list_pairs():
    agent = request.args.get('agent') or None
    try:
        limit = int(request.args.get('limit') or '20')
    except Exception:
        limit = 20
    return jsonify({"items": list_pairs(agent, limit=limit)})

@app.get('/pairs/<pid>')
def http_get_pair(pid: str):
    item = get_pair(pid)
    if not item:
        return jsonify({"error": "not found"}), 404
    return jsonify(item)

@app.delete('/pairs/<pid>')
def http_delete_pair(pid: str):
    ok = delete_pair(pid)
    if not ok:
        return jsonify({"deleted": False, "error": "not found"}), 404
    return jsonify({"deleted": True, "id": pid})

@app.get('/pairs/with_annotations')
def http_pairs_with_annotations():
    sentiment = (request.args.get('sentiment') or '').strip().lower()  # '', 'positive', 'negative'
    agent = request.args.get('agent') or None
    try:
        limit = int(request.args.get('limit') or '20')
    except Exception:
        limit = 20
    with _DB_LOCK:
        con = _db_conn()
        try:
            cur = con.cursor()
            base_sql = (
                "SELECT p.id, p.created_at, p.agent_type, p.user_request, p.model_response, p.topic, COUNT(a.id) as acount "
                "FROM pairs p JOIN pair_annotations a ON a.pair_id = p.id "
            )
            where = []
            params: list[typing.Any] = []
            if agent:
                where.append("p.agent_type = ?")
                params.append(agent)
            if sentiment in ("positive", "negative"):
                where.append("(a.sentiment = ?)")
                params.append(sentiment)
            sql = base_sql
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " GROUP BY p.id ORDER BY p.created_at DESC LIMIT ?"
            params.append(limit)
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
        finally:
            con.close()
    items = []
    for r in rows:
        items.append({
            "id": r[0],
            "created_at": r[1],
            "agent_type": r[2],
            "user_request": r[3],
            "model_response": r[4],
            "topic": r[5],
            "annotation_count": r[6],
        })
    return jsonify({"items": items, "sentiment": sentiment or "any"})

@app.post('/pairs/<pid>/annotations')
def http_create_annotation(pid: str):
    body = request.get_json(silent=True) or {}
    # Validate pair exists
    if not get_pair(pid):
        return jsonify({"error": "pair not found"}), 404
    ann_id = str(uuid.uuid4())
    created_at = _now_ts()
    target = str(body.get('target') or 'model_response')
    start = body.get('start')
    end = body.get('end')
    try:
        start_i = int(start) if start is not None else None
        end_i = int(end) if end is not None else None
    except Exception:
        return jsonify({"error": "start/end must be integers"}), 400
    text = str(body.get('text') or '')
    sentiment = str(body.get('sentiment') or '')  # 'positive' | 'negative' | ''
    tags = body.get('tags') or []
    if not isinstance(tags, list):
        tags = []
    try:
        tags_json = json.dumps([str(t) for t in tags], ensure_ascii=False)
    except Exception:
        tags_json = json.dumps([])
    note = str(body.get('note') or '')
    rating_val = body.get('rating')
    try:
        if rating_val is None or str(rating_val).strip() == "":
            rating = None
        else:
            rating = int(str(rating_val))
    except Exception:
        rating = None
    with _DB_LOCK:
        con = _db_conn()
        try:
            cur = con.cursor()
            cur.execute(
                "INSERT INTO pair_annotations (id, pair_id, created_at, target, start, end, text, sentiment, tags_json, note, rating) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (ann_id, pid, created_at, target, start_i, end_i, text, sentiment, tags_json, note, rating)
            )
            con.commit()
        finally:
            con.close()
    return jsonify({
        "id": ann_id,
        "pair_id": pid,
        "created_at": created_at,
        "target": target,
        "start": start_i,
        "end": end_i,
        "text": text,
        "sentiment": sentiment,
        "tags": json.loads(tags_json),
        "note": note,
        "rating": rating,
    })

@app.get('/pairs/<pid>/annotations')
def http_list_annotations(pid: str):
    with _DB_LOCK:
        con = _db_conn()
        try:
            cur = con.cursor()
            cur.execute("SELECT id, created_at, target, start, end, text, sentiment, tags_json, note, rating FROM pair_annotations WHERE pair_id=? ORDER BY created_at DESC", (pid,))
            rows = cur.fetchall()
        finally:
            con.close()
    items = []
    for r in rows:
        items.append({
            "id": r[0],
            "pair_id": pid,
            "created_at": r[1],
            "target": r[2],
            "start": r[3],
            "end": r[4],
            "text": r[5],
            "sentiment": r[6],
            "tags": json.loads(r[7] or "[]"),
            "note": r[8],
            "rating": r[9],
        })
    return jsonify({"items": items})

@app.delete('/pairs/<pid>/annotations/<ann_id>')
def http_delete_annotation(pid: str, ann_id: str):
    with _DB_LOCK:
        con = _db_conn()
        try:
            cur = con.cursor()
            cur.execute("DELETE FROM pair_annotations WHERE id=? AND pair_id=?", (ann_id, pid))
            con.commit()
            ok = cur.rowcount > 0
        finally:
            con.close()
    if not ok:
        return jsonify({"deleted": False, "error": "not found"}), 404
    return jsonify({"deleted": True, "id": ann_id})

@app.post('/pairs/search')
def http_search_pairs():
    body = request.get_json(silent=True) or {}
    q = (body.get('q') or body.get('query') or '').strip()
    agent = (body.get('agent') or None)
    limit = int(body.get('limit') or 20)
    if not q:
        return jsonify({"items": list_pairs(agent, limit=limit)})
    pattern = f"%{q.replace('%','').replace('_','')}%"
    with _DB_LOCK:
        con = _db_conn()
        try:
            cur = con.cursor()
            if agent:
                cur.execute("SELECT id, created_at, agent_type, user_request, model_response, topic FROM pairs WHERE agent_type=? AND (user_request LIKE ? OR model_response LIKE ? OR topic LIKE ?) ORDER BY created_at DESC LIMIT ?", (agent, pattern, pattern, pattern, limit))
            else:
                cur.execute("SELECT id, created_at, agent_type, user_request, model_response, topic FROM pairs WHERE (user_request LIKE ? OR model_response LIKE ? OR topic LIKE ?) ORDER BY created_at DESC LIMIT ?", (pattern, pattern, pattern, limit))
            rows = cur.fetchall()
        finally:
            con.close()
    items = []
    for r in rows:
        items.append({"id": r[0], "created_at": r[1], "agent_type": r[2], "user_request": r[3], "model_response": r[4], "topic": r[5]})
    return jsonify({"items": items, "query": q})

def _pair_text_for_index(item: dict) -> str:
    return f"{item.get('topic','')}\n{item.get('user_request','')}\n{item.get('model_response','')}"

def _embed_text(text: str):
    model = _get_embedding_model()
    if not model:
        return None
    try:
        vec = model.encode([text])[0]
        # return as list[float] for cosine
        return vec.tolist() if hasattr(vec, 'tolist') else list(vec)
    except Exception as e:
        app.logger.warning(f"embed failed: {e}")
        return None

def _cosine(a: list[float], b: list[float]) -> float:
    try:
        import math
        if not a or not b or len(a)!=len(b):
            return 0.0
        dot = sum(x*y for x,y in zip(a,b))
        na = math.sqrt(sum(x*x for x in a))
        nb = math.sqrt(sum(y*y for y in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot/(na*nb)
    except Exception:
        return 0.0

def _load_pair_embeddings(ids: list[str]) -> dict[str, list[float]]:
    if not ids:
        return {}
    with _DB_LOCK:
        con = _db_conn()
        try:
            cur = con.cursor()
            qmarks = ','.join(['?']*len(ids))
            cur.execute(f"SELECT id, vec FROM pair_emb WHERE id IN ({qmarks})", tuple(ids))
            rows = cur.fetchall()
        finally:
            con.close()
    out: dict[str, list[float]] = {}
    for pid, vec_json in rows:
        try:
            out[pid] = json.loads(vec_json)
        except Exception:
            continue
    return out

def _save_pair_embedding(pid: str, text: str):
    vec = _embed_text(text)
    if vec is None:
        return
    with _DB_LOCK:
        con = _db_conn()
        try:
            cur = con.cursor()
            cur.execute("REPLACE INTO pair_emb (id, vec) VALUES (?,?)", (pid, json.dumps(vec)))
            con.commit()
        finally:
            con.close()

@app.post('/pairs/search_hybrid')
def http_search_pairs_hybrid():
    body = request.get_json(silent=True) or {}
    q = (body.get('q') or body.get('query') or '').strip()
    agent = (body.get('agent') or None)
    limit = int(body.get('limit') or 20)
    if not q:
        return jsonify({"items": list_pairs(agent, limit=limit)})
    # Load recent N candidates then score
    pool = list_pairs(agent, limit=200)
    tokens_q = set(_tokenize(q))
    # Try embedding query
    qvec = _embed_text(q)
    # Load vectors for pool
    pool_ids = [it['id'] for it in pool]
    vecs = _load_pair_embeddings(pool_ids)
    scored: list[tuple[float, dict]] = []
    for it in pool:
        text = _pair_text_for_index(it)
        # term overlap heuristic (BM25-lite)
        toks = set(_tokenize(text))
        overlap = len(tokens_q & toks)
        bm25_like = overlap / max(1, len(tokens_q))
        # embedding cosine
        cos = 0.0
        v = vecs.get(it['id'])
        if v is None and qvec is not None:
            # lazily build and store embedding for this item
            _save_pair_embedding(it['id'], text)
            v = _load_pair_embeddings([it['id']]).get(it['id'])
        if v is not None and qvec is not None:
            cos = _cosine(qvec, v)
        # hybrid score
        score = 0.6 * cos + 0.4 * bm25_like
        scored.append((score, it))
    scored.sort(key=lambda x: x[0], reverse=True)
    items = [it for _, it in scored[:limit]]
    return jsonify({"items": items, "query": q, "method": "hybrid"})

@app.post('/pairs/attach')
def http_attach_pair():
    body = request.get_json(silent=True) or {}
    pid = (body.get('id') or body.get('pair_id') or '').strip()
    session_id = (body.get('session_id') or '').strip()
    if not pid or not session_id:
        return jsonify({"error": "id and session_id required"}), 400
    item = get_pair(pid)
    if not item:
        return jsonify({"error": "pair not found"}), 404
    # Insert as separate messages to mirror actual conversation
    hist = _CHAT_SESSIONS.setdefault(session_id, [])
    ur = item.get('user_request') or ''
    mr = item.get('model_response') or ''
    if ur:
        hist.append({"role": "user", "content": ur})
    if mr:
        hist.append({"role": "assistant", "content": mr})
    return jsonify({"attached": True, "session_id": session_id, "pair_id": pid})

@app.route('/proxy/tool', methods=['POST', 'OPTIONS'])
def proxy_tool():
    """Direct tool invocation for the UI. Body: { name: str, arguments?: dict }
    Returns: { name, content } where content is tool textual output.
    """
    if request.method == 'OPTIONS':
        return ('', 204)
    payload = request.get_json(force=True, silent=True) or {}
    name = (payload.get('name') or '').strip()
    arguments = payload.get('arguments') or {}
    if not isinstance(arguments, dict):
        arguments = {}
    if not name:
        return jsonify({"error": "name required"}), 400
    try:
        content = _mcp_tool_call(name, arguments)
        return jsonify({"name": name, "content": content})
    except Exception as e:
        return jsonify({"error": f"tool error: {e}"}), 500

# ------------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------------

def _decode_html_response(resp: requests.Response) -> str:
    """Decode HTML bytes to str safely to avoid mojibake (â¦ issues).
    Order: server-declared (if not latin-1 default) -> apparent_encoding -> utf-8 -> windows-1252 -> latin-1.
    Additionally attempt latin1->utf8 roundtrip fix when telltale sequences appear.
    """
    data = resp.content or b""
    cand: list[str] = []
    enc = (resp.encoding or "").lower()
    if enc and enc not in {"iso-8859-1", "latin-1"}:
        cand.append(enc)
    try:
        app_enc = getattr(resp, "apparent_encoding", None)
        if app_enc and app_enc.lower() not in {c.lower() for c in cand}:
            cand.append(app_enc)
    except Exception:
        pass
    for e in ("utf-8", "windows-1252", "latin-1"):
        if e not in cand:
            cand.append(e)
    def _roundtrip_fix(txt: str) -> str:
        # If the decoded text already contains Cyrillic, do not attempt latin1->utf8 repair,
        # as that would drop non-Latin characters.
        try:
            if re.search(r"[\u0400-\u04FF]", txt):
                return txt
        except Exception:
            pass
        if "â" in txt or "Ã" in txt or "Ä" in txt or "Å" in txt:
            try:
                fixed = txt.encode("latin1", errors="ignore").decode("utf-8", errors="ignore")
                # Only keep if it reduces mojibake markers and does not drastically shrink text
                if (
                    (fixed.count("â") + fixed.count("Ã") + fixed.count("Ä") + fixed.count("Å"))
                    < (txt.count("â") + txt.count("Ã") + txt.count("Ä") + txt.count("Å"))
                    and len(fixed) > len(txt) * 0.5
                ) or re.search(r"[āčēģīķļņōŗšūžĀČĒĢĪĶĻŅŌŖŠŪŽ]", fixed) or re.search(r"[\u0400-\u04FF]", fixed):
                    return fixed
            except Exception:
                pass
        return txt
    for e in cand:
        try:
            text = data.decode(e, errors="strict")
            return _roundtrip_fix(text)
        except Exception:
            continue
    # Fallback with replacement
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:
        text = data.decode("latin-1", errors="replace")
    return _roundtrip_fix(text)


def fetch_url(url: str) -> dict:
    """Return raw HTML of the requested URL (robust decoding)."""
    try:
        resp = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0 (compatible; webtool-mcp/1.0)"})
        resp.raise_for_status()
        return {"content": _decode_html_response(resp)}
    except requests.RequestException as exc:
        return {"error": f"Could not fetch {url}: {exc}"}


def search_wikipedia(query: str) -> dict:
    """Get a short summary from Wikipedia REST API."""
    api_url = (
        f"https://en.wikipedia.org/api/rest_v1/page/summary/{query.replace(' ', '_')}"
    )
    try:
        resp = requests.get(api_url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        return {
            "title": data.get("title"),
            "description": data.get("description"),
            "extract": data.get("extract"),
            "url": data.get("content_urls", {}).get("desktop", {}).get("page"),
        }
    except requests.RequestException as exc:
        return {"error": f"Wikipedia fetch failed: {exc}"}


def search_duckduckgo(query: str, max_results: int = 5) -> dict:
    """Improved DuckDuckGo search.
    1) Try duckduckgo_search library for organic results.
    2) Fallback to lightweight HTML scrape.
    3) Finally fallback to Instant Answer API (may be sparse for long-tail queries).
    """
    if not query:
        return {"error": "Empty query"}
    results = []
    # Attempt library (organic results)
    try:
        from duckduckgo_search import DDGS  # type: ignore
        with DDGS() as ddgs:  # context manager handles cookies
            for r in ddgs.text(query, max_results=max_results):
                if not isinstance(r, dict):
                    continue
                title = r.get("title") or r.get("heading")
                url = r.get("href") or r.get("url")
                snippet = r.get("body") or r.get("abstract")
                if title and url:
                    results.append({"title": title, "url": url, "snippet": snippet})
        if results:
            return {
                "query": query,
                "engine": "duckduckgo",
                "results": results,
                "source": "duckduckgo_search library",
            }
    except ImportError:
        pass  # fallback below
    except Exception as exc:
        # Non-fatal; include note and fallback
        fallback_note = f"organic_error: {exc}"[:180]
    # If library failed or empty, attempt lightweight HTML scraping (best-effort; may break)
    if not results:
        try:
            r = requests.get("https://duckduckgo.com/html/", params={"q": query}, timeout=10, headers={"User-Agent": "Mozilla/5.0 webtool-mcp"})
            r.raise_for_status()
            s = BeautifulSoup(r.text, 'html.parser')
            for a in s.select('a.result__a'):
                title = _collapse(a.get_text(' '))[:240]
                href = a.get('href')
                snippet_tag = a.find_parent('div', class_='result__body')
                snippet = ''
                if snippet_tag:
                    sn = snippet_tag.select_one('.result__snippet')
                    if sn:
                        snippet = _collapse(sn.get_text(' '))[:400]
                if title and href:
                    results.append({"title": title, "url": href, "snippet": snippet})
                if len(results) >= max_results:
                    break
            if results:
                return {"query": query, "engine": "duckduckgo_html", "results": results, "source": "duckduckgo html scrape"}
        except Exception:
            pass
    # Fallback to Instant Answer
    url = "https://api.duckduckgo.com/"
    params = {"q": query, "format": "json", "no_html": 1, "skip_disambig": 1, "t": "webtool-mcp"}
    try:
        resp = requests.get(url, params=params, timeout=7)
        resp.raise_for_status()
        data = resp.json()
        abstract = data.get("Abstract") or data.get("AbstractText")
        heading = data.get("Heading")
        related = []
        for topic in data.get("RelatedTopics", [])[: max_results]:
            if isinstance(topic, dict):
                txt = topic.get("Text")
                first_url = topic.get("FirstURL")
                if txt and first_url:
                    related.append({"title": txt, "url": first_url})
        payload = {"query": query, "engine": "duckduckgo_instant", "heading": heading, "abstract": abstract, "related": related, "source": "DuckDuckGo Instant Answer"}
        if not abstract and not related:
            payload["note"] = "Instant Answer returned minimal data; consider alternate engine via web_search tool."
        return payload
    except requests.RequestException as exc:
        return {"error": f"DuckDuckGo request failed: {exc}"}


def web_search(query: str, engine: str = "duckduckgo", max_results: int = 5, engines: list[str] | None = None) -> dict:
    """Unified multi-engine web search.

    Supported engines:
      - duckduckgo (library for organic results)
      - bing (HTML scrape lightweight; may be brittle)
      - google_cse (requires env GOOGLE_API_KEY + GOOGLE_CSE_ID)
      - multi (provide list via engines=[...])
    """
    if not query:
        return {"error": "Empty query"}
    engine = (engine or "duckduckgo").lower()

    def _bing(q: str) -> list[dict]:
        search_url = "https://www.bing.com/search"
        try:
            r = requests.get(search_url, params={"q": q}, timeout=10, headers={"User-Agent": "Mozilla/5.0 webtool-mcp"})
            r.raise_for_status()
            s = BeautifulSoup(r.text, "html.parser")
            out = []
            for li in s.select("li.b_algo"):
                a = li.select_one("h2 a")
                if not a or not a.get("href"):
                    continue
                title = _collapse(a.get_text(" "))[:240]
                url2 = a.get("href")
                snippet_tag = li.select_one("p") or li.select_one("div.b_caption p")
                snippet = _collapse(snippet_tag.get_text(" "))[:400] if snippet_tag else ""
                if title and url2:
                    out.append({"title": title, "url": url2, "snippet": snippet})
                if len(out) >= max_results:
                    break
            return out
        except Exception as e:
            return [{"error": f"bing_fetch_failed: {e}"}]

    def _google_cse(q: str) -> list[dict]:
        key = os.environ.get("GOOGLE_API_KEY")
        cx = os.environ.get("GOOGLE_CSE_ID")
        if not key or not cx:
            return [{"error": "Missing GOOGLE_API_KEY or GOOGLE_CSE_ID env vars"}]
        try:
            resp = requests.get("https://www.googleapis.com/customsearch/v1", params={"key": key, "cx": cx, "q": q, "num": min(max_results, 10)}, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items") or []
            out = []
            for it in items[:max_results]:
                title = it.get("title")
                link = it.get("link")
                snippet = it.get("snippet")
                if title and link:
                    out.append({"title": title, "url": link, "snippet": snippet})
            return out
        except Exception as e:
            return [{"error": f"google_cse_failed: {e}"}]

    def _duck(q: str) -> list[dict]:
        r = search_duckduckgo(q, max_results=max_results)
        if r.get("results"):
            return r["results"]  # type: ignore
        # Fallback transform of instant answer "related"
        rel = r.get("related") or []
        out = []
        for it in rel:
            title = it.get("title") or it.get("text")
            url2 = it.get("url")
            if title and url2:
                out.append({"title": title, "url": url2, "snippet": r.get("abstract") or ""})
        return out

    if engine == "multi":
        selected = engines or ["duckduckgo", "bing"]
        aggregate = {}
        for eng in selected:
            if eng == "duckduckgo":
                aggregate[eng] = _duck(query)
            elif eng == "bing":
                aggregate[eng] = _bing(query)
            elif eng == "google_cse":
                aggregate[eng] = _google_cse(query)
            else:
                aggregate[eng] = [{"error": "unsupported_engine"}]
        return {"query": query, "engine": "multi", "results": aggregate, "source": "web_search"}

    if engine == "duckduckgo":
        return {"query": query, "engine": engine, "results": _duck(query), "source": "web_search"}
    if engine == "bing":
        return {"query": query, "engine": engine, "results": _bing(query), "source": "web_search"}
    if engine == "google_cse":
        return {"query": query, "engine": engine, "results": _google_cse(query), "source": "web_search"}
    return {"error": f"Unsupported engine '{engine}'", "supported": ["duckduckgo", "bing", "google_cse", "multi"]}


def quick_search(query: str) -> dict:
    """Fast lightweight search (duckduckgo first, fallback to bing) limited to 3 results.
    Intended for initial scoping before deeper multi-engine exploration.
    """
    if not query:
        return {"error": "Empty query"}
    r = web_search(query, engine="duckduckgo", max_results=3)
    results = r.get("results") or []
    if isinstance(results, list) and results:
        return {"query": query, "engine": "duckduckgo", "results": results, "source": "quick_search"}
    # fallback single bing
    r2 = web_search(query, engine="bing", max_results=3)
    return {"query": query, "engine": "bing", "results": r2.get("results"), "source": "quick_search"}


def ai_company_news(companies: list[str] | str | None = None, limit: int = 5, locale: str = "en-US", region: str = "US") -> dict:
    """Aggregate recent news headlines per AI/tech company using Google News RSS.

    Default companies: OpenAI, Google, Anthropic, Microsoft, Nvidia.
    Returns: { company: [ {title,url,published} ] }
    """
    if companies is None or (isinstance(companies, str) and not companies.strip()):
        companies_list = ["OpenAI", "Google", "Anthropic", "Microsoft", "Nvidia"]
    elif isinstance(companies, str):
        companies_list = [c.strip() for c in re.split(r"[\s,]+", companies) if c.strip()]
    else:
        companies_list = [c for c in companies if c]
    out: dict[str, list[dict]] = {}
    errors: dict[str, str] = {}
    for company in companies_list:
        q = quote_plus(company)
        rss_url = f"https://news.google.com/rss/search?q={q}&hl={locale}&gl={region}&ceid={region}:{locale.split('-')[0]}"
        try:
            resp = requests.get(rss_url, timeout=10)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            items = []
            for item in root.findall('.//item'):
                title = (item.findtext('title') or '').strip()
                link = (item.findtext('link') or '').strip()
                pub_date = (item.findtext('pubDate') or '').strip()
                if title and link:
                    items.append({"title": title, "url": link, "published": pub_date})
                if len(items) >= limit:
                    break
            out[company] = items
        except Exception as e:
            errors[company] = str(e)
    result: dict[str, object] = {"companies": out, "source": "Google News RSS", "limit": limit}
    if errors:
        result["errors"] = errors
    return result


def latvian_news(query: str | None = None, limit: int = 10) -> dict:
    """Return the latest Latvian news items or topic-specific items from Google News RSS.
    If query provided, perform a topic search.
    """
    if query:
        # Google News search (lv locale)
        q = quote_plus(query)
        rss_url = f"https://news.google.com/rss/search?q={q}&hl=lv&gl=LV&ceid=LV:lv"
    else:
        rss_url = "https://news.google.com/rss?hl=lv&gl=LV&ceid=LV:lv"
    try:
        resp = requests.get(rss_url, timeout=10)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        items = []
        for item in root.findall('.//item'):
            title = (item.findtext('title') or '').strip()
            link = (item.findtext('link') or '').strip()
            pub_date = (item.findtext('pubDate') or '').strip()
            if title and link:
                items.append({"title": title, "url": link, "published": pub_date})
            if len(items) >= limit:
                break
        return {"items": items, "query": query, "source": "Google News RSS"}
    except requests.RequestException as exc:
        return {"error": f"News fetch failed: {exc}"}


def available_functions_info() -> dict:
    """Return info about available functions and usage (legacy endpoint)."""
    info = {
        "status": "ok",
        "functions": {
            "fetch_url": {"args": {"url": "string", "chunk_id": "string?", "mode": "string? (outline|images)", "link_id": "string? (e.g. L7)"}},
            "search_wikipedia": {"args": {"query": "string"}},
            "latvian_news": {"args": {"query": "string?"}},
            "search_duckduckgo": {"args": {"query": "string"}},
            "ai_company_news": {"args": {"companies": "string|list?", "limit": "int?"}},
            "get_system_prompt": {"args": {}},
        },
        "usage": [
            {"name": "fetch_url", "arguments": {"url": "https://example.com"}},
            {"name": "fetch_url", "arguments": {"url": "https://example.com", "chunk_id": "sec-2"}},
            {"name": "fetch_url", "arguments": {"url": "https://example.com", "mode": "outline"}},
            {"name": "fetch_url", "arguments": {"url": "https://example.com", "link_id": "L3"}},
            {"name": "search_wikipedia", "arguments": {"query": "Python"}},
            {"name": "latvian_news", "arguments": {}},
            {"name": "latvian_news", "arguments": {"query": "tehnoloģijas"}},
            {"name": "search_duckduckgo", "arguments": {"query": "open source vector database"}},
            {"name": "quick_search", "arguments": {"query": "quick test query"}},
            {"name": "ai_company_news", "arguments": {}},
            {"name": "get_system_prompt", "arguments": {}},
        ],
    }
    return info

# JSON-RPC helpers (defined unconditionally)

def _jsonrpc_result(_id, result):
    return {"jsonrpc": "2.0", "id": _id, "result": result}


def _jsonrpc_error(_id, code, message, data=None):
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": _id, "error": err}

def _resp_json(res):
    """Best-effort extract JSON payload from Flask Response or (Response, status) tuple."""
    try:
        # Direct Response
        if hasattr(res, 'get_json'):
            return res.get_json()
        # Tuple (Response, status)
        if isinstance(res, tuple) and len(res) >= 1 and hasattr(res[0], 'get_json'):
            return res[0].get_json()
        # Already a dict
        if isinstance(res, dict):
            return res
    except Exception:
        pass
    return {"ok": False}


def _sse_stream():
    yield "event: ready\ndata: {}\n\n"
    while True:
        yield ": keep-alive\n\n"
        time.sleep(15)

# ------------------------------------------------------------------
# Caching & Rate Limiting (new)
# ------------------------------------------------------------------

_HTML_CACHE_TTL = int(os.getenv("WEBTOOL_CACHE_TTL", "300"))  # seconds
_HTML_CACHE_MAX = int(os.getenv("WEBTOOL_HTML_CACHE_SIZE", "64"))
_OUTLINE_CACHE_TTL = int(os.getenv("WEBTOOL_OUTLINE_CACHE_TTL", "300"))
_FETCH_RATE_PER_MIN = int(os.getenv("WEBTOOL_FETCH_URL_RATE_PER_MIN", "60"))

_html_cache_lock = threading.Lock()
_outline_cache_lock = threading.Lock()

class _LRUCache:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.data: OrderedDict[str, tuple[float, str]] = OrderedDict()

    def get(self, key: str, ttl: int) -> str | None:
        now = time.time()
        with _html_cache_lock:
            item = self.data.get(key)
            if not item:
                return None
            ts, val = item
            if now - ts > ttl:
                del self.data[key]
                return None
            # move to end
            self.data.move_to_end(key)
            return val

    def put(self, key: str, value: str):
        with _html_cache_lock:
            if key in self.data:
                self.data.move_to_end(key)
            self.data[key] = (time.time(), value)
            while len(self.data) > self.capacity:
                self.data.popitem(last=False)
    def clear(self):
        with _html_cache_lock:
            self.data.clear()

_html_cache = _LRUCache(_HTML_CACHE_MAX)
_outline_cache = _LRUCache(_HTML_CACHE_MAX)

# Admin helpers
@app.post('/admin/clear_caches')
def admin_clear_caches():
    try:
        _html_cache.clear()
        _outline_cache.clear()
        return jsonify({"cleared": True})
    except Exception as e:
        return jsonify({"cleared": False, "error": str(e)}), 500

@app.get('/admin/annotations_export')
def admin_annotations_export():
    fmt = (request.args.get('format') or 'jsonl').lower()
    try:
        since = int(request.args.get('since') or 0)
    except Exception:
        since = 0
    try:
        until = int(request.args.get('until') or 0)
    except Exception:
        until = 0
    # Join annotations with core pair info for fine-tuning datasets
    with _DB_LOCK:
        con = _db_conn()
        try:
            cur = con.cursor()
            sql = (
                "SELECT a.id, a.pair_id, a.created_at, a.target, a.start, a.end, a.text, a.sentiment, a.tags_json, a.note, a.rating, "
                "p.created_at as pair_created_at, p.agent_type, p.user_request, p.model_response, p.topic "
                "FROM pair_annotations a JOIN pairs p ON p.id = a.pair_id"
            )
            where = []
            params: list[typing.Any] = []
            if since > 0:
                where.append("a.created_at >= ?")
                params.append(since)
            if until > 0:
                where.append("a.created_at <= ?")
                params.append(until)
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY a.created_at DESC"
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
        finally:
            con.close()
    items = []
    for r in rows:
        try:
            tags = json.loads(r[8] or '[]')
        except Exception:
            tags = []
        items.append({
            "annotation_id": r[0],
            "pair_id": r[1],
            "annotation_created_at": r[2],
            "target": r[3],
            "start": r[4],
            "end": r[5],
            "selected_text": r[6],
            "sentiment": r[7],
            "tags": tags,
            "note": r[9],
            "rating": r[10],
            "pair_created_at": r[11],
            "agent_type": r[12],
            "user_request": r[13],
            "model_response": r[14],
            "topic": r[15],
        })
    if fmt == 'json':
        return jsonify({"items": items, "count": len(items)})
    if fmt == 'csv':
        # CSV export with a stable column set
        import csv
        from io import StringIO
        cols = [
            "annotation_id","pair_id","annotation_created_at","target","start","end","selected_text",
            "sentiment","tags","note","rating","pair_created_at","agent_type","user_request","model_response","topic"
        ]
        def _row(obj: dict) -> list[str]:
            out = []
            for k in cols:
                v = obj.get(k)
                if k == 'tags':
                    try:
                        v = ",".join([str(t) for t in (v or [])])
                    except Exception:
                        v = ''
                if v is None:
                    v = ''
                out.append(str(v))
            return out
        sio = StringIO()
        writer = csv.writer(sio)
        writer.writerow(cols)
        for it in items:
            writer.writerow(_row(it))
        payload = sio.getvalue()
        headers = {
            'Content-Type': 'text/csv; charset=utf-8',
            'Content-Disposition': 'attachment; filename="annotations.csv"'
        }
        return Response(payload, headers=headers)
    # default jsonl
    def generate():
        for obj in items:
            yield json.dumps(obj, ensure_ascii=False) + "\n"
    headers = {
        'Content-Type': 'text/plain; charset=utf-8',
        'Content-Disposition': 'attachment; filename="annotations.jsonl"'
    }
    return Response(generate(), headers=headers)

@app.get('/vision/status')
def vision_status():
    ready = _get_vision_model() is not None
    return jsonify({
        "ready": bool(ready),
        "model": _VISION_MODEL_NAME,
        "has_torch": bool(torch is not None),
        "has_transformers": bool(AutoModel is not None),
        "has_pillow": bool(Image is not None),
        "has_ocr": bool(pytesseract is not None)
    })

@app.post('/vision/encode')
def vision_encode():
    body = request.get_json(silent=True) or {}
    url = (body.get('url') or '').strip()
    b64 = (body.get('data') or '').strip()
    include_vec = str(body.get('include_vector') or '').strip().lower() in {'1','true','yes'}
    if not url and not b64:
        return jsonify({"error": "url or data required"}), 400
    data: bytes | None = None
    mime = None
    try:
        if url:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            data = r.content
            mime = r.headers.get('Content-Type')
        else:
            data = base64.b64decode(b64)
    except Exception as e:
        return jsonify({"error": f"image fetch/decode failed: {e}"}), 400
    pil = _open_image_from_bytes(data or b'')
    w = pil.width if pil is not None else None
    h = pil.height if pil is not None else None
    vec = _siglip_image_embed(pil) if pil is not None else None
    ocr_txt = _ocr_image(pil)
    vid = _vision_save_item(url or None, mime, w, h, ocr_txt, None, None, vec)
    resp = {"id": vid, "url": url or None, "width": w, "height": h, "mime": mime, "ocr_text": ocr_txt or ''}
    if include_vec and vec is not None:
        resp["embedding"] = vec
    return jsonify(resp)

@app.post('/vision/search')
def vision_search():
    body = request.get_json(silent=True) or {}
    q = (body.get('q') or body.get('query') or '').strip()
    try:
        limit = int(body.get('limit') or 10)
    except Exception:
        limit = 10
    if not q:
        return jsonify({"error": "q required"}), 400
    qv = _siglip_text_embed(q)
    if qv is None:
        return jsonify({"error": "vision model unavailable"}), 400
    # Load all vision vectors (small scale); in production, use ANN index
    with _DB_LOCK:
        con = _db_conn()
        try:
            cur = con.cursor()
            cur.execute("SELECT id, vec FROM vision_emb")
            rows = cur.fetchall()
        finally:
            con.close()
    items: list[tuple[float,str]] = []
    for pid, vec_json in rows:
        try:
            v = json.loads(vec_json)
            sc = _cosine(qv, v)  # reuse cosine
            items.append((float(sc), pid))
        except Exception:
            continue
    items.sort(key=lambda t: t[0], reverse=True)
    top = items[:limit]
    results = []
    if top:
        with _DB_LOCK:
            con = _db_conn()
            try:
                cur = con.cursor()
                qmarks = ','.join(['?']*len(top))
                cur.execute(f"SELECT id, created_at, src_url, mime, width, height, ocr_text, tags_json, meta_json FROM vision_items WHERE id IN ({qmarks})", tuple([pid for _, pid in top]))
                rows2 = cur.fetchall()
            finally:
                con.close()
        info = {r[0]: r for r in rows2}
        for sc, pid in top:
            r = info.get(pid)
            if not r:
                continue
            try:
                tags = json.loads(r[7] or '[]')
            except Exception:
                tags = []
            results.append({
                "id": r[0], "created_at": r[1], "url": r[2], "mime": r[3], "width": r[4], "height": r[5],
                "ocr_text": r[6] or '', "tags": tags, "score": round(float(sc),4)
            })
    return jsonify({"items": results, "query": q})

@app.post('/vision/extract_from_url')
def vision_extract_from_url():
    body = request.get_json(silent=True) or {}
    url = (body.get('url') or '').strip()
    try:
        limit = int(body.get('limit') or 6)
    except Exception:
        limit = 6
    if not url:
        return jsonify({"error": "url required"}), 400
    try:
        res = fetch_url(url)
        html = res.get('content') if isinstance(res, dict) else None
        if not html:
            return jsonify({"error": "failed to fetch base url"}), 400
        soup = BeautifulSoup(html, 'html.parser')
        imgs = _extract_images(soup, url)[:limit]
        out = []
        for img in imgs:
            src = img.get('src')
            if not src:
                continue
            try:
                r = requests.get(src, timeout=10)
                r.raise_for_status()
                data = r.content
                pil = _open_image_from_bytes(data)
                w = pil.width if pil is not None else None
                h = pil.height if pil is not None else None
                vec = _siglip_image_embed(pil) if pil is not None else None
                ocr_txt = _ocr_image(pil)
                vid = _vision_save_item(src, r.headers.get('Content-Type'), w, h, ocr_txt, None, {"from": url}, vec)
                out.append({"id": vid, "url": src, "width": w, "height": h, "ocr_text": ocr_txt or ''})
            except Exception as e:
                app.logger.warning(f"image fetch/index failed for {src}: {e}")
                continue
        return jsonify({"items": out, "source": url})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.get('/admin/annotations_summary')
def admin_annotations_summary():
    try:
        since = int(request.args.get('since') or 0)
    except Exception:
        since = 0
    try:
        until = int(request.args.get('until') or 0)
    except Exception:
        until = 0
    with _DB_LOCK:
        con = _db_conn()
        try:
            cur = con.cursor()
            # Base filter
            where = []
            params: list[typing.Any] = []
            if since > 0:
                where.append("a.created_at >= ?")
                params.append(since)
            if until > 0:
                where.append("a.created_at <= ?")
                params.append(until)
            wsql = (" WHERE " + " AND ".join(where)) if where else ""
            # Totals
            cur.execute(f"SELECT COUNT(*), MIN(a.created_at), MAX(a.created_at) FROM pair_annotations a{wsql}", tuple(params))
            row = cur.fetchone() or (0, None, None)
            total = row[0] or 0
            min_ts = row[1]
            max_ts = row[2]
            # Distinct pairs
            cur.execute(f"SELECT COUNT(DISTINCT a.pair_id) FROM pair_annotations a{wsql}", tuple(params))
            total_pairs = (cur.fetchone() or (0,))[0] or 0
            # Sentiment counts
            cur.execute(f"SELECT COALESCE(a.sentiment,''), COUNT(*) FROM pair_annotations a{wsql} GROUP BY COALESCE(a.sentiment,'')", tuple(params))
            by_sent = { (r[0] or ''): r[1] for r in cur.fetchall() }
            # Tags
            cur.execute(f"SELECT a.tags_json FROM pair_annotations a{wsql}", tuple(params))
            tag_counts: dict[str,int] = {}
            for (tags_json,) in cur.fetchall():
                try:
                    tags = json.loads(tags_json or '[]')
                    if isinstance(tags, list):
                        for t in tags:
                            try:
                                k = str(t).strip()
                                if not k: continue
                                tag_counts[k] = tag_counts.get(k,0) + 1
                            except Exception:
                                continue
                except Exception:
                    continue
            top_tags = sorted(([{"tag": k, "count": v} for k, v in tag_counts.items()]), key=lambda x: x["count"], reverse=True)[:20]
            # By agent
            cur.execute(
                f"SELECT p.agent_type, COUNT(*) FROM pair_annotations a JOIN pairs p ON p.id=a.pair_id{wsql} GROUP BY p.agent_type",
                tuple(params)
            )
            by_agent = { (r[0] or 'unknown'): r[1] for r in cur.fetchall() }
        finally:
            con.close()
    return jsonify({
        "total_annotations": total,
        "total_pairs": total_pairs,
        "time_range": {"since": since or min_ts, "until": until or max_ts},
        "by_sentiment": {
            "positive": by_sent.get('positive', 0),
            "negative": by_sent.get('negative', 0),
            "neutral": by_sent.get('', 0)
        },
        "top_tags": top_tags,
        "by_agent": by_agent
    })

_rate_lock = threading.Lock()
_fetch_timestamps = deque()  # timestamps of fetch_url network fetches

def _rate_limited_fetch_allowed() -> bool:
    """Return True if another network fetch_url is allowed under rate limit."""
    if _FETCH_RATE_PER_MIN <= 0:
        return True
    now = time.time()
    window_start = now - 60
    with _rate_lock:
        # drop old
        while _fetch_timestamps and _fetch_timestamps[0] < window_start:
            _fetch_timestamps.popleft()
        if len(_fetch_timestamps) >= _FETCH_RATE_PER_MIN:
            return False
        _fetch_timestamps.append(now)
        return True

def _cached_fetch_html(url: str) -> tuple[str | None, bool, str | None]:
    """Return (html, cache_hit, error)."""
    key = url.strip()
    html = _html_cache.get(key, _HTML_CACHE_TTL)
    if html is not None:
        return html, True, None
    # rate limiting only for real network fetches
    if not _rate_limited_fetch_allowed():
        return None, False, f"Rate limit exceeded: max {_FETCH_RATE_PER_MIN} fetch_url network requests per minute. Try later or rely on cached outline/chunks."
    res = fetch_url(url)
    if isinstance(res, dict) and res.get("error"):
        return None, False, res["error"]
    html = res.get("content", "")
    if html:
        _html_cache.put(key, html)
    return html, False, None

def _outline_cache_key(url: str, html: str | None = None) -> str:
    # Include a short checksum of HTML to avoid stale outlines when decoding/extraction changes
    if html:
        try:
            import hashlib
            h = hashlib.md5(html.encode('utf-8', errors='ignore')).hexdigest()[:8]
            return f"outline::{url.strip()}::{h}"
        except Exception:
            pass
    return f"outline::{url.strip()}"

def _get_cached_outline(url: str, html: str | None = None) -> str | None:
    return _outline_cache.get(_outline_cache_key(url, html), _OUTLINE_CACHE_TTL)

def _store_cached_outline(url: str, text: str, html: str | None = None):
    _outline_cache.put(_outline_cache_key(url, html), text)
    app.logger.debug(f"Stored outline cache for {url}")

# ------------------------------------------------------------------
# Structured page extraction (replaces earlier simple fallback)
# ------------------------------------------------------------------

_TOKEN_EST_CHARS_PER = 4  # heuristic

_HEADING_TAGS = ["h1", "h2", "h3"]

_WS_RE = re.compile(r"\s+")
_CAP_ENTITY_RE = re.compile(r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b")
_DATE_RE = re.compile(r"\b(20\d{2}|19\d{2})\b")
_NUMBER_RE = re.compile(r"\b\d{2,}\b")


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ------------------------------------------------------------------
# Luxriot PDF RAG (BM25-based lightweight index)
# ------------------------------------------------------------------

# You can override file paths via env LUXRIOT_ADMIN_GUIDE / LUXRIOT_MONITOR_GUIDE
LUXRIOT_DEFAULT_FILES = [
    os.environ.get("LUXRIOT_ADMIN_GUIDE", os.path.join(os.getcwd(), "Luxriot-EVO-S-Administration-Guide.pdf")),
    os.environ.get("LUXRIOT_MONITOR_GUIDE", os.path.join(os.getcwd(), "Luxriot-EVO-Monitor-User-Guide.pdf")),
]
LUXRIOT_INDEX_PATH = os.environ.get("LUXRIOT_INDEX", os.path.join(os.getcwd(), "luxriot_index.pkl"))
# Tunables
LUXRIOT_CHARS_PER_CHUNK = int(os.environ.get("LUXRIOT_CHARS_PER_CHUNK", "1400"))
LUXRIOT_CHUNK_OVERLAP = int(os.environ.get("LUXRIOT_CHUNK_OVERLAP", "200"))
LUXRIOT_HYBRID_ALPHA = float(os.environ.get("LUXRIOT_HYBRID_ALPHA", "0.6"))  # weight for semantic vs BM25
LUXRIOT_EMBED_CACHE = os.environ.get("LUXRIOT_EMBED_CACHE", os.path.join(os.getcwd(), "luxriot_embed.npy"))
LUXRIOT_RERANK_MODEL = os.environ.get("LUXRIOT_RERANK_MODEL")  # e.g., cross-encoder/ms-marco-MiniLM-L-6-v2

_luxriot_lock = threading.Lock()
_luxriot_index = None  # type: ignore


@dataclass
class LuxriotChunk:
    id: str
    doc: str
    file: str
    page_start: int
    page_end: int
    text: str


class LuxriotIndex:
    def __init__(self):
        self.chunks: list[LuxriotChunk] = []
        self.tokens: list[list[str]] = []
        self.bm25 = None
        self.files: list[str] = []
        self.built_at = None
        self.embeddings = None  # optional semantic vectors
        self.embed_model_name = None

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return re.findall(r"[a-zA-Z0-9]{2,}", (text or "").lower())

    def _chunk_pages(self, reader, file_path: str, doc_name: str):
        # Accumulate per configured chars with overlap carryover between chunks
        buf = ""
        start_page = 0
        chunk_idx = 0
        max_len = max(400, int(LUXRIOT_CHARS_PER_CHUNK))
        overlap = max(0, int(LUXRIOT_CHUNK_OVERLAP))
        for i, page in enumerate(reader.pages):
            try:
                txt = page.extract_text() or ""
            except Exception:
                txt = ""
            if not txt.strip():
                continue
            if not buf:
                start_page = i
            buf += ("\n" if buf else "") + txt
            if len(buf) >= max_len:
                chunk_idx += 1
                cid = f"{doc_name}:{start_page+1}-{i+1}#{chunk_idx}"
                self.chunks.append(LuxriotChunk(id=cid, doc=doc_name, file=file_path, page_start=start_page+1, page_end=i+1, text=buf.strip()))
                if overlap > 0:
                    tail = buf[-overlap:]
                    buf = tail
                    # next chunk logically still includes current page
                    start_page = max(i, 0)
                else:
                    buf = ""
        if buf.strip():
            chunk_idx += 1
            cid = f"{doc_name}:{start_page+1}-{len(reader.pages)}#{chunk_idx}"
            self.chunks.append(LuxriotChunk(id=cid, doc=doc_name, file=file_path, page_start=start_page+1, page_end=len(reader.pages), text=buf.strip()))

    def build(self, pdf_paths: list[str]):
        if PdfReader is None or BM25Okapi is None:
            raise RuntimeError("Missing dependencies: install pypdf and rank_bm25")
        self.files = [p for p in pdf_paths if p and os.path.exists(p)]
        if not self.files:
            raise FileNotFoundError("No Luxriot PDFs found. Set LUXRIOT_ADMIN_GUIDE and LUXRIOT_MONITOR_GUIDE or place PDFs in project root.")
        self.chunks.clear()
        for path in self.files:
            try:
                name = os.path.basename(path)
                if 'Monitor' in name:
                    doc_name = 'Monitor-User-Guide'
                elif 'Administration' in name or 'Admin' in name or 'EVO-S' in name:
                    doc_name = 'EVO-S-Administration-Guide'
                else:
                    doc_name = name
                reader = PdfReader(path)
                self._chunk_pages(reader, path, doc_name)
            except Exception as e:
                app.logger.exception(f"Failed to read {path}: {e}")
        # Tokens & BM25
        self.tokens = [self._tokenize(c.text) for c in self.chunks]
        self.bm25 = BM25Okapi(self.tokens)
        self.built_at = _now_iso()
        # Optional embeddings if sentence-transformers available and enabled
        model_name = os.environ.get("LUXRIOT_EMBED_MODEL")
        if SentenceTransformer is not None and _np is not None and model_name:
            try:
                model = SentenceTransformer(model_name)
                self.embed_model_name = model_name
                import numpy as np
                try:
                    if LUXRIOT_EMBED_CACHE and os.path.exists(LUXRIOT_EMBED_CACHE):
                        self.embeddings = np.load(LUXRIOT_EMBED_CACHE)
                        if self.embeddings.shape[0] != len(self.chunks):
                            self.embeddings = None
                except Exception:
                    self.embeddings = None
                if self.embeddings is None:
                    self.embeddings = model.encode([c.text for c in self.chunks], normalize_embeddings=True)
                    try:
                        if LUXRIOT_EMBED_CACHE:
                            np.save(LUXRIOT_EMBED_CACHE, self.embeddings)
                    except Exception:
                        pass
            except Exception as e:
                app.logger.warning(f"Luxriot embeddings build failed: {e}")

    @staticmethod
    def _expand_query_terms(q: str) -> list[str]:
        # Simple synonym expansion for Luxriot domain
        synonyms: dict[str, list[str]] = {
            "failover": ["redundancy", "ha", "high", "availability", "cluster"],
            "archive": ["storage", "retention", "long-term", "backup"],
            "monitor": ["client", "viewer", "ui", "display"],
            "server": ["service", "core"],
            "license": ["licensing", "activation", "key"],
            "database": ["sql", "postgres", "postgresql"],
            "recording": ["stream", "ingest"],
            "camera": ["ip", "device"],
        }
        toks = LuxriotIndex._tokenize(q)
        expanded = toks[:]
        for t in toks:
            if t in synonyms:
                expanded.extend(synonyms[t])
        # light boost by duplicating originals
        expanded.extend(toks)
        return expanded

    @staticmethod
    def _make_snippet(text: str, terms: list[str], max_len: int = 500) -> str:
        if not text:
            return ""
        tset = {t.lower() for t in terms if len(t) >= 3}
        lower = text.lower()
        pos = -1
        hit = None
        for t in tset:
            p = lower.find(t)
            if p != -1 and (pos == -1 or p < pos):
                pos = p
                hit = t
        if pos == -1:
            return text[:max_len].replace('\n', ' ')
        start = max(0, pos - max_len // 2)
        end = min(len(text), start + max_len)
        snippet = text[start:end].replace('\n', ' ')
        if hit:
            try:
                snippet = re.sub(fr"(?i)\b{re.escape(hit)}\b", r"**\\g<0>**", snippet)
            except Exception:
                pass
        return snippet

    def to_dict(self) -> dict:
        return {
            "files": self.files,
            "built_at": self.built_at,
            "chunks": [
                {
                    "id": c.id,
                    "doc": c.doc,
                    "file": c.file,
                    "page_start": c.page_start,
                    "page_end": c.page_end,
                    "text": c.text,
                }
                for c in self.chunks
            ],
            "tokens": self.tokens,
            "embed_model": self.embed_model_name,
            # embeddings are large; cache only if env permits
            "embeddings": None,
        }

    @classmethod
    def from_dict(cls, d: dict):
        idx = cls()
        idx.files = list(d.get("files", []))
        idx.built_at = d.get("built_at")
        idx.chunks = [
            LuxriotChunk(
                id=c.get("id",""),
                doc=c.get("doc",""),
                file=c.get("file",""),
                page_start=int(c.get("page_start",0)),
                page_end=int(c.get("page_end",0)),
                text=c.get("text",""),
            )
            for c in d.get("chunks", [])
        ]
        idx.tokens = list(d.get("tokens", []))
        if BM25Okapi is not None and idx.tokens:
            try:
                idx.bm25 = BM25Okapi(idx.tokens)
            except Exception:
                idx.bm25 = None
        idx.embed_model_name = d.get("embed_model")
        idx.embeddings = None  # do not restore by default; recompute if requested
        return idx

    def search(self, query: str, k: int = 5, doc: str | None = None) -> list[dict]:
        if not self.bm25 or not self.chunks:
            return []
        qtok = self._expand_query_terms(query)
        if not qtok:
            return []
        scores = self.bm25.get_scores(qtok)
        idxs = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        out = []
        for i in idxs:
            ck = self.chunks[i]
            if doc and doc.lower() not in ck.doc.lower():
                continue
            score = float(scores[i])
            snippet = self._make_snippet(ck.text, qtok, 500)
            out.append({
                "chunk_id": ck.id,
                "doc": ck.doc,
                "pages": f"{ck.page_start}-{ck.page_end}",
                "score": round(score, 4),
                "snippet": snippet,
            })
            if len(out) >= k:
                break
        return out

    def semantic_search(self, query: str, k: int = 5, doc: str | None = None) -> list[dict]:
        if SentenceTransformer is None or _np is None:
            return []
        if not self.chunks:
            return []
        # lazily compute embeddings using configured model
        model_name = os.environ.get("LUXRIOT_EMBED_MODEL")
        if not model_name:
            return []
        try:
            model = SentenceTransformer(model_name)
            qv = model.encode([query], normalize_embeddings=True)[0]
            if self.embeddings is None:
                self.embeddings = model.encode([c.text for c in self.chunks], normalize_embeddings=True)
                self.embed_model_name = model_name
            sims = (self.embeddings @ qv)
            import numpy as np
            idxs = np.argsort(-sims)
            out = []
            for i in idxs:
                ck = self.chunks[int(i)]
                if doc and doc.lower() not in ck.doc.lower():
                    continue
                out.append({
                    "chunk_id": ck.id,
                    "doc": ck.doc,
                    "pages": f"{ck.page_start}-{ck.page_end}",
                    "score": float(sims[int(i)]),
                    "snippet": self._make_snippet(ck.text, LuxriotIndex._tokenize(query), 500),
                })
                if len(out) >= k:
                    break
            return out
        except Exception as e:
            app.logger.warning(f"semantic_search failed: {e}")
            return []

    def search_hybrid(self, query: str, k: int = 5, doc: str | None = None) -> list[dict]:
        if not self.chunks:
            return []
        # BM25 part
        bm_items = []
        bm_scores = []
        if self.bm25 is not None:
            bm = self.search(query, k=len(self.chunks), doc=doc)
            bm_items = bm
            bm_scores = [it["score"] for it in bm]
        # Semantic part
        sem_items = []
        sem_scores = []
        if SentenceTransformer is not None and _np is not None and os.environ.get("LUXRIOT_EMBED_MODEL"):
            sem = self.semantic_search(query, k=len(self.chunks), doc=doc)
            sem_items = sem
            sem_scores = [it["score"] for it in sem]
        # Build index maps
        def to_map(items):
            m = {}
            for it in items:
                m[it["chunk_id"]] = it
            return m
        bm_map = to_map(bm_items)
        sem_map = to_map(sem_items)
        # Normalization helpers
        def normalize(vals):
            if not vals:
                return lambda x: 0.0
            vmin, vmax = min(vals), max(vals)
            if vmax <= vmin + 1e-9:
                return lambda x: 0.0
            return lambda x: (x - vmin) / (vmax - vmin)
        bm_norm = normalize(bm_scores)
        sem_norm = normalize(sem_scores)
        # Blend
        seen = set()
        all_ids = list({*bm_map.keys(), *sem_map.keys()})
        scored = []
        for cid in all_ids:
            b = bm_norm(bm_map.get(cid, {}).get("score", 0.0))
            s = sem_norm(sem_map.get(cid, {}).get("score", 0.0))
            hybrid = float(LUXRIOT_HYBRID_ALPHA) * s + (1.0 - float(LUXRIOT_HYBRID_ALPHA)) * b
            # pick a representative item (prefer bm entry for stable pages/snippet)
            base = bm_map.get(cid) or sem_map.get(cid)
            if not base:
                continue
            seen.add(cid)
            scored.append((hybrid, base))
        scored.sort(key=lambda t: t[0], reverse=True)
        # Optional cross-encoder rerank of the top N
        reranked = scored
        try:
            if LUXRIOT_RERANK_MODEL and 'CrossEncoder' in globals() and CrossEncoder is not None:
                topN = min(25, len(scored))
                ce = CrossEncoder(LUXRIOT_RERANK_MODEL)
                pairs = [(query, (bm_map.get(it["chunk_id"], it).get("snippet") or it.get("snippet") or "")) for _, it in scored[:topN]]
                import numpy as np
                scores_ce = ce.predict(pairs)
                reranked = list(zip(scores_ce, [it for _, it in scored[:topN]]))
                reranked.sort(key=lambda t: float(t[0]), reverse=True)
        except Exception as e:
            app.logger.warning(f"Luxriot rerank failed: {e}")
            reranked = scored
        out = []
        for sc, it in reranked[:k]:
            out.append({
                "chunk_id": it["chunk_id"],
                "doc": it["doc"],
                "pages": it["pages"],
                "score": round(float(sc), 4),
                "snippet": it.get("snippet") or "",
                "bm25": round(float(bm_map.get(it["chunk_id"], {}).get("score", 0.0)), 4),
                "semantic": round(float(sem_map.get(it["chunk_id"], {}).get("score", 0.0)), 4),
            })
        return out

    def get(self, chunk_id: str) -> dict | None:
        for c in self.chunks:
            if c.id == chunk_id:
                return {
                    "chunk_id": c.id,
                    "doc": c.doc,
                    "file": c.file,
                    "page_start": c.page_start,
                    "page_end": c.page_end,
                    "text": c.text,
                }
        return None


def _luxriot_ensure_index() -> LuxriotIndex | None:  # type: ignore
    global _luxriot_index
    with _luxriot_lock:
        if _luxriot_index is not None:
            return _luxriot_index
        try:
            # Try load from pickle if newer than PDFs
            import pickle
            use_cache = False
            if os.path.exists(LUXRIOT_INDEX_PATH):
                try:
                    cache_mtime = os.path.getmtime(LUXRIOT_INDEX_PATH)
                    pdf_mtimes = [os.path.getmtime(p) for p in LUXRIOT_DEFAULT_FILES if p and os.path.exists(p)]
                    if pdf_mtimes and cache_mtime >= max(pdf_mtimes):
                        with open(LUXRIOT_INDEX_PATH, 'rb') as f:
                            data = pickle.load(f)
                        idx = LuxriotIndex.from_dict(data)
                        if idx.chunks and idx.bm25:
                            _luxriot_index = idx
                            app.logger.info(f"Luxriot index loaded from cache: {len(idx.chunks)} chunks")
                            return _luxriot_index
                except Exception as e:
                    app.logger.warning(f"Luxriot index cache load failed: {e}")

            # Build fresh
            idx = LuxriotIndex()
            idx.build(LUXRIOT_DEFAULT_FILES)
            # Save to cache
            try:
                with open(LUXRIOT_INDEX_PATH, 'wb') as f:
                    pickle.dump(idx.to_dict(), f)
                app.logger.info(f"Luxriot index saved to {LUXRIOT_INDEX_PATH}")
            except Exception as e:
                app.logger.warning(f"Luxriot index cache save failed: {e}")
            _luxriot_index = idx
            app.logger.info(f"Luxriot index built: {len(idx.chunks)} chunks from {len(idx.files)} files")
            return _luxriot_index
        except Exception as e:
            app.logger.warning(f"Luxriot index unavailable: {e}")
            return None


@app.route('/luxriot/status', methods=['GET'])
def luxriot_status():
    idx = _luxriot_ensure_index()
    if not idx:
        return jsonify({"ready": False})
    return jsonify({
        "ready": True,
        "files": idx.files,
        "chunks": len(idx.chunks),
        "built_at": idx.built_at,
        "embed_model": idx.embed_model_name,
        "has_embeddings": bool(getattr(idx, 'embeddings', None) is not None)
    })


@app.route('/luxriot/search', methods=['GET'])
def luxriot_search():
    q = request.args.get('q') or request.args.get('query')
    k = int(request.args.get('k') or 5)
    doc = request.args.get('doc')
    if not q:
        return jsonify({"error": "q is required"}), 400
    idx = _luxriot_ensure_index()
    if not idx:
        return jsonify({"ready": False, "items": []})
    return jsonify({"ready": True, "items": idx.search(q, k=k, doc=doc)})


@app.route('/luxriot/search_hybrid', methods=['GET'])
def luxriot_search_hybrid():
    q = request.args.get('q') or request.args.get('query')
    k = int(request.args.get('k') or 5)
    doc = request.args.get('doc')
    if not q:
        return jsonify({"error": "q is required"}), 400
    idx = _luxriot_ensure_index()
    if not idx:
        return jsonify({"ready": False, "items": []})
    return jsonify({"ready": True, "items": idx.search_hybrid(q, k=k, doc=doc)})


@app.route('/luxriot/get', methods=['GET'])
def luxriot_get():
    cid = request.args.get('id') or request.args.get('chunk_id')
    if not cid:
        return jsonify({"error": "id is required"}), 400
    idx = _luxriot_ensure_index()
    if not idx:
        return jsonify({"error": "index unavailable"}), 400
    doc = idx.get(cid)
    if not doc:
        return jsonify({"error": "not found"}), 404
    return jsonify(doc)



def _token_estimate(text: str) -> int:
    return max(1, len(text) // _TOKEN_EST_CHARS_PER)


def _select_main(soup: BeautifulSoup) -> Tag:  # revised to guarantee Tag return
    for sel in ["main", "article"]:
        tag = soup.find(sel)
        if isinstance(tag, Tag):
            return tag
    body = soup.body
    if isinstance(body, Tag):
        return body
    # BeautifulSoup itself subclasses Tag enough for our usage; cast for type checker
    return cast(Tag, soup)


def _extract_nav_links(soup: BeautifulSoup, base_url: str) -> list[dict]:
    navs = []
    for nav in soup.find_all(["nav"]):
        for a in nav.find_all("a", href=True):
            txt = _collapse(a.get_text(" "))
            if not txt:
                continue
            href = urljoin(base_url, a["href"]) if a["href"] else None
            if href:
                navs.append({"text": txt, "url": href})
    # Deduplicate by (text,url)
    seen = set()
    dedup = []
    for item in navs:
        key = (item["text"], item["url"])
        if key in seen:
            continue
        seen.add(key)
        dedup.append(item)
    return dedup[:50]

def _absolute_url(base_url: str, href: str | None) -> str | None:
    if not href:
        return None
    try:
        return urljoin(base_url, href)
    except Exception:
        return href

_IMG_EXT_RE = re.compile(r"\.(?:png|jpe?g|webp|gif|bmp|svg)(?:\?.*)?$", re.I)

def _guess_image_width_from_url(u: str) -> int | None:
    """Best-effort width guess from common patterns like '/250px-' or query 'w=640'."""
    try:
        # Wikipedia-style thumbnail path contains '/<N>px-'
        m = re.search(r"/(\d{2,4})px-", u)
        if m:
            return int(m.group(1))
        # Look for common query params w= or width=
        q = urlparse(u).query
        if q:
            qm = re.search(r"(?:^|&)w(?:idth)?=(\d{2,4})(?:&|$)", q)
            if qm:
                return int(qm.group(1))
    except Exception:
        pass
    return None

_IMG_ICON_WORDS = re.compile(r"\b(?:logo|icon|sprite|favicon|avatar|button|badge|tracker)\b", re.I)
_IMG_MAP_FLAG = re.compile(r"\b(?:map|flag)\b", re.I)
_IMG_PHOTO_EXT_SCORE = {"jpg": 3, "jpeg": 3, "webp": 3, "png": 2, "gif": 1, "bmp": 1, "svg": 0}

def _filename_from_url(u: str) -> str:
    try:
        path = urlparse(u).path
        return os.path.basename(path)
    except Exception:
        return u

def _extract_images(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """Collect best-effort page images: og:image, twitter:image, then main <img> sources.
    Filters data: URIs and very small icons. Returns list of dicts with src, alt, filename, width_guess.
    """
    out: list[dict] = []
    seen: set[str] = set()
    def _add(src: str | None, alt: str = ""):
        if not src:
            return
        if src.startswith("data:"):
            return
        u = _absolute_url(base_url, src) or src
        # basic extension match; allow common web image types
        if not _IMG_EXT_RE.search(u):
            parsed = urlparse(u)
            if not parsed.netloc:
                return
        key = u
        if key in seen:
            return
        seen.add(key)
        out.append({
            "src": u,
            "alt": _collapse(alt),
            "filename": _filename_from_url(u),
            "width_guess": _guess_image_width_from_url(u),
        })
    # Meta OG/Twitter first
    for sel, attr in (("meta[property='og:image']", "content"), ("meta[name='twitter:image']", "content")):
        try:
            for m in soup.select(sel):
                val = m.get(attr)
                _add(val if isinstance(val, str) else None)
        except Exception:
            pass
    # Main content imgs
    main = _select_main(soup)
    for img in main.find_all("img")[:60]:
        src = img.get("src") or img.get("data-src") or img.get("data-original")
        alt = img.get("alt") or ""
        _add(src, alt)
    return out[:12]


def _score_image_for_thumb(img: dict) -> float:
    """Score image for thumbnail suitability: prefer photos with mid-size width, non-icon keywords, useful alt.
    Higher is better.
    """
    src = str(img.get("src") or "")
    alt = str(img.get("alt") or "")
    fn = str(img.get("filename") or "")
    ext = fn.split(".")[-1].lower() if "." in fn else ""
    width = img.get("width_guess") or 0
    score = 0.0
    # Extension/photo type weight
    score += _IMG_PHOTO_EXT_SCORE.get(ext, 0)
    # Prefer mid-size thumbnails (200-600px), slightly reward larger up to 1200
    if width:
        if 180 <= width <= 600:
            score += 3.0
        elif 120 < width < 180:
            score += 1.0
        elif 600 < width <= 1200:
            score += 1.0
    # Penalize icons/logos/maps/flags
    if _IMG_ICON_WORDS.search(src) or _IMG_ICON_WORDS.search(fn) or _IMG_ICON_WORDS.search(alt):
        score -= 3.0
    if _IMG_MAP_FLAG.search(src) or _IMG_MAP_FLAG.search(fn) or _IMG_MAP_FLAG.search(alt):
        score -= 1.5
    # Prefer non-empty descriptive alt text
    if len(alt.strip()) >= 6:
        score += 1.5
    return score

def _top_thumbnail_images(images: list[dict], k: int = 2) -> list[dict]:
    if not images:
        return []
    scored = sorted(images, key=_score_image_for_thumb, reverse=True)
    return [img for img in scored[:k] if _score_image_for_thumb(img) > 0]


def _iter_text_nodes(node: Tag):
    for el in node.descendants:
        if isinstance(el, NavigableString):
            txt = _collapse(str(el))
            if txt:
                yield txt


def _gather_links(main: Tag, base_url: str) -> list[dict]:
    links = []
    for a in main.find_all("a", href=True):
        text = _collapse(a.get_text(" "))[:160]
        href = urljoin(base_url, a["href"]) if a["href"] else None
        if not href or not text:
            continue
        links.append({"text": text, "url": href})
    # Dedupe while preserving order
    seen = set()
    out = []
    for l in links:
        key = (l["text"], l["url"])
        if key in seen:
            continue
        seen.add(key)
        out.append(l)
    return out[:200]


def _extract_headings(main: Tag) -> list[dict]:
    headings = []
    for tag in main.find_all(_HEADING_TAGS):
        level = int(tag.name[1])
        title = _collapse(tag.get_text(" "))
        if not title:
            continue
        headings.append({"level": level, "title": title, "tag": tag})
    return headings


def _build_chunks(headings: list[dict], main: Tag) -> list[dict]:
    if not headings:
        # single chunk of all text
        text = _collapse(main.get_text(" "))
        return [{"id": "sec-1", "heading": "Document", "level": 1, "text": text}]
    chunks = []
    for idx, h in enumerate(headings):
        start_tag = h["tag"]
        # Determine stop boundary
        stop_tags = []
        for nxt in headings[idx + 1:]:
            if nxt["level"] <= h["level"]:
                stop_tags.append(nxt["tag"])
                break
        texts = []
        cur = start_tag.next_sibling
        while cur and (not stop_tags or cur != stop_tags[0]):
            if isinstance(cur, Tag):
                # Skip further headings entirely
                if cur.name in _HEADING_TAGS:
                    break
                txt = _collapse(cur.get_text(" "))
                if txt:
                    texts.append(txt)
            elif isinstance(cur, NavigableString):
                txt = _collapse(str(cur))
                if txt:
                    texts.append(txt)
            cur = cur.next_sibling
        body_text = " \n".join(texts).strip()
        chunk_id = f"sec-{idx+1}"
        chunks.append({
            "id": chunk_id,
            "heading": h["title"],
            "level": h["level"],
            "text": body_text,
            "tokens": _token_estimate(body_text),
        })
    return chunks


def _derive_outline(chunks: list[dict]) -> list[str]:
    lines = []
    for c in chunks:
        indent = "  " * (c["level"] - 1)
        lines.append(f"{indent}{c['id']} {c['heading']}")
    return lines


def _keypoints(chunks: list[dict]) -> list[str]:
    points = []
    for c in chunks[:8]:  # limit initial extraction
        if not c["text"]:
            continue
        # Take first sentence-like fragment
        frag = c["text"].split(".")[0][:180]
        if frag:
            points.append(f"{c['heading']}: {frag.strip()}.")
    return points[:12]


def _entities(full_text: str) -> dict:
    people_orgs = list(dict.fromkeys(_CAP_ENTITY_RE.findall(full_text)))[:25]
    years = list(dict.fromkeys(_DATE_RE.findall(full_text)))[:10]
    numbers = list(dict.fromkeys(_NUMBER_RE.findall(full_text)))[:15]
    return {"names": people_orgs, "years": years, "numbers": numbers}


def _snippets(chunks: list[dict]) -> list[str]:
    out = []
    for c in chunks[:10]:
        if not c["text"]:
            continue
        snippet = c["text"][:260].strip()
        out.append(f"[{c['id']}] {snippet}...")
    return out


# Link / URL cleanup helpers
_GOOGLE_NEWS_ARTICLE_RE = re.compile(r"https://news\.google\.com/rss/articles/")

def _cleanup_link(url: str) -> str:
    # For Google News redirect-style article URLs keep as-is (cannot easily unwrap w/out fetch), but remove trailing query params except required 'oc=5'
    if _GOOGLE_NEWS_ARTICLE_RE.match(url):
        # Preserve only base + optional ?oc=5
        base, _, query = url.partition('?')
        if 'oc=5' in query:
            return base + '?oc=5'
        return base
    return url


def format_structured_page(html: str, url: str, chunk_id: str | None = None, mode: str | None = None) -> str:
    """Return structured multi-section text for LLM consumption.
    Sections: META, OUTLINE, KEYPOINTS, ENTITIES, LINKS, NAV, SNIPPETS, CHUNKS, NEXT
    If chunk_id provided, return focused chunk view plus minimal META/OUTLINE context.
    """
    # (We re-use existing implementation but add early outline-only branch)
    # NOTE: This edit only appends outline mode handling at the start.
    if not html:
        return f"META\nsource: {url}\nstatus: empty\n\n"
    soup = BeautifulSoup(html, "html.parser")
    title = _collapse(soup.title.get_text()) if soup.title else ""
    meta_desc = ""
    md = soup.find("meta", attrs={"name": "description"})
    if isinstance(md, Tag):
        content = md.get("content")
        if isinstance(content, str):
            meta_desc = _collapse(content)
    main = _select_main(soup)
    headings = _extract_headings(main)
    chunks = _build_chunks(headings, main)
    full_text = " \n".join(c["text"] for c in chunks if c.get("text"))
    links = _gather_links(main, url)
    nav_links = _extract_nav_links(soup, url)
    images = _extract_images(soup, url)
    outline_lines = _derive_outline(chunks)

    if mode == 'outline':
        link_lines = []
        for i, l in enumerate(links[:40], 1):
            link_lines.append(f"[L{i}] {l['text']} — {l['url']}")
        chunk_index_lines = [
            f"{c.get('id')} lvl={c.get('level')} tokens~{c.get('tokens','?')} {str(c.get('heading',''))[:120]}"
            for c in chunks[:60]
        ]
        thumbs = _top_thumbnail_images(images, 2)
        parts = [
            'META', f'source: {url}', f'fetched_at: {_now_iso()}', f'title: {title}', f'description: {meta_desc}' if meta_desc else '', '',
            'OUTLINE', *outline_lines[:80], '',
            'LINKS', *(link_lines or ['(none)']), '',
            'THUMBS', *( [f"![{(img.get('alt') or img.get('filename') or '')[:60]}]({img.get('src')})" for img in thumbs] or ['(none)'] ), '',
            'IMAGES', *( [f"![{(img.get('alt') or '')[:60]}]({img.get('src')})" for img in images[:8]] or ['(none)'] ), '',
            'CHUNKS', *chunk_index_lines, '', 'NEXT', 'Request a section id (e.g. sec-2) or follow a link (e.g. L5).']
        return "\n".join([p for p in parts if p])

    if mode == 'images':
        thumbs = _top_thumbnail_images(images, 2)
        parts = [
            'META', f'source: {url}', f'fetched_at: {_now_iso()}', f'title: {title}', '',
            'THUMBS', *( [f"![{(img.get('alt') or img.get('filename') or '')[:60]}]({img.get('src')})" for img in thumbs] or ['(none)'] ), '',
            'IMAGES', *( [f"{img.get('filename') or ''} | alt=\"{(img.get('alt') or '')[:80]}\" | w~{img.get('width_guess') or '?'} — {img.get('src')}" for img in images[:12]] or ['(none)'] ),
        ]
        return "\n".join([p for p in parts if p])

    # Focus mode if chunk_id requested
    focus_chunk = None
    if chunk_id:
        focus_chunk = next((c for c in chunks if c["id"].lower() == chunk_id.lower()), None)

    outline_lines = _derive_outline(chunks)

    if focus_chunk:
        neighbor_ids = [c["id"] for c in chunks]
        idx = neighbor_ids.index(focus_chunk["id"]) if focus_chunk["id"] in neighbor_ids else -1
        prev_id = neighbor_ids[idx-1] if idx > 0 else None
        next_id = neighbor_ids[idx+1] if idx >= 0 and idx < len(neighbor_ids)-1 else None
        parts = [
            "META",
            f"source: {url}",
            f"fetched_at: {_now_iso()}",
            f"title: {title}",
            f"description: {meta_desc}" if meta_desc else "",
            "",
            "OUTLINE",
            *outline_lines[:40],
            "",
            "CHUNK",
            f"id: {focus_chunk['id']}",
            f"heading: {focus_chunk['heading']}",
            f"level: {focus_chunk['level']}",
            f"tokens_est: {focus_chunk['tokens']}",
            "",
            focus_chunk["text"][:5000],
            "",
            "NEIGHBORS",
            f"previous: {prev_id or '-'}",
            f"next: {next_id or '-'}",
            "",
            "LINKS (local excerpt)",
        ]
        # limited links inside focus text
        local_links = []
        if links:
            for i, l in enumerate(links, 1):
                if len(local_links) >= 40:
                    break
                # naive filter: if link text appears in chunk text
                if l["text"] and l["text"] in focus_chunk["text"]:
                    local_links.append(f"[L{i}] {l['text']} — {l['url']}")
        parts.extend(local_links or ["(none)"])
        parts.extend([
            "",
            "NEXT",
            "You can request another section by id (e.g. sec-2) or follow a link (e.g. L5).",
        ])
        return "\n".join([p for p in parts if p is not None])

    # Global view
    kp = _keypoints(chunks)
    ents = _entities(full_text)
    snips = _snippets(chunks)

    link_lines = []
    for i, l in enumerate(links[:120], 1):
        link_lines.append(f"[L{i}] {l['text']} — {l['url']}")

    nav_lines = [f"• {n['text']} — {n['url']}" for n in nav_links[:40]]

    chunk_index_lines = [
        f"{c.get('id')} lvl={c.get('level')} tokens~{c.get('tokens','?')} {str(c.get('heading',''))[:120]}" for c in chunks[:80]
    ]

    parts = [
        "META",
        f"source: {url}",
        f"fetched_at: {_now_iso()}",
        f"title: {title}",
        f"description: {meta_desc}" if meta_desc else "",
        "",
        "OUTLINE",
        *outline_lines[:80],
        "",
        "KEYPOINTS",
        *(kp or ["(none extracted)"]),
        "",
        "ENTITIES",
        f"names: {', '.join(ents['names'])}" if ents.get("names") else "names: (none)",
        f"years: {', '.join(ents['years'])}" if ents.get("years") else "years: (none)",
        f"numbers: {', '.join(ents['numbers'])}" if ents.get("numbers") else "numbers: (none)",
        "",
        "LINKS",
        *(link_lines or ["(none)"]),
        "",
        "NAV",
        *(nav_lines or ["(none)"]),
        "",
        "SNIPPETS",
        *(snips or ["(none)"]),
        "",
        "CHUNKS",
        *chunk_index_lines,
        "",
        "NEXT",
        "Request a section via its id (e.g. sec-2) or ask to follow a specific link (e.g. L7).",
    ]
    return "\n".join([p for p in parts if p is not None])

# ------------------------------------------------------------------
# MCP endpoint modifications (tools list & call)
# ------------------------------------------------------------------

@app.route('/mcp', methods=['POST', 'GET'])
def mcp_endpoint():
    # Always provide SSE stream on GET (LM Studio probes this path for SSE fallback)
    if request.method == 'GET':
        headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
        return Response(_sse_stream(), headers=headers, mimetype='text/event-stream')

    # Parse JSON payload (don't fail on empty/invalid JSON)
    app.logger.debug(f"Received MCP payload: {request.data}")
    data = request.get_json(silent=True) or {}

    # If this looks like a JSON-RPC 2.0 request, handle MCP JSON-RPC methods
    if isinstance(data, dict) and data.get("jsonrpc") == "2.0" and ("method" in data or "id" in data):
        _id = data.get("id")
        method = data.get("method")
        params = data.get("params") or {}

        # initialize handshake
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "webtool-mcp", "version": "1.0.0"},
                "capabilities": {"tools": {}},
            }
            return jsonify(_jsonrpc_result(_id, result))

        # list tools
        if method in ("tools/list", "tools.list"):
            tools = [
                {
                    "name": "fetch_url",
                    "description": "Fetch and summarize a webpage with outline, links, navigation, snippets, and chunk index. Optional: fetch a specific chunk, outline-only mode, or follow a link id (L#) from the page.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string", "description": "HTTP or HTTPS URL (base page or target if not following)"},
                            "chunk_id": {"type": "string", "description": "Optional section id to return only that chunk (e.g., sec-3)"},
                            "section": {"type": "string", "description": "Alias for chunk_id"},
                            "mode": {"type": "string", "enum": ["outline"], "description": "outline = only META/OUTLINE/LINKS/CHUNKS/NEXT"},
                            "link_id": {"type": "string", "description": "Follow a link from the base page by id (e.g. L7)"}
                        },
                        "required": ["url"],
                    },
                },
                {
                    "name": "search_wikipedia",
                    "description": "Get a short summary from Wikipedia",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"query": {"type": "string", "description": "Search query"}},
                        "required": ["query"],
                    },
                },
                {
                    "name": "latvian_news",
                    "description": "Latest Latvian news headlines or topic search (optional query).",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"query": {"type": "string", "description": "Optional topic term"}},
                    },
                },
                {
                    "name": "search_duckduckgo",
                    "description": "DuckDuckGo Instant Answer: abstract + related links for a query.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"query": {"type": "string", "description": "Search phrase"}},
                        "required": ["query"],
                    },
                },
                {
                    "name": "web_search",
                    "description": "Multi-engine web search (duckduckgo, bing, google_cse, multi). Returns structured result list.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "engine": {"type": "string", "enum": ["duckduckgo", "bing", "google_cse", "multi"], "description": "Search engine (default duckduckgo)"},
                            "max_results": {"type": "number", "description": "Max results per engine (default 5)"},
                            "engines": {"type": "array", "items": {"type": "string"}, "description": "When engine=multi specify engines subset"}
                        }
                    },
                },
                {
                    "name": "site_search",
                    "description": "Convenience wrapper: site-specific search (builds site:domain query then calls web_search).",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "site": {"type": "string", "description": "Domain like example.com (no protocol)"},
                            "term": {"type": "string", "description": "Search term / phrase"},
                            "engine": {"type": "string", "enum": ["duckduckgo", "bing", "google_cse", "multi"], "description": "Search engine (default duckduckgo)"},
                            "max_results": {"type": "number", "description": "Max results (default 5)"},
                            "engines": {"type": "array", "items": {"type": "string"}, "description": "When engine=multi specify engines subset"}
                        },
                        "required": ["site", "term"]
                    },
                },
                {
                    "name": "quick_search",
                    "description": "Fast small-result search (duckduckgo→bing fallback) max 3 results for scoping.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"query": {"type": "string", "description": "Search phrase"}},
                        "required": ["query"],
                    },
                },
                {
                    "name": "ai_company_news",
                    "description": "Recent news headlines per AI/tech company (OpenAI, Google, Anthropic, Microsoft, Nvidia by default).",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "companies": {"type": "string", "description": "Optional comma/space separated company names"},
                            "limit": {"type": "number", "description": "Headlines per company (default 5)"}
                        }
                    },
                },
                {
                    "name": "get_system_prompt",
                    "description": "Return the internal system prompt / guidance for tool usage.",
                    "inputSchema": {"type": "object", "properties": {}},
                },
                {
                    "name": "luxriot_docs_status",
                    "description": "Status of Luxriot manuals index (ready, files, chunks).",
                    "inputSchema": {"type": "object", "properties": {}},
                },
                {
                    "name": "luxriot_docs_search",
                    "description": "Search Luxriot manuals using BM25. Params: query (string), k (number, default 5), doc (optional filter).",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "k": {"type": "number"},
                            "doc": {"type": "string"}
                        },
                        "required": ["query"]
                    },
                },
                {
                    "name": "luxriot_docs_search_hybrid",
                    "description": "Hybrid search over Luxriot manuals (BM25 + semantic if available). Params: query, k, doc.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "k": {"type": "number"},
                            "doc": {"type": "string"}
                        },
                        "required": ["query"]
                    },
                },
                {
                    "name": "luxriot_docs_get",
                    "description": "Get full text of a Luxriot chunk by chunk_id.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"chunk_id": {"type": "string", "description": "Chunk id returned by luxriot_docs_search"}},
                        "required": ["chunk_id"]
                    },
                },
                {
                    "name": "pairs_search_hybrid",
                    "description": "Search saved conversation pairs (memories) using hybrid semantic + token overlap. Returns a small JSON list.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "q": {"type": "string", "description": "Search query"},
                            "agent": {"type": "string", "description": "Optional filter: researcher|news|support"},
                            "limit": {"type": "number", "description": "Max results (default 10)"}
                        },
                        "required": ["q"]
                    }
                },
                {
                    "name": "pairs_get",
                    "description": "Get a saved pair by id (returns user_request, model_response, topic).",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"id": {"type": "string"}},
                        "required": ["id"]
                    }
                },
                {
                    "name": "pairs_annotate",
                    "description": "Create an annotation for a pair (span-level or note). Params: pair_id, target, start, end, text, sentiment, tags, note, rating.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "pair_id": {"type": "string"},
                            "target": {"type": "string"},
                            "start": {"type": "number"},
                            "end": {"type": "number"},
                            "text": {"type": "string"},
                            "sentiment": {"type": "string"},
                            "tags": {"type": "array", "items": {"type": "string"}},
                            "note": {"type": "string"},
                            "rating": {"type": "number"}
                        },
                        "required": ["pair_id"]
                    }
                },
                {
                    "name": "pairs_list_annotations",
                    "description": "List annotations for a pair. Params: pair_id.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"pair_id": {"type": "string"}},
                        "required": ["pair_id"]
                    }
                },
                {
                    "name": "vision_status",
                    "description": "Status of optional SigLIP-based vision (availability of model and OCR)",
                    "inputSchema": {"type": "object", "properties": {}}
                },
                {
                    "name": "vision_encode",
                    "description": "Encode an image (url or base64 data) via SigLIP and store it for search.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string"},
                            "data": {"type": "string", "description": "base64 data URI or raw base64"},
                            "include_vector": {"type": "boolean"}
                        }
                    }
                },
                {
                    "name": "vision_search",
                    "description": "Search indexed images by text using SigLIP text encoder.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "q": {"type": "string"},
                            "limit": {"type": "number"}
                        },
                        "required": ["q"]
                    }
                },
                {
                    "name": "vision_extract_from_url",
                    "description": "Fetch a web page, extract top images, index them with embeddings and OCR.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string"},
                            "limit": {"type": "number"}
                        },
                        "required": ["url"]
                    }
                },
            ]
            return jsonify(_jsonrpc_result(_id, {"tools": tools}))

        # call tool
        if method in ("tools/call", "tools.call"):
            name = None
            arguments = {}
            if isinstance(params, dict):
                name = (
                    params.get("name")
                    or params.get("toolName")
                    or params.get("function")
                    or params.get("method")
                )
                arguments = params.get("arguments") or params.get("args") or {}
                # Repair mojibake early (russian, etc.) and ensure dict
                arguments = _fix_args_mojibake(arguments)
                if not isinstance(arguments, dict):
                    arguments = {}

            # From here on, always use a narrowed dict view for safety
            args: dict[str, typing.Any] = arguments if isinstance(arguments, dict) else {}
            def _arg_str(key: str, default: str = "") -> str:
                v = args.get(key, default)
                try:
                    return str(v) if v is not None else default
                except Exception:
                    return default
            def _arg_opt_str(key: str) -> str | None:
                v = args.get(key)
                if v is None:
                    return None
                try:
                    s = str(v)
                    return s
                except Exception:
                    return None
            def _arg_int(key: str, default: int) -> int:
                v = args.get(key, default)
                try:
                    return int(v)
                except Exception:
                    return default
            def _arg_list_str(key: str) -> list[str] | None:
                v = args.get(key)
                if v is None:
                    return None
                if isinstance(v, list):
                    out: list[str] = []
                    for it in v:
                        try:
                            out.append(str(it))
                        except Exception:
                            pass
                    return out
                # single string
                if isinstance(v, str):
                    return [v]
                return None

            if name == "fetch_url":
                url = _arg_str("url", "")
                chunk_id = _arg_opt_str("chunk_id") or _arg_opt_str("section")
                mode = _arg_opt_str("mode")
                link_id = _arg_opt_str("link_id")
                cache_status = []
                # Use caches
                html, html_cache_hit, html_error = _cached_fetch_html(url)
                if html_error:
                    return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": f"Error fetching URL: {html_error}"}]}))
                if html_cache_hit:
                    cache_status.append("html_hit")
                # Outline cache applies only when outline mode and no chunk/link follow
                if mode == 'outline' and not chunk_id and not link_id:
                    cached_outline = _get_cached_outline(url, html)
                    if cached_outline is not None:
                        cache_status.append("outline_hit")
                        text = cached_outline
                        # annotate (reuse injection logic later)
                        marker = "META\n"
                        insertion = f"META\ncache_status: {','.join(cache_status)}\n"
                        if marker in text:
                            text2 = text.replace(marker, insertion, 1)
                            text = text2
                        else:
                            text = insertion + text
                        return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": text}]}))
                if html is None:
                    text = "Error: no HTML returned."  # should have been handled above
                else:
                    # If link_id provided, perform single-hop follow
                    if link_id and not chunk_id:
                        try:
                            base_soup = BeautifulSoup(html, 'html.parser')
                            main = _select_main(base_soup)
                            base_links = _gather_links(main, url)
                            # normalize link_id like 'L7' or '7'
                            m = re.match(r'[Ll]?(\d+)', str(link_id).strip())
                            target_structured = None
                            if not m:
                                raise ValueError(f"Invalid link_id format: {link_id}")
                            idx = int(m.group(1))
                            if idx < 1 or idx > len(base_links):
                                raise IndexError(f"link_id {link_id} out of range (1..{len(base_links)})")
                            chosen = base_links[idx-1]
                            target_url = chosen['url']
                            # fetch target
                            target_res = fetch_url(target_url)
                            if isinstance(target_res, dict) and target_res.get('error'):
                                text = f"Error following {link_id} → {target_url}: {target_res['error']}"
                            else:
                                target_html = target_res.get('content', '')
                                try:
                                    target_structured = format_structured_page(target_html, target_url, mode=mode)
                                except Exception as e:
                                    app.logger.exception("format_structured_page (follow) failed")
                                    trunc2 = target_html[:1000].replace('\n',' ')
                                    target_structured = f"Parser error on followed page: {e}\nSource: {target_url}\nSnippet: {trunc2}"
                                text = (
                                    "HISTORY\n"
                                    f"from_page: {url}\n"
                                    f"followed: {link_id} -> {target_url}\n"
                                    f"link_text: {chosen['text']}\n"
                                    "\n" + target_structured
                                )
                        except Exception as e:
                            app.logger.exception("link follow failed")
                            trunc = html[:800].replace('\n',' ')
                            text = f"Link follow error: {e}\nBase page snippet: {trunc}\nYou can retry with a different link_id or fetch without link_id."
                    else:
                        try:
                            text = format_structured_page(html, url, chunk_id=chunk_id, mode=mode)
                            # Always attempt to store if outline mode (no chunk/link)
                            if mode == 'outline' and not chunk_id and not link_id:
                                _store_cached_outline(url, text, html)
                        except Exception as e:
                            app.logger.exception("format_structured_page failed")
                            trunc = html[:1200].replace('\n', ' ')
                            text = f"Parser error, fallback raw snippet. Error: {e}\nSource: {url}\nSnippet: {trunc}"
                if cache_status:
                    marker = "META\n"
                    insertion = f"META\ncache_status: {','.join(cache_status)}\n"
                    if marker in text:
                        text2 = text.replace(marker, insertion, 1)
                        if text2 == text:
                            # fallback append after first line
                            lines = text.splitlines()
                            if lines and lines[0] == 'META':
                                lines.insert(1, f"cache_status: {','.join(cache_status)}")
                                text = "\n".join(lines)
                            else:
                                text = insertion + text
                        else:
                            text = text2
                    else:
                        text = insertion + text
                return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": text}]}))
            if name == "search_wikipedia":
                query = _arg_str("query", "")
                query = _maybe_fix_mojibake_py(query)
                res = search_wikipedia(query)
                # Keep JSON-encoded result as text, it's small
                return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False)}]}))
            if name == "latvian_news":
                q = _arg_opt_str("query")
                res = latvian_news(q)
                items = res.get("items") if isinstance(res, dict) else None
                if items:
                    lines = [f"Latvian News{' — ' + q if q else ''}:"]
                    for it in items:
                        title = it.get("title", "").strip()
                        url2 = it.get("url", "").strip()
                        pub = it.get("published", "").strip()
                        line = f"• {title} — {url2}"
                        if pub:
                            line += f" (Published: {pub})"
                        lines.append(line)
                    text = "\n".join(lines)
                else:
                    text = json.dumps(res, ensure_ascii=False)
                return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": text}]}))
            if name == "search_duckduckgo":
                query = _arg_str("query", "")
                query = _maybe_fix_mojibake_py(query)
                res = search_duckduckgo(query)
                return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False)}]}))
            if name == "web_search":
                # Fallback inference: accept 'q' or first stray string value if 'query' missing
                query = args.get("query") or args.get("q") or ""
                if not query and isinstance(args, dict):
                    for k, v in args.items():
                        if k not in {"engine", "max_results", "engines"} and isinstance(v, str) and v.strip():
                            query = v.strip()
                            break
                # Auto-prefer Google CSE when configured and engine not explicitly provided
                engine_arg = args.get("engine")
                engine: str
                if engine_arg in (None, "") and os.environ.get("GOOGLE_API_KEY") and os.environ.get("GOOGLE_CSE_ID"):
                    engine = "google_cse"
                else:
                    engine = str(engine_arg) if engine_arg is not None else "duckduckgo"
                max_results = _arg_int("max_results", 5)
                engines = _arg_list_str("engines")
                query = _maybe_fix_mojibake_py(str(query))
                res = web_search(query, engine=engine, max_results=max_results, engines=engines)
                return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False)}]}))
            if name == "site_search":
                site = _arg_str("site", "").strip()
                term = _arg_str("term", "").strip()
                engine = _arg_str("engine", "duckduckgo")
                max_results = _arg_int("max_results", 5)
                engines = _arg_list_str("engines")
                if not site or not term:
                    res = {"error": "site and term required"}
                else:
                    domain = site.replace("http://", "").replace("https://", "").split("/")[0]
                    query = f"site:{domain} {term}".strip()
                    res = web_search(query, engine=engine, max_results=max_results, engines=engines)
                    res["site"] = domain
                    res["original_term"] = term
                return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False)}]}))
            if name == "quick_search":
                query = _arg_str("query", "")
                res = quick_search(query)
                return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False)}]}))
            if name == "ai_company_news":
                companies_any = args.get("companies")
                companies: list[str] | str | None
                if companies_any is None:
                    companies = None
                elif isinstance(companies_any, list):
                    companies = [str(c) for c in companies_any]
                else:
                    companies = str(companies_any)
                limit = _arg_int("limit", 5)
                res = ai_company_news(companies, limit=limit)
                return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False)}]}))
            if name == "get_system_prompt":
                prm = get_system_prompt()
                return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": prm["prompt"]}]}))

            if name == "vision_status":
                st = vision_status()
                return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": json.dumps(_resp_json(st), ensure_ascii=False)}]}))
            if name == "vision_encode":
                try:
                    with app.test_request_context(json={
                        "url": args.get("url"),
                        "data": args.get("data"),
                        "include_vector": args.get("include_vector")
                    }):
                        r = vision_encode()
                    data = _resp_json(r)
                except Exception as e:
                    data = {"error": str(e)}
                return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]}))
            if name == "vision_search":
                try:
                    with app.test_request_context(json={"q": args.get("q"), "limit": args.get("limit")}):
                        r = vision_search()
                    data = _resp_json(r)
                except Exception as e:
                    data = {"error": str(e)}
                return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]}))
            if name == "vision_extract_from_url":
                try:
                    with app.test_request_context(json={"url": args.get("url"), "limit": args.get("limit")}):
                        r = vision_extract_from_url()
                    data = _resp_json(r)
                except Exception as e:
                    data = {"error": str(e)}
                return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]}))

            if name == "pairs_search_hybrid":
                q = _arg_str("q", "").strip()
                agent = _arg_opt_str("agent")
                limit = _arg_int("limit", 10)
                body = {"q": q, "agent": agent, "limit": limit}
                try:
                    with app.test_request_context(json=body):
                        res = http_search_pairs_hybrid()
                    # Flask Response -> get_json via direct call not guaranteed; fallback to dict if available
                    if hasattr(res, "get_json"):
                        payload = res.get_json()
                    else:
                        payload = res[0].get_json() if isinstance(res, tuple) else res
                except Exception as e:
                    payload = {"error": str(e)}
                return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]}))

            if name == "pairs_get":
                pid = _arg_str("id", "").strip()
                if not pid:
                    return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": json.dumps({"error":"id required"})}]}))
                item = get_pair(pid)
                if not item:
                    return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": json.dumps({"error":"not found"})}]}))
                return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": json.dumps(item, ensure_ascii=False)}]}))

            if name == "pairs_annotate":
                pid = _arg_str("pair_id", "").strip()
                if not pid:
                    return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": json.dumps({"error":"pair_id required"})}]}))
                payload = {
                    "target": _arg_str("target", "model_response"),
                    "start": args.get("start"),
                    "end": args.get("end"),
                    "text": _arg_str("text", ""),
                    "sentiment": _arg_str("sentiment", ""),
                    "tags": args.get("tags") if isinstance(args.get("tags"), list) else [],
                    "note": _arg_str("note", ""),
                    "rating": args.get("rating"),
                }
                try:
                    with app.test_request_context(json=payload):
                        res = http_create_annotation(pid)
                    data = _resp_json(res)
                except Exception as e:
                    data = {"error": str(e)}
                return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]}))

            if name == "pairs_list_annotations":
                pid = _arg_str("pair_id", "").strip()
                if not pid:
                    return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": json.dumps({"error":"pair_id required"})}]}))
                try:
                    with app.test_request_context():
                        res = http_list_annotations(pid)
                    data = _resp_json(res)
                except Exception as e:
                    data = {"error": str(e)}
                return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]}))

            if name == "luxriot_docs_status":
                idx = _luxriot_ensure_index()
                if not idx:
                    res = {"ready": False, "reason": "index unavailable (missing deps or PDFs)"}
                else:
                    res = {"ready": True, "files": idx.files, "chunks": len(idx.chunks), "built_at": idx.built_at}
                return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False)}]}))

            if name == "luxriot_docs_search":
                q = _arg_str("query", "")
                k = _arg_int("k", 5)
                doc = _arg_opt_str("doc")
                idx = _luxriot_ensure_index()
                if not idx:
                    res = {"ready": False, "items": []}
                else:
                    res = {"ready": True, "items": idx.search(q, k=k, doc=doc)}
                return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False)}]}))

            if name == "luxriot_docs_search_hybrid":
                q = _arg_str("query", "")
                k = _arg_int("k", 5)
                doc = _arg_opt_str("doc")
                idx = _luxriot_ensure_index()
                if not idx:
                    res = {"ready": False, "items": []}
                else:
                    res = {"ready": True, "items": idx.search_hybrid(q, k=k, doc=doc)}
                return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False)}]}))

            if name == "luxriot_docs_get":
                cid = _arg_opt_str("chunk_id") or _arg_opt_str("id")
                idx = _luxriot_ensure_index()
                if not cid:
                    err = {"error": "chunk_id required"}
                    return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": json.dumps(err, ensure_ascii=False)}]}))
                if not idx:
                    err = {"error": "index unavailable"}
                    return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": json.dumps(err, ensure_ascii=False)}]}))
                doc_obj = idx.get(str(cid))
                if not doc_obj:
                    err = {"error": "chunk not found"}
                    return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": json.dumps(err, ensure_ascii=False)}]}))
                return jsonify(_jsonrpc_result(_id, {"content": [{"type": "text", "text": json.dumps(doc_obj, ensure_ascii=False)}]}))

            return jsonify(_jsonrpc_error(_id, -32601, f"Unknown tool '{name}'"))

        # Unknown JSON-RPC method
        return jsonify(_jsonrpc_error(_id, -32601, f"Unknown method '{method}'"))

    # ------------- Legacy simple payloads for manual testing -------------
    # Determine function name and arguments from either 'function'/'args' or 'name'/'arguments'
    function_name = None
    args = {}

    if isinstance(data, dict):
        if 'function' in data:
            function_name = data.get('function')
            args = data.get('args', {}) or {}
        elif 'name' in data:
            function_name = data.get('name')
            args = data.get('arguments', {}) or {}

    # If still not known, try to infer from payload keys
    payload = args if isinstance(args, dict) and args else data
    if not function_name:
        # For POSTs without JSON-RPC and no function specified, return a JSON-RPC error envelope
        # so MCP clients parsing strict JSON-RPC won't fail.
        hint = "Send JSON-RPC 2.0 or include 'function'/'name'. (If using curl, ensure -d JSON is in the same command; newline breaks will drop the body.)"
        return jsonify(_jsonrpc_error(None, -32600, "Invalid Request", {"hint": hint}))

    # Handle generic info/handshake-like names gracefully
    if function_name in ('initialize', 'list_tools', 'health', 'info'):
        result = available_functions_info()
        # Attach system prompt in legacy info for convenience
        try:
            result["system_prompt_head"] = get_system_prompt()["prompt"].splitlines()[:6]
        except Exception:
            result["system_prompt_head"] = ["(failed to load system prompt)"]
        return jsonify({"response": result})

    # Dispatch to helper functions
    if function_name == 'fetch_url':
        url = ''
        if isinstance(payload, dict):
            url = payload.get('url', '')
        result = fetch_url(url)
    elif function_name == 'search_wikipedia':
        query = ''
        if isinstance(payload, dict):
            query = payload.get('query', '')
        result = search_wikipedia(query)
    elif function_name == 'latvian_news':
        query = ''
        if isinstance(payload, dict):
            query = payload.get('query', '')
        result = latvian_news(query)
    elif function_name == 'get_system_prompt':
        result = get_system_prompt()
    else:
        # Instead of hard error, respond with info so clients don't fail to connect
        app.logger.error(f"Unknown function '{function_name}'")
        return jsonify({"response": available_functions_info(), "warning": f"Unknown function '{function_name}'"})

    # Return format expected by LM Studio's legacy manual testing: {"response": ...}
    return jsonify({"response": result})

if __name__ == "__main__":
    # Simple health check endpoint for quick diagnostics
    @app.route('/health', methods=['GET'])
    def health():
        return jsonify({"status": "ok"})

    app.run(host="0.0.0.0", port=5000)