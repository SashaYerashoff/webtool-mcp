import React from 'react';
import NewspaperMarkdown from './NewspaperMarkdown';
import { Bubble, Collapsible } from './ui';
import { maybeFixUtf8Mojibake, stripToolJsonBlocks, splitControlPreamble } from './encoding';

interface Props { messages: any[]; onFollowLink?(id: string): void; onFetchSection?(id: string): void; markdown?: boolean; onAnnotate?(sel: { text: string; messageIndex: number; offsetStart: number; offsetEnd: number }): void; }

export const MessageList: React.FC<Props> = ({ messages, onFollowLink, onFetchSection, markdown = false, onAnnotate }) => {
  const bottomRef = React.useRef<HTMLDivElement | null>(null);
  React.useEffect(()=>{
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages]);

  function renderWithActions(text: string){
    // Replace tokens like [L7] and [sec-2] with clickable spans
    const parts: Array<React.ReactNode> = [];
    const regex = /\[(L\d+|sec-\d+)\]/g;
    let lastIndex = 0; let m: RegExpExecArray | null;
    while((m = regex.exec(text))){
      const before = text.slice(lastIndex, m.index);
      if(before) parts.push(before);
      const token = m[1];
      parts.push(
        <button key={m.index}
          className="underline decoration-dotted text-rust-600 dark:text-rust-300 hover:text-rust-500"
          onClick={()=>{
            if(token.startsWith('L')) onFollowLink?.(token);
            else onFetchSection?.(token);
          }}
        >[{token}]</button>
      );
      lastIndex = m.index + m[0].length;
    }
    const rest = text.slice(lastIndex);
    if(rest) parts.push(rest);
    return parts;
  }
  function handleMouseUp(e: React.MouseEvent){
    try{
      const sel = window.getSelection();
      if(!sel || sel.isCollapsed) return;
      const text = String(sel.toString() || '').trim();
      if(!text) return;
      // Find the assistant message container under selection
      const anchorEl = sel.anchorNode?.parentElement as HTMLElement | null;
      if(!anchorEl) return;
      const container = anchorEl.closest('[data-msg-idx]') as HTMLElement | null;
      if(!container) return;
      const idxStr = container.getAttribute('data-msg-idx');
      if(!idxStr) return;
      const idx = parseInt(idxStr,10);
      if(Number.isNaN(idx)) return;
      // Basic offsets within message text (approx by indexOf; for fine-tune later we can carry text only)
      const msgText = (messages[idx]?.content || '') as string;
      const start = msgText.indexOf(text);
      const end = start >= 0 ? start + text.length : -1;
      onAnnotate?.({ text, messageIndex: idx, offsetStart: start, offsetEnd: end });
    }catch{}
  }
  return (
  <div className="py-6 bg-paper-50 dark:bg-ink-900">
      <div className="container-safe content-pad space-y-6">
        {messages.map((m,i)=>{
          const isUser = m.role === 'user';
          const isAssistant = m.role === 'assistant' || m.role === 'system';
          const showCollapsible = m.role === 'tool' || m.role === 'reasoning';
    if (showCollapsible) {
            return (
              <div key={i} className="flex justify-center">
                <Bubble role={m.role}>
      <Collapsible title={m.role === 'tool' ? 'Tool output' : 'Reasoning'} content={maybeFixUtf8Mojibake(m.content || '')} />
                </Bubble>
              </div>
            );
          }
      if (isUser) {
            return (
              <div key={i} className="flex justify-center">
        <Bubble role="user">{maybeFixUtf8Mojibake(m.content || '')}</Bubble>
              </div>
            );
          }
          // Assistant/system: centered text without bubbles
          const cleaned = stripToolJsonBlocks(maybeFixUtf8Mojibake(m.content || ''));
          const { preamble, rest } = splitControlPreamble(cleaned);
          const content = rest;
          const pre = !markdown && preamble ? (
            <div className="text-xs text-ink-600/70 dark:text-paper-400/70 font-mono whitespace-pre-wrap break-words mb-1">{preamble}</div>
          ) : null;
          if (markdown) {
            return (
              <div key={i} className="mx-auto w-full max-w-[900px]" data-msg-idx={i} onMouseUp={handleMouseUp}>
                {pre}
                <NewspaperMarkdown>{content}</NewspaperMarkdown>
              </div>
            );
          }
          // Raw with clickable [L#]/[sec-#]
          return (
            <div key={i} className="mx-auto w-full max-w-[900px] text-[16px] leading-7" data-msg-idx={i} onMouseUp={handleMouseUp}>
              {pre}
              <div className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
                {renderWithActions(content)}
              </div>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  );
};
