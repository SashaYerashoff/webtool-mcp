import React, { useEffect, useState } from 'react';
import { fetchModels } from './services/api';

interface SidebarProps {
  onToggleTheme(): void;
  onNewChat(): void;
  model: string | null;
  setModel(m: string): void;
  systemPrompt: string;
  setSystemPrompt(v: string): void;
}

export const Sidebar: React.FC<SidebarProps> = ({ onToggleTheme, onNewChat, model, setModel, systemPrompt, setSystemPrompt }) => {
  const [models, setModels] = useState<string[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);
  useEffect(()=>{
    (async()=>{
      setLoadingModels(true);
      try {
        const data = await fetchModels();
        setModels(data.models || []);
      } finally {
        setLoadingModels(false);
      }
    })();
  },[]);
  return (
    <aside className="w-80 border-r border-neutral-800 flex flex-col">
      <div className="p-4 space-y-6 overflow-auto">
        <div>
          <div className="flex items-center justify-between">
            <h2 className="text-[11px] uppercase font-medium tracking-wider text-neutral-400">Session</h2>
            <button onClick={onNewChat} className="text-[11px] px-2 py-1 rounded bg-neutral-800 hover:bg-neutral-700">New</button>
          </div>
        </div>
        <div>
          <h2 className="text-[11px] uppercase font-medium tracking-wider text-neutral-400 mb-2">Model</h2>
          <select value={model || ''} onChange={e=>setModel(e.target.value)} className="mt-1 w-full bg-neutral-900 border border-neutral-700 rounded px-2 py-1 text-sm focus:outline-none focus:border-brand-500">
            {loadingModels && <option>loading...</option>}
            {!loadingModels && models.length === 0 && <option value="">auto</option>}
            {models.map(m=> <option key={m} value={m}>{m}</option>)}
          </select>
        </div>
        <div>
          <h2 className="text-[11px] uppercase font-medium tracking-wider text-neutral-400 mb-2">System Prompt (first message)</h2>
          <textarea value={systemPrompt} onChange={e=>setSystemPrompt(e.target.value)} placeholder="Optional system prompt to send once at start" className="w-full h-40 resize-none rounded bg-neutral-900 border border-neutral-700 px-2 py-1 text-xs leading-snug focus:outline-none focus:border-brand-500"></textarea>
        </div>
        <div>
          <h2 className="text-[11px] uppercase font-medium tracking-wider text-neutral-400 mb-2">Theme</h2>
          <button onClick={onToggleTheme} className="mt-1 w-full text-left px-3 py-2 rounded bg-neutral-800 hover:bg-neutral-700 text-sm">Toggle Theme</button>
        </div>
      </div>
      <div className="mt-auto p-4 text-[11px] text-neutral-500 space-y-1">
        <p>webtool-mcp UI</p>
        <p className="text-neutral-600">alpha</p>
      </div>
    </aside>
  );
};
