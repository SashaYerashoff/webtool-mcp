import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

// Newspaper/Magazine-styled markdown renderer
// Uses serif headings, generous spacing, justified text, and refined list/blockquote styles.
export const NewspaperMarkdown: React.FC<{ children: string }> = ({ children }) => {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        h1: (props) => (
          <h1 className="font-news text-[2.2rem] leading-tight font-black tracking-tight mt-6 mb-3">
            {props.children}
          </h1>
        ),
        h2: (props) => (
          <h2 className="font-news text-[1.6rem] leading-snug font-bold uppercase tracking-wide mt-8 mb-3">
            {props.children}
          </h2>
        ),
        h3: (props) => (
          <h3 className="font-news text-[1.25rem] italic font-semibold mt-6 mb-2">
            {props.children}
          </h3>
        ),
        h4: (props) => (
          <h4 className="font-news text-[1.1rem] font-semibold mt-5 mb-2 tracking-wide">
            {props.children}
          </h4>
        ),
        p: (props) => (
          <p className="md-p">
            {props.children}
          </p>
        ),
        a: (props) => (
          <a {...props} className="underline decoration-ink-500/40 underline-offset-[3px] hover:decoration-ink-500 hover:text-ink-900 dark:hover:text-paper-100" />
        ),
        ul: (props) => (
          <ul className="md-ul" {...props} />
        ),
        ol: (props) => (
          <ol className="md-ol" {...props} />
        ),
        li: (props) => (
          <li className="md-li" {...props} />
        ),
        blockquote: (props) => (
          <blockquote className="md-quote">
            {props.children}
          </blockquote>
        ),
        code: (props) => {
          const inline = (props as any).inline as boolean | undefined;
          const className = (props as any).className as string | undefined;
          const isInline = inline || !String(className || '').includes('language-');
          if (isInline) {
            return <code className="md-code-inline" {...props} />;
          }
          return (
            <pre className="md-code-pre"><code className="md-code-block" {...props} /></pre>
          );
        },
        hr: () => (<hr className="my-10 border-t border-paper-200 dark:border-ink-700" />),
        table: (props) => (
          <div className="overflow-auto my-6">
            <table className="w-full text-left border-collapse md-table" {...props} />
          </div>
        ),
        th: (props) => (
          <th className="border-b border-paper-300 dark:border-ink-700 py-2 pr-4 font-semibold" {...props} />
        ),
        td: (props) => (
          <td className="border-b border-paper-200 dark:border-ink-800 py-2 pr-4 align-top" {...props} />
        ),
        strong: (props) => <strong className="font-semibold" {...props} />,
        em: (props) => <em className="italic" {...props} />,
        img: (props) => (
          <img className="my-4 rounded shadow-sm max-w-full h-auto" {...props} />
        ),
      }}
      className="md-article"
    >
      {children}
    </ReactMarkdown>
  );
};

export default NewspaperMarkdown;
