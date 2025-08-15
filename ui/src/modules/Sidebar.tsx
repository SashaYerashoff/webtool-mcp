import React, { useEffect, useState } from 'react';
import { fetchModels } from './services/api';
import { Button, Card, H2, Select, Textarea } from './ui';

interface SidebarProps {
  collapsed?: boolean;
  onToggleTheme(): void;
  onNewChat(): void;
  model: string | null;
  setModel(m: string): void;
  systemPrompt: string;
  setSystemPrompt(v: string): void;
}

export const Sidebar: React.FC<SidebarProps> = ({ collapsed = false, onToggleTheme, onNewChat, model, setModel, systemPrompt, setSystemPrompt }) => {
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
    <aside className={(collapsed ? 'w-0 sm:w-12 ' : 'w-80 ') + 'transition-all duration-200 border-r border-paper-200 dark:border-ink-700 flex flex-col bg-paper-100/70 dark:bg-ink-800/40 overflow-hidden'}>
      <div className={(collapsed ? 'hidden sm:block ' : '') + 'p-5 space-y-6 overflow-auto'}>
        <div>
          <div className="flex items-center justify-between">
            <H2 className="!text-[0.95rem]">Session</H2>
            <Button onClick={onNewChat} className="!px-3 !py-1.5 !text-[12px]">New</Button>
          </div>
        </div>
        <div>
          <H2 className="!text-[0.95rem] mb-2">Model</H2>
      <Select value={model || ''} onChange={e=>setModel((e.target as HTMLSelectElement).value)}>
            {loadingModels && <option>loading...</option>}
            {!loadingModels && models.length === 0 && <option value="">auto</option>}
            {models.map(m=> <option key={m} value={m}>{m}</option>)}
          </Select>
        </div>
        <div>
          <H2 className="!text-[0.95rem] mb-2">System Prompt (first message)</H2>
      <Textarea value={systemPrompt} onChange={e=>setSystemPrompt(e.target.value)} placeholder="Optional system prompt to send once at start" className="h-40 text-[13px]" />
        </div>
        <div>
          <H2 className="!text-[0.95rem] mb-2">Theme</H2>
      <Button onClick={onToggleTheme} className="mt-1 w-full text-left !text-[14px]">Toggle Theme</Button>
        </div>
      </div>
      <div className={(collapsed ? 'hidden sm:block ' : '') + 'mt-auto p-5 text-[12px] text-ink-600 dark:text-paper-400 space-y-1'}>
        <p>webtool-mcp UI</p>
        <p className="text-neutral-600">alpha</p>
      </div>
    </aside>
  );
};
