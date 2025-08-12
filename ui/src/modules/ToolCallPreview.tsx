import React from 'react';

export const ToolCallPreview: React.FC<{tool: any}> = ({ tool }) => {
  return (
    <div className="rounded border border-neutral-700 bg-neutral-900 p-3 text-xs font-mono">
      <div className="text-neutral-400 mb-1">Pending tool call</div>
      <pre className="whitespace-pre-wrap">{JSON.stringify(tool, null, 2)}</pre>
    </div>
  );
};
