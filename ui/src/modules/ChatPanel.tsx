import React, { useState } from 'react';
import { MessageList } from './MessageList';
import { ToolCallPreview } from './ToolCallPreview';
import { sendChat, streamChat, type ChatStreamEvent, callTool } from './services/api';
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
  const scrollRef = React.useRef<HTMLDivElement | null>(null);

  async function send() {
  if(!input.trim() || sending || pendingTool) return;
  // Ensure no stray stream is open
  if (streaming) { try { streaming.close(); } catch {} setStreaming(null); }
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

  return (
    <div className="flex-1 flex flex-col min-h-0">
  <div ref={scrollRef} className="flex-1 overflow-auto">
  <MessageList messages={messages} onFollowLink={followLink} onFetchSection={fetchSection} markdown={markdown && !streaming} />
      </div>
  <div className="border-t border-paper-200 dark:border-ink-700 p-4 flex flex-col gap-3 bg-paper-100/70 dark:bg-ink-800/40">
        {pendingTool && <ToolCallPreview tool={pendingTool} />}
        {/* Show detected base URL if available */}
        {extractSourceUrl(messages) && (
          <div className="text-xs text-ink-600 dark:text-paper-400">Base URL: {extractSourceUrl(messages)}</div>
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
