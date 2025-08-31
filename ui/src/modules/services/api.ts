// Backend URL config (no hardcoded host:port)
// Priority:
// 1) VITE_BACKEND_ROOT: e.g. https://demo.example.com:5000
// 2) If VITE_BACKEND_BASE is provided as a full /proxy URL, derive root from it
// 3) Fallback to same-host default port 5000 (only for local dev)
const VITE = (import.meta as any).env || {};
const deriveRootFromBase = (base: string) => {
  try{ const u = new URL(base); return `${u.protocol}//${u.host}`; }catch{ return base.replace(/\/?proxy\/?$/, ''); }
};
const DEFAULT_ROOT = `${location.protocol}//${location.hostname}:5000`;
export const BACKEND_ROOT = VITE.VITE_BACKEND_ROOT || (VITE.VITE_BACKEND_BASE ? deriveRootFromBase(VITE.VITE_BACKEND_BASE) : DEFAULT_ROOT);
export const PROXY_BASE = VITE.VITE_BACKEND_BASE || `${BACKEND_ROOT}/proxy`;
// If VITE_BACKEND_BASE is relative (e.g., '/proxy'), use same-origin '/mcp'
const MCP_SAME_ORIGIN = (typeof VITE.VITE_BACKEND_BASE === 'string' && VITE.VITE_BACKEND_BASE.startsWith('/'));
export const MCP_BASE = MCP_SAME_ORIGIN ? '/mcp' : `${BACKEND_ROOT}/mcp`;
export const BASE = PROXY_BASE;
// When BACKEND_ROOT resolves to '/', treat it as empty for relative fetch paths
const REL_ROOT = (BACKEND_ROOT && BACKEND_ROOT !== '/' ? BACKEND_ROOT : '');

export async function fetchModels(){
  const r = await fetch(`${BASE}/models`);
  if(!r.ok) throw new Error('models failed');
  return r.json();
}

export interface ChatSendPayload {
  session_id?: string;
  user: string;
  model?: string | null;
  system_prompt?: string | null;
}

export async function sendChat(p: ChatSendPayload){
  const r = await fetch(`${BASE}/chat`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({...p, stream:false})});
  if(!r.ok) throw new Error('chat failed');
  return r.json();
}

export async function getSession(id: string){
  const r = await fetch(`${BASE}/session/${id}`);
  if(!r.ok) throw new Error('session failed');
  return r.json();
}

export async function callTool(name: string, arguments_: any = {}){
  const r = await fetch(`${BASE}/tool`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ name, arguments: arguments_ }) });
  if(!r.ok) throw new Error('tool failed');
  return r.json();
}

