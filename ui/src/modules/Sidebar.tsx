import React from 'react';

interface SidebarProps { onToggleTheme(): void }

export const Sidebar: React.FC<SidebarProps> = ({ onToggleTheme }) => {
  return (
    <aside className="w-72 border-r border-neutral-800 flex flex-col">
      <div className="p-4 space-y-4">
        <div>
          <h2 className="text-xs uppercase font-medium tracking-wider text-neutral-400">Session</h2>
          <button className="mt-2 w-full text-left px-3 py-2 rounded bg-neutral-800 hover:bg-neutral-700 text-sm">New Chat</button>
        </div>
        <div>
          <h2 className="text-xs uppercase font-medium tracking-wider text-neutral-400">Model</h2>
          <select className="mt-2 w-full bg-neutral-900 border border-neutral-700 rounded px-2 py-1 text-sm focus:outline-none focus:border-brand-500">
            <option>auto (LM Studio)</option>
          </select>
        </div>
        <div>
          <h2 className="text-xs uppercase font-medium tracking-wider text-neutral-400">Theme</h2>
          <button onClick={onToggleTheme} className="mt-2 w-full text-left px-3 py-2 rounded bg-neutral-800 hover:bg-neutral-700 text-sm">Toggle Theme</button>
        </div>
      </div>
      <div className="mt-auto p-4 text-xs text-neutral-500">
        <p>webtool-mcp UI preview</p>
      </div>
    </aside>
  );
};
