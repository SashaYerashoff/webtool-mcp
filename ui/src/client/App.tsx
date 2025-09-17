import React, { useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { getSystemPrompt, streamChat, sendChat, type ChatStreamEvent } from '../modules/services/api';
import './mock.css';

type Msg = { id: string; role: 'user'|'assistant'|'tool'; content: string };
type Attachment = { name: string; type?: string; size?: number };

export default function App(){
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState('');
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  const [systemPrompt, setSystemPrompt] = useState<string>('');
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [attachments, setAttachments] = useState<Attachment[]>([]);

  useEffect(()=>{ getSystemPrompt().then(setSystemPrompt).catch(()=>{}); },[]);
  useEffect(()=>{ scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' }); }, [messages]);

  const send = async ()=>{
    const text = input.trim();
    if(!text || busy) return;
    setInput('');
    const userMsg: Msg = { id: crypto.randomUUID(), role:'user', content: text };
    setMessages(prev=>[...prev, userMsg, { id: 'pending', role:'assistant', content: '' }]);
    setBusy(true);
  const es = streamChat({ user: text, session_id: sessionId, system_prompt: systemPrompt || null, model: null }, async (ev: ChatStreamEvent)=>{
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
        // Fallback: try non-streaming POST if SSE fails (e.g., proxy/SSE issues)
        try{
          const resp = await sendChat({ user: text, session_id: sessionId, system_prompt: systemPrompt || null, model: null });
          const assistant = (resp as any)?.assistant || '';
          setSessionId((resp as any)?.session_id || sessionId);
          if(assistant){
            setMessages(prev=> prev.map(m=> m.id==='pending' ? { ...m, id: crypto.randomUUID(), content: assistant } : m));
          }else{
            setMessages(prev=>[...prev.filter(m=>m.id!=='pending'), { id: crypto.randomUUID(), role:'assistant', content: `Error: ${ev.message}` }]);
          }
        }catch(err:any){
          setMessages(prev=>[...prev.filter(m=>m.id!=='pending'), { id: crypto.randomUUID(), role:'assistant', content: `Error: ${ev.message}` }]);
        }finally{
          setBusy(false);
        }
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

  const attachSummary = attachments.length ? `Attached: ${attachments.map(a=>a.name).slice(0,3).join(', ')}${attachments.length>3?` (+${attachments.length-3} more)`:''}` : '';

  const prefill = (scope: string, tip: string)=>{
    const suggest = `${scope}: ${tip || ''}`.trim();
    setInput(suggest);
  };

  return (
    <div id="luxriot-agent" className="wrapper" role="application" aria-label="Luxriot support agent" data-theme="dark">
      <header className="brand">
        <div className="logo" aria-hidden="true"></div>
        <div className="brand-name">Luxriot</div>
      </header>

      <main className="grid" aria-label="Topic shortcuts">
        <section className="card" aria-labelledby="events-title" tabIndex={0} role="button" onClick={()=>prefill('Events & Actions','How to count cars on a parking lot?')}>
          <h2 id="events-title">Events &amp; Actions</h2>
          <p>I can help set scenarios, troubleshoot issues and answer questions. Don’t know what to start with?</p>
          <small className="eyebrow">Scenario of the day: <em>How to count cars on a parking lot?</em></small>
        </section>

        <section className="card" aria-labelledby="devices-title" tabIndex={0} role="button" onClick={()=>prefill('Device Configuration','My camera is not in the list of supported, can I do smth?')}>
          <h2 id="devices-title">Device Configuration</h2>
          <p>Need to add a new camera? Understand how to set channels? What all those settings even mean? ONVIF? Troubleshoot?</p>
          <small className="eyebrow">Here’s the starter: <em>My camera is not in the list of supported, can I do smth?</em></small>
        </section>

        <section className="card" aria-labelledby="server-title" tabIndex={0} role="button" onClick={()=>prefill('Server Configuration','How to set recording replication to the RAID in a different subnet?')}>
          <h2 id="server-title">Server Configuration</h2>
          <p>Don’t know what to do with the Recording server? Maybe you need to set disks? Looking for multi‑step troubleshoot to pinpoint an issue?</p>
          <small className="eyebrow">Try this: <em>How to set recording replication to the RAID in a different subnet?</em></small>
        </section>

        <section className="card" aria-labelledby="services-title" tabIndex={0} role="button" onClick={()=>prefill('Services configuration','Can I add i‑PRO Active Guard to the Luxriot Evo S?')}>
          <h2 id="services-title">Services configuration</h2>
          <p>Access controls? External analytics? Something very special? I can help to solve misteries.</p>
          <small className="eyebrow">Here’s the tip: <em>Can I add i‑PRO Active Guard to the Luxriot Evo S?</em></small>
        </section>
      </main>

      <section className="assistant" aria-label="Assistant and message composer">
        <div className="agent-card">
          <div className="avatar" aria-hidden="true">AI</div>
          <div>
            <h3>Evo AI</h3>
            <div className="sub">Hi! I am your support agent.</div>
            <p className="sub intro">I am trained on an extensive range of Luxriot data and can answer a lot of your questions or help with multi‑step troubleshooting. Select a topic from the above or provide your issue description.</p>
            <div className="agent-note">“I can make mistakes, but I am trying my best and constantly evolving.”</div>
          </div>
        </div>

        <div className="messages" ref={scrollRef}>
          {messages.map(m=> (
            <div key={m.id} className={"bubble "+m.role}>
              {m.role==='assistant' ? (
                <>
                  <div style={{fontWeight:800, marginBottom:4}}>Evo AI</div>
                  <Markdown>{m.content}</Markdown>
                </>
              ) : m.role==='user' ? (
                <>
                  <div style={{fontWeight:800, marginBottom:4}}>You</div>
                  <div className="whitespace-pre-wrap">{m.content}</div>
                </>
              ) : (
                <div className="whitespace-pre-wrap">{m.content}</div>
              )}
            </div>
          ))}
        </div>

        <form className="composer" onSubmit={(e)=>{e.preventDefault(); send();}}>
          <label htmlFor="prompt" id="prompt-label" className="sr-only">Your prompt</label>
          <textarea id="prompt" name="prompt" placeholder="Your prompt here:" aria-labelledby="prompt-label"
            value={input}
            onChange={(e)=>setInput(e.target.value)}
            onKeyDown={(e)=>{ if((e.ctrlKey||e.metaKey) && e.key==='Enter'){ e.preventDefault(); send(); } }}
          ></textarea>
          <div className="right">
            <div className="chips"><span>Attach:</span>
              <button className="chip" type="button" onClick={()=>document.getElementById('file-screenshot')?.click()}>Screenshot</button>
              <button className="chip" type="button" onClick={()=>document.getElementById('file-log')?.click()}>log</button>
            </div>
            <div className="attach-summary" aria-live="polite">{attachSummary}</div>
            <button className="send" type="submit" aria-label="Send" disabled={busy}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M22 2L11 13"></path><path d="M22 2l-7 20-4-9-9-4 20-7z"></path></svg>
              {busy ? 'SENDING…' : 'SEND'}
            </button>
          </div>
          <input type="file" id="file-screenshot" accept="image/*" hidden onChange={(e)=>{ const fs = (e.target as HTMLInputElement).files; if(fs && fs.length) setAttachments(prev=>[...prev, ...Array.from(fs).map(f=>({name:f.name,type:f.type,size:f.size}))]); }} />
          <input type="file" id="file-log" accept=".txt,.log,.zip,.gz,.tar,.json" hidden onChange={(e)=>{ const fs = (e.target as HTMLInputElement).files; if(fs && fs.length) setAttachments(prev=>[...prev, ...Array.from(fs).map(f=>({name:f.name,type:f.type,size:f.size}))]); }} />
        </form>
        <p style={{marginTop:14, color:'var(--muted)'}}>Tip: Press <span className="kbd">Ctrl</span> + <span className="kbd">Enter</span> to send.</p>
      </section>
    </div>
  );
}