// Convenience: fetch URL in outline or images mode through MCP (returns raw text)
export async function fetchUrlStructured(url: string, mode: 'outline'|'images' = 'outline'){
  const payload = { jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: 'fetch_url', arguments: { url, mode } } };
  const r = await fetch(`${MCP_BASE}`, { method: 'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
  if(!r.ok) throw new Error('fetch_url failed');
  const data = await r.json();
  try{ return (data.result.content[0].text as string) || ''; }catch{ return ''; }
}

export async function getSystemPrompt(){
  // Invoke MCP get_system_prompt and return prompt text
  const payload = { jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: 'get_system_prompt', arguments: {} } };
  const r = await fetch(`${MCP_BASE}`, { method: 'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
  if(!r.ok) throw new Error('get_system_prompt failed');
  const data = await r.json();
  try{
    return data.result.content[0].text as string;
  }catch{
    return '';
  }
}

// Pairs Library API
export interface PairListItem {
  id: string;
  created_at: number;
  agent_type: string;
  user_request: string;
  model_response: string;
  topic: string;
}

export async function listPairs(params?: { agent?: string; limit?: number }){
  let path = `${REL_ROOT}/pairs`;
  const sp = new URLSearchParams();
  if(params?.agent) sp.set('agent', params.agent);
  if(params?.limit) sp.set('limit', String(params.limit));
  if(Array.from(sp.keys()).length > 0) path += `?${sp.toString()}`;
  const r = await fetch(path);
  if(!r.ok) throw new Error('pairs list failed');
  const data = await r.json();
  return (data.items || []) as PairListItem[];
}

export async function deletePair(id: string){
  const base = REL_ROOT;
  const r = await fetch(`${base}/pairs/${id}`, { method: 'DELETE' });
  if(!r.ok) throw new Error('delete pair failed');
  return r.json();
}

export async function getPair(id: string){
  const base = REL_ROOT;
  const r = await fetch(`${base}/pairs/${id}`);
  if(!r.ok) throw new Error('get pair failed');
  return r.json();
}

export async function attachPairToSession(pairId: string, sessionId: string){
  const base = REL_ROOT;
  const r = await fetch(`${base}/pairs/attach`, { method: 'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ id: pairId, session_id: sessionId }) });
  if(!r.ok) throw new Error('attach failed');
  return r.json();
}

export async function searchPairsHybrid(q: string, opts?: { agent?: string; limit?: number }){
  const base = REL_ROOT;
  const r = await fetch(`${base}/pairs/search_hybrid`, { method: 'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ q, agent: opts?.agent, limit: opts?.limit || 10 }) });
  if(!r.ok) throw new Error('hybrid search failed');
  const data = await r.json();
  return (data.items || []) as PairListItem[];
}

export type ChatStreamEvent =
  | { type: 'session'; session_id: string }
  | { type: 'assistant_token'; text: string; phase: 'initial'|'final' }
  | { type: 'assistant_final_token'; text: string }
  | { type: 'reasoning_token'; text: string; phase: 'initial'|'final' }
  | { type: 'assistant_done'; phase: 'initial' }
  | { type: 'tool_start'; name: string; arguments: any }
  | { type: 'tool'; name?: string; content?: string; error?: string }
  | { type: 'done'; session_id: string; assistant: string; assistant_reasoning: string; tool_output?: string|null; pair_id?: string|null }
  | { type: 'error'; message: string };

export function streamChat(params: { user: string; session_id?: string; model?: string|null; system_prompt?: string|null }, onEvent: (e: ChatStreamEvent)=>void){
  const sp = new URLSearchParams();
  sp.set('user', params.user);
  if(params.session_id) sp.set('session_id', params.session_id);
  if(params.model) sp.set('model', String(params.model));
  if(params.system_prompt) sp.set('system_prompt', String(params.system_prompt));
  const es = new EventSource(`${BASE}/chat_stream?${sp.toString()}`);
  es.addEventListener('session', ev=>{
    try{ onEvent({type:'session', ...(JSON.parse((ev as MessageEvent).data))}); }catch{}
  });
  es.addEventListener('assistant_token', ev=>{
    try{ const d = JSON.parse((ev as MessageEvent).data); onEvent({type:'assistant_token', text:d.text||'', phase:d.phase||'initial'}); }catch{}
  });
  es.addEventListener('assistant_final_token', ev=>{
    try{ const d = JSON.parse((ev as MessageEvent).data); onEvent({type:'assistant_final_token', text:d.text||''}); }catch{}
  });
  es.addEventListener('reasoning_token', ev=>{
    try{ const d = JSON.parse((ev as MessageEvent).data); onEvent({type:'reasoning_token', text:d.text||'', phase:d.phase||'initial'}); }catch{}
  });
  es.addEventListener('assistant_done', ()=> onEvent({type:'assistant_done', phase:'initial'}));
  es.addEventListener('tool_start', ev=>{
    try{ const d = JSON.parse((ev as MessageEvent).data); onEvent({type:'tool_start', name:d.name, arguments:d.arguments}); }catch{}
  });
  es.addEventListener('tool', ev=>{
    try{ const d = JSON.parse((ev as MessageEvent).data); onEvent({type:'tool', name:d.name, content:d.content, error:d.error}); }catch{}
  });
  es.addEventListener('done', ev=>{
  try{ const d = JSON.parse((ev as MessageEvent).data); onEvent({type:'done', session_id:d.session_id, assistant:d.assistant||'', assistant_reasoning:d.assistant_reasoning||'', tool_output:d.tool_output||null, pair_id:d.pair_id||null}); }catch{}
    es.close();
  });
  es.addEventListener('error', ev=>{
    try{ const d = JSON.parse((ev as MessageEvent).data); onEvent({type:'error', message:d.message||'stream error'}); }catch{ onEvent({type:'error', message:'stream error'});} 
    es.close();
  });
  return es;
}

// Annotations API
export interface Annotation {
  id: string;
  pair_id: string;
  created_at: number;
  target: string;
  start?: number|null;
  end?: number|null;
  text: string;
  sentiment?: 'positive' | 'negative' | '';
  tags?: string[];
  note?: string;
  rating?: number|null;
}

export async function createAnnotation(pairId: string, payload: Partial<Omit<Annotation,'id'|'pair_id'|'created_at'>>){
  const base = REL_ROOT;
  const r = await fetch(`${base}/pairs/${pairId}/annotations`, { method: 'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
  if(!r.ok) throw new Error('create annotation failed');
  return r.json() as Promise<Annotation>;
}

export async function listAnnotations(pairId: string){
  const base = REL_ROOT;
  const r = await fetch(`${base}/pairs/${pairId}/annotations`);
  if(!r.ok) throw new Error('list annotations failed');
  const data = await r.json();
  return (data.items || []) as Annotation[];
}

export async function deleteAnnotation(pairId: string, annId: string){
  const base = REL_ROOT;
  const r = await fetch(`${base}/pairs/${pairId}/annotations/${annId}`, { method: 'DELETE' });
  if(!r.ok) throw new Error('delete annotation failed');
  return r.json();
}

export async function listPairsWithAnnotations(opts?: { sentiment?: 'positive'|'negative'|''; agent?: string; limit?: number }){
  const sp = new URLSearchParams();
  if(opts?.sentiment) sp.set('sentiment', opts.sentiment);
  if(opts?.agent) sp.set('agent', opts.agent);
  if(opts?.limit) sp.set('limit', String(opts.limit));
  const r = await fetch(`${REL_ROOT}/pairs/with_annotations?${sp.toString()}`);
  if(!r.ok) throw new Error('pairs with annotations failed');
  const data = await r.json();
  return (data.items || []) as (PairListItem & { annotation_count: number })[];
}

export function exportAnnotationsDataset(format: 'jsonl'|'json'|'csv' = 'jsonl', opts?: { since?: number; until?: number }){
  const sp = new URLSearchParams();
  sp.set('format', format);
  if(opts?.since) sp.set('since', String(opts.since));
  if(opts?.until) sp.set('until', String(opts.until));
  const url = `${REL_ROOT}/admin/annotations_export?${sp.toString()}`;
  // open in new tab to trigger download
  window.open(url, '_blank');
}

export async function getAnnotationsSummary(opts?: { since?: number; until?: number }){
  const sp = new URLSearchParams();
  if(opts?.since) sp.set('since', String(opts.since));
  if(opts?.until) sp.set('until', String(opts.until));
  const r = await fetch(`${REL_ROOT}/admin/annotations_summary?${sp.toString()}`);
  if(!r.ok) throw new Error('annotations summary failed');
  return r.json() as Promise<{
    total_annotations: number;
    total_pairs: number;
    time_range: { since?: number; until?: number };
    by_sentiment: { positive: number; negative: number; neutral: number };
    top_tags: Array<{ tag: string; count: number }>;
    by_agent: Record<string, number>;
  }>;
}

// Luxriot status
export async function getLuxriotStatus(){
  const r = await fetch(`${REL_ROOT}/luxriot/status`);
  if(!r.ok) throw new Error('luxriot status failed');
  return r.json() as Promise<{ ready: boolean; files?: string[]; chunks?: number; embed_model?: string|null; has_embeddings?: boolean }>;
}
