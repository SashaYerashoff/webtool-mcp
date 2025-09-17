import React from 'react';
import { createRoot } from 'react-dom/client';

function ClientApp() {
  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <div className="max-w-xl w-full space-y-4">
        <h1 className="text-2xl font-semibold">Evo Agent Client</h1>
        <p className="text-slate-600">
          Minimal client for chatting with the agent. This build is separate from the Trainer UI.
        </p>
        <div className="space-y-2">
          <label className="block text-sm font-medium">Your message</label>
          <textarea className="w-full border rounded-md p-2" rows={4} placeholder="Ask the agent..." />
          <button className="px-4 py-2 rounded-md bg-slate-900 text-white">Send</button>
        </div>
      </div>
    </div>
  );
}

createRoot(document.getElementById('root')!).render(<ClientApp />);
