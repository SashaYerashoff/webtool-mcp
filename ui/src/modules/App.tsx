import React, { useState } from 'react';
import { ChatPanel } from './ChatPanel';
import { Sidebar } from './Sidebar';

export default function App() {
  const [dark, setDark] = useState(true);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [model, setModel] = useState<string | null>('');
  const [systemPrompt, setSystemPrompt] = useState<string>('');
  const [messages, setMessages] = useState<any[]>([]);

  function handleNewChat(){
    setSessionId(null);
    setMessages([]);
  }
  return (
    <div className={dark ? 'dark' : ''}>
      <div className="flex h-screen w-full dark:bg-neutral-950 dark:text-neutral-100 bg-white text-neutral-900 transition-colors">
        <Sidebar
          onToggleTheme={() => setDark(d=>!d)}
          onNewChat={handleNewChat}
          model={model}
          setModel={m=>setModel(m)}
          systemPrompt={systemPrompt}
          setSystemPrompt={setSystemPrompt}
        />
        <div className="flex-1 flex flex-col">
          <header className="px-4 py-2 border-b border-neutral-800 flex items-center justify-between">
            <h1 className="text-lg font-semibold tracking-wide">webtool UI</h1>
            <button onClick={()=>setDark(d=>!d)} className="text-sm px-3 py-1 rounded bg-neutral-800 hover:bg-neutral-700">{dark? 'Light':'Dark'}</button>
          </header>
          <ChatPanel
            sessionId={sessionId}
            setSessionId={setSessionId}
            model={model || undefined}
            systemPrompt={systemPrompt}
            messages={messages}
            setMessages={setMessages}
          />
        </div>
      </div>
    </div>
  );
}
