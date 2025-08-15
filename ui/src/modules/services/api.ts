// Prefer explicit env override; fallback to same host:5000 Flask integrated proxy
const DEFAULT_PROXY_BASE = `${location.protocol}//${location.hostname}:5000/proxy`;
const BASE = (import.meta as any).env?.VITE_BACKEND_BASE || DEFAULT_PROXY_BASE;

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

export type ChatStreamEvent =
  | { type: 'session'; session_id: string }
  | { type: 'assistant_token'; text: string; phase: 'initial'|'final' }
  | { type: 'assistant_final_token'; text: string }
  | { type: 'reasoning_token'; text: string; phase: 'initial'|'final' }
  | { type: 'assistant_done'; phase: 'initial' }
  | { type: 'tool_start'; name: string; arguments: any }
  | { type: 'tool'; name?: string; content?: string; error?: string }
  | { type: 'done'; session_id: string; assistant: string; assistant_reasoning: string; tool_output?: string|null }
  | { type: 'error'; message: string };

export function streamChat(params: { user: string; session_id?: string; model?: string|null; system_prompt?: string|null }, onEvent: (e: ChatStreamEvent)=>void){
  const url = new URL(`${BASE}/chat_stream`);
  url.searchParams.set('user', params.user);
  if(params.session_id) url.searchParams.set('session_id', params.session_id);
  if(params.model) url.searchParams.set('model', String(params.model));
  if(params.system_prompt) url.searchParams.set('system_prompt', String(params.system_prompt));
  const es = new EventSource(url.toString());
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
    try{ const d = JSON.parse((ev as MessageEvent).data); onEvent({type:'done', session_id:d.session_id, assistant:d.assistant||'', assistant_reasoning:d.assistant_reasoning||'', tool_output:d.tool_output||null}); }catch{}
    es.close();
  });
  es.addEventListener('error', ev=>{
    try{ const d = JSON.parse((ev as MessageEvent).data); onEvent({type:'error', message:d.message||'stream error'}); }catch{ onEvent({type:'error', message:'stream error'});} 
    es.close();
  });
  return es;
}
