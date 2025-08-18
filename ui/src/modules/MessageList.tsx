import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Bubble, Collapsible } from './ui';
import { maybeFixUtf8Mojibake, stripToolJsonBlocks, splitControlPreamble } from './encoding';

interface Props { messages: any[]; onFollowLink?(id: string): void; onFetchSection?(id: string): void; markdown?: boolean; }

export const MessageList: React.FC<Props> = ({ messages, onFollowLink, onFetchSection, markdown = false }) => {
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
          const pre = preamble ? (
            <div className="text-xs text-ink-600/70 dark:text-paper-400/70 font-mono whitespace-pre-wrap break-words mb-1">{preamble}</div>
          ) : null;
          if (markdown) {
            return (
              <div key={i} className="mx-auto w-full max-w-[900px] text-[16px] leading-7">
                {pre}
                <ReactMarkdown
                  skipHtml
                  remarkPlugins={[remarkGfm]}
                  className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]"
                >
                  {content}
                </ReactMarkdown>
              </div>
            );
          }
          // Raw with clickable [L#]/[sec-#]
          return (
            <div key={i} className="mx-auto w-full max-w-[900px] text-[16px] leading-7">
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
