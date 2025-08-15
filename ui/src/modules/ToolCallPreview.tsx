import React from 'react';

export const ToolCallPreview: React.FC<{tool: any}> = ({ tool }) => {
  return (
    <div className="rounded border border-paper-200 dark:border-ink-700 bg-paper-50 dark:bg-ink-900 p-3 text-xs font-mono text-ink-900 dark:text-paper-100">
      <div className="text-ink-600 dark:text-paper-300 mb-1">Pending tool call</div>
      <pre className="whitespace-pre-wrap">{JSON.stringify(tool, null, 2)}</pre>
    </div>
  );
};
