import React, { useEffect, useState } from 'react';
import { fetchModels, listPairs, deletePair, searchPairsHybrid, type PairListItem, listPairsWithAnnotations, listAnnotations, deleteAnnotation, exportAnnotationsDataset, getAnnotationsSummary } from './services/api';
import { Button, Card, H2, Select } from './ui';
import { PERSONA_LABELS, type PersonaId } from './presets';

interface SidebarProps {
  collapsed?: boolean;
  onNewChat(): void;
  model: string | null;
  setModel(m: string): void;
  basePrompt: string; // kept for info, not editable here
  persona: PersonaId;
  setPersona(p: PersonaId): void;
  sessionId?: string | null;
  onAttachPair?: (p: PairListItem) => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ collapsed = false, onNewChat, model, setModel, basePrompt, persona, setPersona, sessionId, onAttachPair }) => {
  const [models, setModels] = useState<string[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [pairs, setPairs] = useState<PairListItem[]>([]);
  const [loadingPairs, setLoadingPairs] = useState(false);
  const [q, setQ] = useState('');
  const [onlyAnnotated, setOnlyAnnotated] = useState(false);
  const [annoSentiment, setAnnoSentiment] = useState<''|'positive'|'negative'>('');
  const [openPairAnno, setOpenPairAnno] = useState<string|null>(null);
  const [openPairAnnoItems, setOpenPairAnnoItems] = useState<Record<string, any[]>>({});
  const [since, setSince] = useState<string>('');
  const [until, setUntil] = useState<string>('');
  const [showTime, setShowTime] = useState(false);
  const [summary, setSummary] = useState<null | { total_annotations: number; total_pairs: number; by_sentiment: any; top_tags: Array<{tag:string;count:number}> }>(null);
  const debRef = React.useRef<number | undefined>(undefined);
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
  async function refreshPairs(){
    setLoadingPairs(true);
    try{
      let items: PairListItem[];
      if(onlyAnnotated){
        const rows = await listPairsWithAnnotations({ sentiment: annoSentiment || undefined, limit: 10 });
        items = rows;
      } else {
        items = await listPairs({ limit: 10 });
      }
      setPairs(items);
    } finally {
      setLoadingPairs(false);
    }
  }
  useEffect(()=>{ refreshPairs(); },[]);
  useEffect(()=>{ refreshPairs(); }, [onlyAnnotated, annoSentiment]);

  const AGENT_LABEL: Record<string,string> = { researcher: 'Deep Researcher', news: 'News Crawler', support: 'Support Agent', unknown: 'Agent' };

  function deriveTitle(p: PairListItem): string {
    // Prefer first markdown heading from model_response
    const mr = p.model_response || '';
    const heading = mr.split(/\n/).find(line => /^#{1,3}\s+/.test(line));
    if (heading) return heading.replace(/^#{1,3}\s+/, '').trim().slice(0, 120);
    // If topic exists, use it
    if (p.topic && p.topic.trim()) return p.topic.trim().slice(0, 120);
    // Try to extract quoted phrase from user_request
    const ur = p.user_request || '';
    const m = ur.match(/"([^"]{3,120})"/);
    if (m) return m[1].trim();
    // Fallback to first sentence fragment
    const frag = (ur || '').replace(/^\s*hi\b[^,.!?]*/i, '').trim();
    return (frag || ur || '(untitled)').slice(0, 120);
  }
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
          <H2 className="!text-[0.95rem] mb-2">Behavior</H2>
          <div className="space-y-2 text-[14px]">
            {(Object.keys(PERSONA_LABELS) as PersonaId[]).map(id => (
              <label key={id} className="flex items-center gap-2">
                <input type="radio" name="persona" value={id} checked={persona===id} onChange={()=>setPersona(id)} />
                <span>{PERSONA_LABELS[id]}</span>
              </label>
            ))}
          </div>
        </div>
        <div>
          <div className="flex items-center justify-between">
            <H2 className="!text-[0.95rem] mb-2">Library</H2>
            <Button onClick={refreshPairs} className="!px-2 !py-1 !text-[12px]">Refresh</Button>
          </div>
          <div className="flex flex-wrap items-center gap-2 mb-2 text-[12px]">
            <label className="flex items-center gap-1">
              <input type="checkbox" checked={onlyAnnotated} onChange={e=>{ setOnlyAnnotated(e.target.checked); }} />
              Only annotated
            </label>
            <select value={annoSentiment} onChange={e=>setAnnoSentiment((e.target as HTMLSelectElement).value as any)} className="border border-paper-200 dark:border-ink-700 rounded px-1 py-0.5">
              <option value="">any</option>
              <option value="positive">positive</option>
              <option value="negative">negative</option>
            </select>
            <button className="ml-auto underline" onClick={()=> setShowTime(s=>!s)}>{showTime? 'Hide time range':'Time range'}</button>
            <Button className="!px-2 !py-1 !text-[12px]" onClick={()=>{
              const s = since? Number(since) : undefined; const u = until? Number(until) : undefined; exportAnnotationsDataset('jsonl', { since: s, until: u });
            }}>Export</Button>
          </div>
          {showTime && (
            <div className="mb-2 grid grid-cols-2 gap-2 text-[12px]">
              <input type="number" placeholder="since (epoch s)" value={since} onChange={e=>setSince((e.target as HTMLInputElement).value)} className="w-full px-2 py-1 border border-paper-200 dark:border-ink-700 rounded" />
              <input type="number" placeholder="until (epoch s)" value={until} onChange={e=>setUntil((e.target as HTMLInputElement).value)} className="w-full px-2 py-1 border border-paper-200 dark:border-ink-700 rounded" />
              <Button className="!px-2 !py-1 !text-[12px]" onClick={async()=>{
                try{ const s = since? Number(since): undefined; const u = until? Number(until): undefined; const sum = await getAnnotationsSummary({ since: s, until: u }); setSummary({ total_annotations: sum.total_annotations, total_pairs: sum.total_pairs, by_sentiment: sum.by_sentiment, top_tags: sum.top_tags }); }catch{}
              }}>Preview</Button>
              {summary && (
                <div className="text-[11px] text-ink-700 dark:text-paper-300 col-span-2">
                  <div>Total: {summary.total_annotations} notes • Pairs: {summary.total_pairs} • Sentiment: +{summary.by_sentiment?.positive||0}/-{summary.by_sentiment?.negative||0}/~{summary.by_sentiment?.neutral||0}</div>
                  {summary.top_tags?.length>0 && <div className="truncate">Top tags: {summary.top_tags.slice(0,6).map(t=>`${t.tag}(${t.count})`).join(', ')}</div>}
                </div>
              )}
            </div>
          )}
          <div className="mb-2">
            <input
              value={q}
              onChange={e=>{
                const v = (e.target as HTMLInputElement).value;
                setQ(v);
                // debounce hybrid search
                if (debRef.current) window.clearTimeout(debRef.current);
                debRef.current = window.setTimeout(async()=>{
                  setLoadingPairs(true);
                  try{
                    if(v.trim()){
                      const items = await searchPairsHybrid(v.trim(), { limit: 10 });
                      setPairs(items);
                    } else {
                      await refreshPairs();
                    }
                  } finally {
                    setLoadingPairs(false);
                  }
                }, 250);
              }}
              placeholder="Search memories…"
              className="w-full text-[12px] px-2 py-1 rounded border border-paper-200 dark:border-ink-700 bg-paper-50 dark:bg-ink-900"
            />
          </div>
          <div className="space-y-2 max-h-56 overflow-auto pr-1">
            {loadingPairs && <div className="text-[12px] text-ink-600">Loading…</div>}
            {!loadingPairs && pairs.length === 0 && <div className="text-[12px] text-ink-600">No saved items yet.</div>}
      {pairs.map(p=>{
              const dt = new Date((p.created_at||0)*1000);
              const when = isFinite(dt.getTime()) ? dt.toLocaleString() : '';
              const title = deriveTitle(p);
              const persona = AGENT_LABEL[p.agent_type] || p.agent_type || 'Agent';
              return (
        <Card key={p.id} className="p-2 text-[12px]">
                  <div className="flex items-center justify-between gap-2">
                    <button className="truncate font-medium text-left hover:underline" onClick={()=> onAttachPair?.(p)} title="Insert into chat">Particular "{title}" — {persona}, {when}</button>
                    <button title="Delete" className="text-red-600 hover:underline ml-2" onClick={async()=>{ await deletePair(p.id); await refreshPairs(); }}>Delete</button>
                  </div>
                  <div className="text-ink-600 truncate">{(p.user_request||'').slice(0,100)}</div>
                  <div className="mt-1 flex items-center gap-2">
                    <button className="underline text-rust-700 dark:text-rust-300" onClick={async()=>{
                      setOpenPairAnno(openPairAnno===p.id? null : p.id);
                      if(!openPairAnnoItems[p.id]){
                        try{ const items = await listAnnotations(p.id); setOpenPairAnnoItems(s=>({...s, [p.id]: items})); }catch{}
                      }
                    }}>Annotations</button>
                    {'annotation_count' in p ? <span className="text-[11px] text-ink-600">{(p as any).annotation_count} notes</span> : null}
                  </div>
                  {openPairAnno===p.id && (
                    <div className="mt-2 max-h-32 overflow-auto space-y-1">
                      {(openPairAnnoItems[p.id]||[]).map((a:any)=> (
                        <div key={a.id} className="border border-paper-200 dark:border-ink-700 rounded p-1">
                          <div className="text-[11px] text-ink-600 flex items-center justify-between">
                            <span>{a.sentiment||'neutral'} {a.rating? `• ${a.rating}/5` : ''} {a.tags?.length? `• ${a.tags.join(', ')}`:''}</span>
                            <button className="text-red-600" onClick={async()=>{ await deleteAnnotation(p.id, a.id); const items = await listAnnotations(p.id); setOpenPairAnnoItems(s=>({...s, [p.id]: items})); }}>Delete</button>
                          </div>
                          {a.text && <div className="text-[12px] whitespace-pre-wrap break-words">“{a.text}”</div>}
                          {a.note && <div className="text-[12px] text-ink-700 dark:text-paper-300">{a.note}</div>}
                        </div>
                      ))}
                      {(!openPairAnnoItems[p.id] || openPairAnnoItems[p.id].length===0) && <div className="text-[12px] text-ink-600">No annotations yet.</div>}
                    </div>
                  )}
                </Card>
              );
            })}
          </div>
        </div>
      </div>
      <div className={(collapsed ? 'hidden sm:block ' : '') + 'mt-auto p-5 text-[12px] text-ink-600 dark:text-paper-400 space-y-1'}>
        <p>webtool-mcp UI</p>
        <p className="text-neutral-600">alpha</p>
      </div>
    </aside>
  );
};
