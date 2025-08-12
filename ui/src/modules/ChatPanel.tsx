import React, { useState } from 'react';
import { MessageList } from './MessageList';
import { ToolCallPreview } from './ToolCallPreview';
import { sendChat } from './services/api';

interface Props {
  sessionId: string | null;
  setSessionId(id: string): void;
  model?: string;
  systemPrompt?: string;
  messages: any[];
  setMessages(m: any[]): void;
}

export const ChatPanel: React.FC<Props> = ({ sessionId, setSessionId, model, systemPrompt, messages, setMessages }) => {
  const [input, setInput] = useState('');
  const [pendingTool, setPendingTool] = useState<any|null>(null);
  const [sending, setSending] = useState(false);

  async function send() {
    if(!input.trim() || sending) return;
    const userMsg = input;
    setInput('');
    setMessages([...messages, {role:'user', content:userMsg}]);
    setSending(true);
    try {
      const resp = await sendChat({ session_id: sessionId || undefined, user: userMsg, model, system_prompt: systemPrompt });
      setSessionId(resp.session_id);
      const newMessages = [...messages, {role:'user', content:userMsg}, {role:'assistant', content: resp.assistant}];
      if(resp.tool_output){
        newMessages.push({role:'tool', content: resp.tool_output});
      }
      setMessages(newMessages);
    } catch(e:any){
      setMessages([...messages, {role:'user', content:userMsg}, {role:'assistant', content: `Error: ${e.message}` }]);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="flex-1 flex flex-col">
      <div className="flex-1 overflow-auto">
        <MessageList messages={messages} />
      </div>
      <div className="border-t border-neutral-800 p-3 flex flex-col gap-2">
        {pendingTool && <ToolCallPreview tool={pendingTool} />}
        <div className="flex gap-2">
          <textarea
            value={input}
            onChange={e=>setInput(e.target.value)}
            placeholder="Ask or instruct..."
            className="flex-1 resize-none rounded bg-neutral-900 border border-neutral-700 px-3 py-2 text-sm focus:outline-none focus:border-brand-500 h-20"
          />
          <button disabled={sending} onClick={send} className="px-4 py-2 rounded bg-brand-600 hover:bg-brand-500 disabled:opacity-40 text-sm font-medium">{sending? '...':'Send'}</button>
        </div>
      </div>
    </div>
  );
};
