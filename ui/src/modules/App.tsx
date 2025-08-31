import React, { useEffect, useState } from 'react';
import { ChatPanel } from './ChatPanel';
import { Sidebar } from './Sidebar';
import { H1 } from './ui';
import { getSystemPrompt, getPair, attachPairToSession, getLuxriotStatus } from './services/api';
import { combinePrompt, type PersonaId } from './presets';

export default function App() {
  const [dark, setDark] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [model, setModel] = useState<string | null>('');
  const [basePrompt, setBasePrompt] = useState<string>('');
  const [persona, setPersona] = useState<PersonaId>('researcher');
  const [messages, setMessages] = useState<any[]>([]);
  const [streamRef, setStreamRef] = useState<EventSource|null>(null);
  const [markdown, setMarkdown] = useState<boolean>(false);
  const [luxriotReady, setLuxriotReady] = useState<{ready:boolean; hasEmb?: boolean}>({ready:false});

  useEffect(()=>{
    // Prefill system prompt once
    (async()=>{
  try{ const p = await getSystemPrompt(); if(p) setBasePrompt(p); }catch{}
    })();
  },[]);

  useEffect(()=>{
    (async()=>{
      try{ const s = await getLuxriotStatus(); setLuxriotReady({ ready: !!s.ready, hasEmb: !!s.has_embeddings }); }catch{}
    })();
  },[]);

  function handleNewChat(){
    setSessionId(null);
    setMessages([]);
  }
  async function handleAttachPair(p: { id: string }){
    try{
      // Ensure a session exists
      const sid = sessionId || crypto.randomUUID();
      if(!sessionId) setSessionId(sid);
      // Fetch full pair to build a readable block locally
      const item = await getPair(p.id);
  const next = [...messages];
  // Insert as separate messages to mirror actual conversation
  if(item.user_request) next.push({ role: 'user', content: item.user_request });
  if(item.model_response) next.push({ role: 'assistant', content: item.model_response });
  setMessages(next);
      // Also notify backend to persist the attach event in the session history
      await attachPairToSession(item.id, sid);
    }catch{}
  }
  return (
    <div className={dark ? 'dark' : ''}>
      <div className="flex h-screen w-full bg-paper-50 text-ink-900 dark:bg-ink-900 dark:text-paper-100 transition-colors">
        <Sidebar
          collapsed={!sidebarOpen}
          onNewChat={handleNewChat}
          model={model}
          setModel={m=>setModel(m)}
          basePrompt={basePrompt}
          persona={persona}
          setPersona={setPersona}
          sessionId={sessionId}
          onAttachPair={handleAttachPair}
        />
        <div className="flex-1 flex flex-col min-h-0">
          <header className="px-4 sm:px-8 py-3 sm:py-4 border-b border-paper-200 dark:border-ink-700 flex items-center justify-between bg-paper-100/80 dark:bg-ink-800/60 backdrop-blur supports-[backdrop-filter]:bg-paper-100/60">
            <div className="flex items-center gap-3">
              <button onClick={()=>setSidebarOpen(s=>!s)} className="text-sm px-3 py-1.5 rounded border border-paper-200 dark:border-ink-700 bg-paper-50 dark:bg-ink-900 hover:bg-paper-100 dark:hover:bg-ink-800">{sidebarOpen? 'Hide panel':'Show panel'}</button>
              <H1 className="!text-[2.0rem] sm:!text-[2.2rem]">Webtool</H1>
              {luxriotReady.ready && (
                <span className="text-[11px] px-2 py-0.5 rounded-full border border-paper-300 dark:border-ink-700 bg-paper-50 dark:bg-ink-800 text-ink-700 dark:text-paper-300">
                  Docs: {luxriotReady.hasEmb ? 'Hybrid' : 'BM25-only'}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <button onClick={()=>setDark(d=>!d)} className="text-sm px-3 py-1.5 rounded bg-ink-900 text-paper-100 hover:bg-ink-800 dark:bg-ink-700 dark:hover:bg-ink-600">{dark? 'Light':'Dark'}</button>
              <button onClick={()=>setMarkdown(m=>!m)} disabled={!!streamRef} className="text-sm px-3 py-1.5 rounded border border-paper-200 dark:border-ink-700 bg-paper-50 dark:bg-ink-900 hover:bg-paper-100 dark:hover:bg-ink-800 disabled:opacity-50">{markdown? 'Markdown: On':'Markdown: Off'}</button>
              {streamRef && <button onClick={()=>{ try{streamRef.close();}catch{}; setStreamRef(null); }} className="text-sm px-3 py-1.5 rounded border border-paper-200 dark:border-ink-700 bg-paper-50 dark:bg-ink-900 hover:bg-paper-100 dark:hover:bg-ink-800">Stop</button>}
            </div>
          </header>
          <ChatPanel
            sessionId={sessionId}
            setSessionId={setSessionId}
            model={model || undefined}
            systemPrompt={combinePrompt(basePrompt || '', persona)}
            messages={messages}
            setMessages={setMessages}
            setStreamingRef={setStreamRef}
            markdown={markdown}
          />
        </div>
      </div>
    </div>
  );
}
