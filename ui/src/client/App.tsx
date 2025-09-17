import React, { useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { getSystemPrompt, streamChat, type ChatStreamEvent } from '../modules/services/api';

type Msg = { id: string; role: 'user'|'assistant'|'tool'; content: string };

export default function App(){
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState('');
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  const [systemPrompt, setSystemPrompt] = useState<string>('');
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(()=>{ getSystemPrompt().then(setSystemPrompt).catch(()=>{}); },[]);
  useEffect(()=>{ scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' }); }, [messages]);

  const send = async ()=>{
    const text = input.trim();
    if(!text || busy) return;
    setInput('');
    const userMsg: Msg = { id: crypto.randomUUID(), role:'user', content: text };
    setMessages(prev=>[...prev, userMsg, { id: 'pending', role:'assistant', content: '' }]);
    setBusy(true);
    const es = streamChat({ user: text, session_id: sessionId, system_prompt: systemPrompt || null, model: null }, (ev: ChatStreamEvent)=>{
      if(ev.type === 'session'){
        setSessionId(ev.session_id);
      } else if(ev.type === 'assistant_token'){
        setMessages(prev=> prev.map(m=> m.id==='pending' ? { ...m, content: (m.content||'') + ev.text } : m));
      } else if(ev.type === 'assistant_final_token'){
        setMessages(prev=> prev.map(m=> m.id==='pending' ? { ...m, content: (m.content||'') + ev.text } : m));
      } else if(ev.type === 'tool_start'){
        // Optional: show tool calls inline
        setMessages(prev=>[...prev.filter(m=>m.id!=='pending'), { id: crypto.randomUUID(), role:'tool', content: `→ tool ${ev.name}(${JSON.stringify(ev.arguments)})` }, { id:'pending', role:'assistant', content:'' }]);
      } else if(ev.type === 'tool'){
        if(ev.error){
          setMessages(prev=>[...prev.filter(m=>m.id!=='pending'), { id: crypto.randomUUID(), role:'tool', content: `✖ tool error: ${ev.error}` }, { id:'pending', role:'assistant', content:'' }]);
        } else {
          const c = (ev.content ?? '').toString();
          setMessages(prev=>[...prev.filter(m=>m.id!=='pending'), { id: crypto.randomUUID(), role:'tool', content: c }, { id:'pending', role:'assistant', content:'' }]);
        }
      } else if(ev.type === 'done'){
        setMessages(prev=> prev.map(m=> m.id==='pending' ? { ...m, id: crypto.randomUUID() } : m));
        setBusy(false);
      } else if(ev.type === 'error'){
        setMessages(prev=>[...prev.filter(m=>m.id!=='pending'), { id: crypto.randomUUID(), role:'assistant', content: `Error: ${ev.message}` }]);
        setBusy(false);
      }
    });
  };

  const Markdown = useMemo(()=> (props: {children: string})=> (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        img: ({node, ...rest}) => <img {...rest} style={{maxWidth:'100%', borderRadius:8}} />,
        a: ({node, ...rest}) => <a {...rest} target="_blank" rel="noreferrer" className="text-blue-600 underline" />,
        code: (props) => (
          <code className={"px-1.5 py-0.5 rounded bg-slate-100 " + ((props as any).className||'')} {...(props as any)}>{(props as any).children}</code>
        ),
      }}
    >{props.children}</ReactMarkdown>
  ), []);

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b px-4 py-3 flex items-center justify-between">
        <div className="font-semibold">Evo Agent Client</div>
        <div className="text-sm text-slate-500">Session: {sessionId ? sessionId.slice(0,8) : '—'}</div>
      </header>
      <main className="flex-1 grid grid-rows-[1fr_auto]">
        <div ref={scrollRef} className="overflow-auto px-4 py-4 space-y-4">
          {messages.map(m=> (
            <div key={m.id} className={m.role==='user' ? 'text-right' : ''}>
              <div className={"inline-block max-w-3xl rounded-2xl px-4 py-2 " + (m.role==='user' ? 'bg-slate-900 text-white' : m.role==='tool' ? 'bg-amber-50 text-amber-900' : 'bg-slate-100')}>
                {m.role==='assistant' ? <Markdown>{m.content}</Markdown> : <div className="whitespace-pre-wrap">{m.content}</div>}
              </div>
            </div>
          ))}
          {messages.length===0 && (
            <div className="text-center text-slate-500 pt-10">Ask anything. The agent can browse, search, and use vision tools.</div>
          )}
        </div>
        <form className="border-t p-3 flex gap-2" onSubmit={(e)=>{e.preventDefault(); send();}}>
          <textarea
            className="flex-1 border rounded-md p-2 min-h-[44px] max-h-[160px]"
            placeholder="Type your message..."
            value={input}
            onChange={(e)=>setInput(e.target.value)}
            onKeyDown={(e)=>{
              if(e.key==='Enter' && !e.shiftKey){ e.preventDefault(); send(); }
            }}
          />
          <button type="submit" disabled={busy} className={"px-4 py-2 rounded-md text-white "+(busy?'bg-slate-400':'bg-slate-900 hover:bg-slate-800')}>{busy?'Sending…':'Send'}</button>
        </form>
      </main>
    </div>
  );
}
