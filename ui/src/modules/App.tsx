import React, { useState } from 'react';
import { ChatPanel } from './ChatPanel';
import { Sidebar } from './Sidebar';
import { H1 } from './ui';

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
  <div className="flex h-screen w-full bg-paper-50 text-ink-900 dark:bg-ink-900 dark:text-paper-100 transition-colors">
        <Sidebar
          onToggleTheme={() => setDark(d=>!d)}
          onNewChat={handleNewChat}
          model={model}
          setModel={m=>setModel(m)}
          systemPrompt={systemPrompt}
          setSystemPrompt={setSystemPrompt}
        />
        <div className="flex-1 flex flex-col">
          <header className="px-8 py-4 border-b border-paper-200 dark:border-ink-700 flex items-center justify-between bg-paper-100/80 dark:bg-ink-800/60 backdrop-blur supports-[backdrop-filter]:bg-paper-100/60">
            <H1 className="!text-[2.2rem]">Webtool</H1>
            <button onClick={()=>setDark(d=>!d)} className="text-sm px-3 py-1.5 rounded bg-ink-900 text-paper-100 hover:bg-ink-800 dark:bg-ink-700 dark:hover:bg-ink-600">{dark? 'Light':'Dark'}</button>
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
