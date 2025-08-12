import React, { useState } from 'react';
import { ChatPanel } from './ChatPanel';
import { Sidebar } from './Sidebar';

export default function App() {
  const [dark, setDark] = useState(true);
  return (
    <div className={dark ? 'dark' : ''}>
      <div className="flex h-screen w-full dark:bg-neutral-950 dark:text-neutral-100 bg-white text-neutral-900 transition-colors">
        <Sidebar onToggleTheme={() => setDark(d=>!d)} />
        <div className="flex-1 flex flex-col">
          <header className="px-4 py-2 border-b border-neutral-800 flex items-center justify-between">
            <h1 className="text-lg font-semibold tracking-wide">webtool UI</h1>
            <button onClick={()=>setDark(d=>!d)} className="text-sm px-3 py-1 rounded bg-neutral-800 hover:bg-neutral-700">{dark? 'Light':'Dark'}</button>
          </header>
          <ChatPanel />
        </div>
      </div>
    </div>
  );
}
