import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Bubble, Collapsible } from './ui';
import { maybeFixUtf8Mojibake } from './encoding';

export const MessageList: React.FC<{messages: any[]}> = ({ messages }) => {
  const bottomRef = React.useRef<HTMLDivElement | null>(null);
  React.useEffect(()=>{
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages]);
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
          const content = maybeFixUtf8Mojibake(m.content || '');
          return (
            <div key={i} className="mx-auto w-full max-w-[900px] text-[16px] leading-7">
              <ReactMarkdown
                skipHtml
                remarkPlugins={[remarkGfm]}
                className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]"
              >
                {content}
              </ReactMarkdown>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  );
};
