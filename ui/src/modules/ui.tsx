import React from 'react';

function cx(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(' ');
}

// Typography helpers to match the mock
export const H1: React.FC<{className?: string; children: React.ReactNode}> = ({ className, children }) => (
  <h1 className={cx('font-news text-[2.75rem] leading-tight font-black tracking-tight', className)}>{children}</h1>
);
export const H2: React.FC<{className?: string; children: React.ReactNode}> = ({ className, children }) => (
  <h2 className={cx('font-news text-[1.9rem] leading-snug font-bold uppercase tracking-wide', className)}>{children}</h2>
);
export const H3: React.FC<{className?: string; children: React.ReactNode}> = ({ className, children }) => (
  <h3 className={cx('font-news text-[1.35rem] italic font-semibold', className)}>{children}</h3>
);

type ButtonVariant = 'primary' | 'ghost' | 'outline';
export const Button: React.FC<React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }>
  = ({ className, variant = 'primary', ...props }) => {
  const base = 'inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2 text-[15px] font-semibold transition-colors shadow-sm focus:outline-none focus:ring-2 focus:ring-offset-0';
  const variants: Record<ButtonVariant, string> = {
    primary: 'bg-ink-900 text-paper-100 hover:bg-ink-800 dark:bg-ink-700 dark:hover:bg-ink-600 focus:ring-rust-400 dark:focus:ring-rust-300 disabled:opacity-40',
    ghost: 'bg-transparent text-ink-900 hover:bg-paper-200/60 dark:text-paper-100 dark:hover:bg-ink-800 disabled:opacity-40',
    outline: 'border border-paper-200 text-ink-900 bg-paper-50 hover:bg-paper-100 dark:border-ink-700 dark:text-paper-100 dark:bg-ink-900 dark:hover:bg-ink-800 disabled:opacity-40',
  };
  return <button className={cx(base, variants[variant], className)} {...props} />;
};

export const Input: React.FC<React.InputHTMLAttributes<HTMLInputElement>> = ({ className, ...props }) => (
  <input className={cx('w-full rounded-lg bg-paper-50 border border-paper-200 text-ink-900 dark:bg-ink-900 dark:border-ink-700 dark:text-paper-100 px-3 py-2 text-[14px] focus:outline-none focus:border-rust-400 dark:focus:border-rust-300 placeholder:opacity-60', className)} {...props} />
);

export const Textarea: React.FC<React.TextareaHTMLAttributes<HTMLTextAreaElement>> = ({ className, ...props }) => (
  <textarea className={cx('w-full rounded-lg bg-paper-50 border border-paper-200 text-ink-900 dark:bg-ink-900 dark:border-ink-700 dark:text-paper-100 px-3 py-2 text-[16px] leading-relaxed focus:outline-none focus:border-rust-400 dark:focus:border-rust-300 placeholder:opacity-60', className)} {...props} />
);

export const Select: React.FC<React.SelectHTMLAttributes<HTMLSelectElement>> = ({ className, children, ...props }) => (
  <select className={cx('w-full rounded-lg bg-paper-50 border border-paper-200 text-ink-900 dark:bg-ink-900 dark:border-ink-700 dark:text-paper-100 px-2.5 py-2 text-[14px] focus:outline-none focus:border-rust-400 dark:focus:border-rust-300', className)} {...props}>{children}</select>
);

export const Card: React.FC<{ className?: string; children: React.ReactNode }>
  = ({ className, children }) => (
  <div className={cx('rounded-xl border border-paper-200 bg-paper-100 text-ink-900 dark:border-ink-700 dark:bg-ink-900 dark:text-paper-100 shadow-sm', className)}>{children}</div>
);

export const Bubble: React.FC<{ role: 'user' | 'assistant' | 'tool' | 'system' | 'reasoning'; className?: string; children: React.ReactNode }>
  = ({ role, className, children }) => {
  const base = 'max-w-[80%] rounded-2xl px-5 py-3 text-[16px] whitespace-pre-wrap break-words [overflow-wrap:anywhere] shadow-sm';
  let scheme = '';
  if (role === 'user') scheme = 'bg-rust-600 text-paper-50';
  else if (role === 'tool' || role === 'reasoning') scheme = 'bg-paper-50 text-ink-900 border border-paper-200 dark:bg-ink-800 dark:text-paper-100 dark:border-ink-700';
  else scheme = 'bg-paper-100 text-ink-900 border border-paper-200 dark:bg-ink-900 dark:text-paper-100 dark:border-ink-700';
  return <div className={cx(base, scheme, className)}>{children}</div>;
};

export const Collapsible: React.FC<{ title: string; content: string }>
  = ({ title, content }) => {
  const [open, setOpen] = React.useState(false);
  return (
    <div className="border border-paper-200 dark:border-ink-700 rounded">
      <button onClick={()=>setOpen(!open)} className="w-full text-left px-3 py-2 text-xs font-medium bg-paper-200/60 text-ink-900 hover:bg-paper-200 dark:bg-ink-800 dark:text-paper-100 dark:hover:bg-ink-700">
        {open ? '▼' : '▶'} {title}
      </button>
      {open && (
        <div className="p-3 text-xs font-mono whitespace-pre-wrap break-words bg-paper-50 text-ink-900 dark:bg-ink-900 dark:text-paper-100">
          {content}
        </div>
      )}
    </div>
  );
};
