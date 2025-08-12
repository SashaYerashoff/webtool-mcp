const BASE = (import.meta as any).env?.VITE_BACKEND_BASE || 'http://localhost:7000';

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
