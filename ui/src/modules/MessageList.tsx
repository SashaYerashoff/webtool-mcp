import React from 'react';

export const MessageList: React.FC<{messages: any[]}> = ({ messages }) => {
  return (
    <ul className="p-4 space-y-4">
      {messages.map((m,i)=>(
        <li key={i} className="text-sm leading-relaxed">
          <span className="font-semibold mr-2 text-brand-400">{m.role}:</span>
          <span>{m.content}</span>
        </li>
      ))}
    </ul>
  );
};
