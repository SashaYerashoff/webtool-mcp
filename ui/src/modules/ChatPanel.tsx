import React, { useState } from 'react';
import { MessageList } from './MessageList';
import { ToolCallPreview } from './ToolCallPreview';
import { sendChat, streamChat, type ChatStreamEvent, callTool, fetchUrlStructured, createAnnotation } from './services/api';
import { maybeFixUtf8Mojibake, stripToolJsonBlocks } from './encoding';
import { Button, Textarea } from './ui';

interface Props {
  sessionId: string | null;
  setSessionId(id: string): void;
  model?: string;
  systemPrompt?: string;
  messages: any[];
  setMessages(m: any[]): void;
  setStreamingRef?(es: EventSource|null): void;
  markdown?: boolean;
}

export const ChatPanel: React.FC<Props> = ({ sessionId, setSessionId, model, systemPrompt, messages, setMessages, setStreamingRef, markdown = false }) => {
  const [input, setInput] = useState('');
  const [pendingTool, setPendingTool] = useState<any|null>(null);
  const [sending, setSending] = useState(false);
  const [streaming, setStreaming] = useState<EventSource|null>(null);
  const [thumbs, setThumbs] = useState<Array<{src: string; alt: string}>>([]);
  const [thumbsLoading, setThumbsLoading] = useState(false);
  const [lastThumbsUrl, setLastThumbsUrl] = useState<string | null>(null);
  const scrollRef = React.useRef<HTMLDivElement | null>(null);
  const [lastPairId, setLastPairId] = useState<string|null>(null);
  const [pendingAnno, setPendingAnno] = useState<{ text: string; start: number; end: number }|null>(null);
  const [annoSentiment, setAnnoSentiment] = useState<'positive'|'negative'|''>('');
  const [annoTags, setAnnoTags] = useState<string>('');
  const quickTags = ['precise','creative','lie','boring','stop hallucinate'];
  const [annoNote, setAnnoNote] = useState<string>('');
  const [annoRating, setAnnoRating] = useState<string>('');

  const currentBaseUrl = React.useMemo(()=> extractSourceUrl(messages), [messages]);

  // If the base URL changes due to navigation, clear any prior thumbnails
  React.useEffect(()=>{
    if(lastThumbsUrl && currentBaseUrl && lastThumbsUrl !== currentBaseUrl){
      setThumbs([]);
      setLastThumbsUrl(null);
    }
  }, [currentBaseUrl]);

  async function send() {
  if(!input.trim() || sending || pendingTool) return;
  // Ensure no stray stream is open
  if (streaming) { try { streaming.close(); } catch {} setStreaming(null); }
  // Clear any previous thumbnail preview on new user message
  setThumbs([]);
  setLastThumbsUrl(null);
    const userMsg = input;
    setInput('');
    const base = [...messages, {role:'user', content:userMsg}];
    setMessages(base);
    setSending(true);
    // Streamed path
    let working = [...base];
    let assistantIdx: number | null = null;
    let reasoningIdx: number | null = null;
    let toolIdx: number | null = null;
  let sawTool = false;
  const es = streamChat({ session_id: sessionId || undefined, user: userMsg, model, system_prompt: systemPrompt }, (ev: ChatStreamEvent)=>{
      if(ev.type === 'session'){
        if(ev.session_id) setSessionId(ev.session_id);
        return;
      }
      if(ev.type === 'assistant_token'){
        if(reasoningIdx === null){ /* ensure reasoning shown before assistant only if arrives first */ }
  const t = stripToolJsonBlocks(maybeFixUtf8Mojibake(ev.text));
        if(assistantIdx === null){ assistantIdx = working.push({role:'assistant', content: t}) - 1; }
        else { working[assistantIdx].content += t; }
        setMessages([...working]);
        return;
      }
      if(ev.type === 'reasoning_token'){
        if(reasoningIdx === null){ reasoningIdx = working.push({role:'reasoning', content: ev.text}) - 1; }
        else { working[reasoningIdx].content += ev.text; }
        setMessages([...working]);
        return;
      }
      if(ev.type === 'assistant_done'){
        // no-op, next phases may follow
        return;
      }
      if(ev.type === 'tool_start'){
        setPendingTool(ev);
        return;
      }
      if(ev.type === 'tool'){
        setPendingTool(null);
        const content = ev.error ? `Error: ${ev.error}` : (ev.content || '');
        if(toolIdx === null){ toolIdx = working.push({role:'tool', content}) - 1; }
        else { working[toolIdx].content = content; }
  sawTool = true;
        setMessages([...working]);
        return;
      }
      if(ev.type === 'assistant_final_token'){
  const t = stripToolJsonBlocks(maybeFixUtf8Mojibake(ev.text));
        if(assistantIdx === null){ assistantIdx = working.push({role:'assistant', content: t}) - 1; }
        else { working[assistantIdx].content += t; }
        setMessages([...working]);
        return;
      }
  if(ev.type === 'done'){
        // Ensure final messages are present
        // tool_output is omitted in multi-pass mode; rely on 'tool' events only
        if(ev.assistant_reasoning){
          if(reasoningIdx === null) reasoningIdx = working.push({role:'reasoning', content: ev.assistant_reasoning}) - 1;
          else working[reasoningIdx].content = ev.assistant_reasoning;
        }
  const finalText = stripToolJsonBlocks(maybeFixUtf8Mojibake(ev.assistant));
        if(assistantIdx === null) {
          if(finalText && finalText.trim()) {
            assistantIdx = working.push({role:'assistant', content: finalText}) - 1;
          }
        }
  setMessages([...working]);
        setSending(false);
  setPendingTool(null);
        setStreaming(null);
  setStreamingRef?.(null);
  if(ev.pair_id) setLastPairId(ev.pair_id);
        es.close();
        return;
      }
      if(ev.type === 'error'){
        working.push({role:'assistant', content: `Error: ${ev.message}`});
        setMessages([...working]);
        setSending(false);
        setStreaming(null);
  setStreamingRef?.(null);
        es.close();
      }
    });
    setStreaming(es);
    setStreamingRef?.(es);
  }

  async function followLink(linkId: string){
    const baseUrl = extractSourceUrl(messages);
    if(!baseUrl) return;
    setPendingTool({ name: 'fetch_url', arguments: { url: baseUrl, link_id: linkId } });
    try{
      const res = await callTool('fetch_url', { url: baseUrl, link_id: linkId });
      const content = res.content || '';
      setMessages([...messages, { role:'tool', content }]);
    } finally {
      setPendingTool(null);
    }
  }

  async function fetchSection(secId: string){
    const baseUrl = extractSourceUrl(messages);
    if(!baseUrl) return;
    setPendingTool({ name: 'fetch_url', arguments: { url: baseUrl, chunk_id: secId } });
    try{
      const res = await callTool('fetch_url', { url: baseUrl, chunk_id: secId });
      const content = res.content || '';
      setMessages([...messages, { role:'tool', content }]);
    } finally {
      setPendingTool(null);
    }
  }

  function extractSourceUrl(msgs: any[]): string | null {
    // Try to find the most recent META source: line in a tool output
    for(let i = msgs.length - 1; i >= 0; i--){
      const m = msgs[i];
      if(m.role === 'tool' && typeof m.content === 'string'){
        const mt = m.content.match(/source:\s*(\S+)/);
        if(mt) return mt[1];
      }
    }
    return null;
  }

  async function previewImages(){
    const baseUrl = currentBaseUrl;
    if(!baseUrl || thumbsLoading) return;
    // Toggle: if thumbs already shown for this URL, collapse
    if(thumbs.length > 0 && lastThumbsUrl === baseUrl){
      setThumbs([]);
      setLastThumbsUrl(null);
      return;
    }
    setPendingTool({ name: 'fetch_url', arguments: { url: baseUrl, mode: 'images' } });
    setThumbsLoading(true);
    setThumbs([]);
    try{
      const text = await fetchUrlStructured(baseUrl, 'images');
      // Parse THUMBS section: lines after 'THUMBS' until next section
      const lines = text.split('\n');
      const out: Array<{src: string; alt: string}> = [];
      let inThumbs = false;
      for(const line of lines){
        if(line.trim() === 'THUMBS'){ inThumbs = true; continue; }
        if(inThumbs){
          if(!line.trim()){ continue; }
          if(/^[A-Z]{3,}/.test(line.trim()) && !line.trim().startsWith('![')){
            // next section started
            break;
          }
          const m = line.match(/!\[([^\]]*)\]\(([^\)]+)\)/);
          if(m){ out.push({ alt: m[1] || '', src: m[2] }); if(out.length>=2) break; }
        }
      }
  setThumbs(out);
  setLastThumbsUrl(baseUrl);
    } catch(e){
      setThumbs([]);
  setLastThumbsUrl(null);
    } finally {
      setPendingTool(null);
      setThumbsLoading(false);
    }
  }

  return (
    <div className="flex-1 flex flex-col min-h-0">
  <div ref={scrollRef} className="flex-1 overflow-auto">
  <MessageList messages={messages} onFollowLink={followLink} onFetchSection={fetchSection} markdown={markdown && !streaming} onAnnotate={(sel)=>{
        // Only allow annotating assistant text we just generated; we attach to lastPairId when available
        if(sel.text && sel.text.length >= 2){ setPendingAnno({ text: sel.text, start: Math.max(0, sel.offsetStart||0), end: Math.max(0, sel.offsetEnd||0) }); }
      }} />
      </div>
  <div className="border-t border-paper-200 dark:border-ink-700 p-4 flex flex-col gap-3 bg-paper-100/70 dark:bg-ink-800/40">
        {pendingTool && <ToolCallPreview tool={pendingTool} />}
        {pendingAnno && (
          <div className="p-3 rounded border border-paper-200 dark:border-ink-700 bg-paper-50 dark:bg-ink-900">
            <div className="text-[13px] mb-2">Annotate selection</div>
            <div className="text-[12px] p-2 rounded bg-paper-100 dark:bg-ink-800 mb-2 whitespace-pre-wrap break-words">{pendingAnno.text.slice(0,500)}</div>
            <div className="flex flex-wrap items-center gap-3 mb-2 text-[12px]">
              <label className="flex items-center gap-1">Sentiment:
                <select value={annoSentiment} onChange={e=>setAnnoSentiment((e.target as HTMLSelectElement).value as any)} className="border border-paper-200 dark:border-ink-700 rounded px-1 py-0.5">
                  <option value="">neutral</option>
                  <option value="positive">positive</option>
                  <option value="negative">negative</option>
                </select>
              </label>
              <label className="flex items-center gap-1">Tags:
                <input value={annoTags} onChange={e=>setAnnoTags((e.target as HTMLInputElement).value)} placeholder="precise, creative, lie, boring, stop hallucinate" className="border border-paper-200 dark:border-ink-700 rounded px-2 py-0.5 min-w-[240px]" />
              </label>
              <label className="flex items-center gap-1">Rating:
                <input type="number" min={1} max={5} value={annoRating} onChange={e=>setAnnoRating((e.target as HTMLInputElement).value)} className="w-16 border border-paper-200 dark:border-ink-700 rounded px-2 py-0.5" />
              </label>
            </div>
            <div className="flex flex-wrap gap-2 mb-2">
              {quickTags.map(t=> (
                <button key={t} className="text-[11px] px-2 py-0.5 rounded border border-paper-200 dark:border-ink-700 hover:bg-paper-100 dark:hover:bg-ink-800" onClick={()=>{
                  const tags = new Set(annoTags.split(',').map(s=>s.trim()).filter(Boolean));
                  tags.add(t);
                  setAnnoTags(Array.from(tags).join(', '));
                }}>{t}</button>
              ))}
            </div>
            <textarea value={annoNote} onChange={e=>setAnnoNote((e.target as HTMLTextAreaElement).value)} placeholder="Add a brief note (issue/solution context)" className="w-full h-16 border border-paper-200 dark:border-ink-700 rounded px-2 py-1 text-[12px] bg-paper-50 dark:bg-ink-900" />
            <div className="mt-2 flex gap-2">
              <Button variant="primary" onClick={async()=>{
                if(!lastPairId){ setPendingAnno(null); return; }
                try{
                  const tags = annoTags.split(',').map(s=>s.trim()).filter(Boolean);
                  await createAnnotation(lastPairId, {
                    target: 'model_response',
                    start: pendingAnno.start >= 0 ? pendingAnno.start : undefined,
                    end: pendingAnno.end >= 0 ? pendingAnno.end : undefined,
                    text: pendingAnno.text,
                    sentiment: annoSentiment,
                    tags,
                    note: annoNote,
                    rating: annoRating ? Number(annoRating) : undefined,
                  });
                }finally{
                  setPendingAnno(null);
                  setAnnoSentiment(''); setAnnoTags(''); setAnnoNote(''); setAnnoRating('');
                }
              }}>Save annotation</Button>
              <Button variant="outline" onClick={()=>{ setPendingAnno(null); }}>Cancel</Button>
            </div>
          </div>
        )}
        {/* Show detected base URL if available */}
        {currentBaseUrl && (
          <div className="flex items-center gap-3">
            <div className="text-xs text-ink-600 dark:text-paper-400">Base URL: {currentBaseUrl}</div>
            <Button
              variant="outline"
              className="px-2 py-1 text-xs"
              disabled={thumbsLoading}
              onClick={previewImages}
            >
              {thumbsLoading ? 'Fetching images…' : (thumbs.length > 0 && lastThumbsUrl === currentBaseUrl ? 'Hide images' : 'Preview images')}
            </Button>
          </div>
        )}
        {!!thumbs.length && (
          <div className="flex gap-3 items-center flex-wrap">
            {thumbs.map((t, i)=> (
              <a key={i} href={t.src} target="_blank" rel="noreferrer" className="block">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={t.src} alt={t.alt || ''} className="h-20 w-auto rounded border border-paper-200 dark:border-ink-700 bg-paper-50 dark:bg-ink-900" />
              </a>
            ))}
          </div>
        )}
        <div className="flex gap-2">
          <Textarea
            value={input}
            onChange={e=>setInput(e.target.value)}
            placeholder="Ask or instruct..."
            disabled={sending}
            className="flex-1 h-24"
          />
      <Button disabled={sending} onClick={send} className="px-5 py-3 !text-[15px]">{sending? 'Streaming…':'Send'}</Button>
        </div>
      </div>
    </div>
  );
};
