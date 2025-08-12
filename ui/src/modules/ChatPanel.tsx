import React, { useState } from 'react';
import { MessageList } from './MessageList';
import { ToolCallPreview } from './ToolCallPreview';

export const ChatPanel: React.FC = () => {
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<any[]>([]);
  const [pendingTool, setPendingTool] = useState<any|null>(null);

  function send() {
    if(!input.trim()) return;
    setMessages(m=>[...m,{role:'user', content: input}]);
    // TODO: call backend proxy to LM Studio + MCP workflow
    setInput('');
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
          <button onClick={send} className="px-4 py-2 rounded bg-brand-600 hover:bg-brand-500 text-sm font-medium">Send</button>
        </div>
      </div>
    </div>
  );
};
