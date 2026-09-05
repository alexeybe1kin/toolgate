import { useCallback, useEffect, useRef, useState } from 'react';
import { Bot, CheckCircle2, Circle, Clock3, Loader2, Plus, Send, ShieldCheck, Trash2, Workflow, Wrench } from 'lucide-react';
import { api } from '../lib/api';
import Button from '../components/Button';

function sessionLabel(session) {
  return session?.target_kind === 'tool' ? 'Tool' : 'Automation';
}

function StageIcon({ status }) {
  if (status === 'completed') return <CheckCircle2 size={16} className="text-emerald-400" />;
  if (status === 'active' || status === 'running') return <Loader2 size={16} className="animate-spin text-accent" />;
  if (status === 'waiting') return <Clock3 size={16} className="text-amber-400" />;
  return <Circle size={16} className="text-muted/50" />;
}

function latestPhaseActivity(activity = []) {
  const seen = new Set();
  return [...activity].reverse().filter((entry) => {
    if (seen.has(entry.phase)) return false;
    seen.add(entry.phase);
    return true;
  }).slice(0, 6);
}

export default function AiBuilderScreen() {
  const [sessions, setSessions] = useState([]);
  const [session, setSession] = useState(null);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const endRef = useRef(null);

  const loadSessions = useCallback(async (preferredId) => {
    const rows = await api.get('/v2/ai/sessions');
    setSessions(rows);
    const nextId = preferredId || rows[0]?.id;
    if (nextId) {
      const selected = await api.get(`/v2/ai/sessions/${nextId}`);
      setSession(selected);
    } else {
      setSession(null);
    }
    setLoading(false);
  }, []);

  useEffect(() => { loadSessions().catch((err) => { setError(err.message); setLoading(false); }); }, [loadSessions]);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [session?.messages, busy]);

  async function select(id) {
    if (busy || id === session?.id) return;
    setError('');
    try { setSession(await api.get(`/v2/ai/sessions/${id}`)); } catch (err) { setError(err.message); }
  }

  async function create(targetKind) {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      const created = await api.post('/v2/ai/sessions', { target_kind: targetKind });
      await loadSessions(created.id);
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }

  async function send() {
    const content = input.trim();
    if (!content || !session || busy) return;
    setInput('');
    setBusy(true);
    setError('');
    const confirmsDraft = Boolean(session.draft) && ['approve', 'approved', 'correct', 'done', 'good', 'looks good', 'perfect', 'ship it', 'that is correct', 'that works', 'yes'].includes(content.toLowerCase().replace(/[^a-z0-9 ]+/g, '').trim());
    const optimistic = {
      ...session,
      status: confirmsDraft ? session.status : 'planning',
      messages: [...session.messages, { role: 'user', content, created_at: new Date().toISOString() }],
      activity: confirmsDraft ? session.activity : [...(session.activity || []), { phase: 'Understanding request', detail: 'Reading the new owner message.', status: 'running', created_at: new Date().toISOString() }],
    };
    setSession(optimistic);
    try {
      const updated = await api.post(`/v2/ai/sessions/${session.id}/messages`, { content });
      setSession(updated);
      setSessions((rows) => rows.map((row) => row.id === updated.id ? updated : row).sort((a, b) => b.updated_at.localeCompare(a.updated_at)));
    } catch (err) {
      setError(err.message);
      setSession(await api.get(`/v2/ai/sessions/${session.id}`).catch(() => optimistic));
    } finally { setBusy(false); }
  }

  async function submit() {
    if (!session?.draft || busy) return;
    setBusy(true);
    setError('');
    try {
      const result = await api.post(`/v2/ai/sessions/${session.id}/submit`);
      setSession(result.session);
      setSessions((rows) => rows.map((row) => row.id === result.session.id ? result.session : row));
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }

  async function remove() {
    if (!session || !window.confirm(`Delete this AI design chat and its history?`)) return;
    setBusy(true);
    try {
      await api.del(`/v2/ai/sessions/${session.id}`);
      setSession(null);
      await loadSessions();
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }

  return <div className="mx-auto flex min-h-[calc(100svh-1px)] max-w-[1900px] flex-col bg-background md:h-svh md:flex-row md:overflow-hidden">
    <aside className="flex shrink-0 flex-col border-b border-border bg-surface md:w-72 md:border-b-0 md:border-r">
      <div className="border-b border-border p-4">
        <div className="flex items-center gap-2"><span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/15 text-accent"><Bot size={17} /></span><div><h1 className="text-sm font-semibold">ToolGate AI</h1><p className="text-[11px] text-muted">Persistent design workspace</p></div></div>
        <div className="mt-4 grid grid-cols-2 gap-2"><Button variant="secondary" className="!px-2 !py-2 text-xs" onClick={() => create('tool')} disabled={busy}><Wrench size={13} /><Plus size={11} /> Tool</Button><Button variant="secondary" className="!px-2 !py-2 text-xs" onClick={() => create('automation')} disabled={busy}><Workflow size={13} /><Plus size={11} /> Automation</Button></div>
      </div>
      <div className="flex gap-2 overflow-x-auto p-2 md:block md:flex-1 md:overflow-y-auto">
        {loading && <p className="p-3 text-xs text-muted">Loading history...</p>}
        {!loading && sessions.length === 0 && <div className="p-4 text-xs leading-5 text-muted">No design chats yet. Start a Tool or Automation session above.</div>}
        {sessions.map((item) => <button key={item.id} onClick={() => select(item.id)} className={`mb-1 min-w-56 rounded-lg border px-3 py-3 text-left transition-colors md:w-full md:min-w-0 ${session?.id === item.id ? 'border-accent/30 bg-accent/10' : 'border-transparent hover:bg-white/[0.04]'}`}><div className="flex items-center gap-2"><span className="text-accent">{item.target_kind === 'tool' ? <Wrench size={13} /> : <Workflow size={13} />}</span><span className="truncate text-xs font-medium text-text">{item.title}</span></div><div className="mt-2 flex items-center justify-between text-[10px] text-muted"><span className="capitalize">{item.status.replace('_', ' ')}</span><span>{new Date(item.updated_at).toLocaleDateString()}</span></div></button>)}
      </div>
      <div className="hidden border-t border-border p-4 text-[11px] leading-5 text-muted md:block">Chats and requests are stored locally in ToolGate. The planner cannot execute or approve its own draft.</div>
    </aside>

    <main className="flex min-h-[620px] min-w-0 flex-1 flex-col">
      {!session ? <div className="flex flex-1 items-center justify-center p-8"><div className="max-w-md text-center"><span className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl border border-border bg-surface text-accent"><Bot size={22} /></span><h2 className="mt-5 text-lg font-semibold">Design a controlled capability</h2><p className="mt-2 text-sm leading-6 text-muted">Start a Tool for one atomic action or an Automation for a workflow that combines tools and control blocks.</p><div className="mt-5 flex justify-center gap-2"><Button onClick={() => create('tool')}><Wrench size={14} /> New tool chat</Button><Button variant="secondary" onClick={() => create('automation')}><Workflow size={14} /> New automation chat</Button></div></div></div> : <>
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-surface px-5 py-4"><div><div className="flex items-center gap-2"><span className="rounded-md border border-border bg-background px-2 py-1 text-[10px] font-medium uppercase tracking-wider text-muted">{sessionLabel(session)}</span><h2 className="max-w-xl truncate text-sm font-semibold">{session.title}</h2></div><p className="mt-1 text-xs text-muted">The planner asks questions until the contract and controls are complete.</p></div><Button variant="ghost" className="text-red-400" onClick={remove} disabled={busy}><Trash2 size={14} /> Delete chat</Button></header>
        <div className="flex-1 space-y-5 overflow-y-auto px-5 py-6 md:px-8">{session.messages.map((message, index) => <div key={`${message.created_at}-${index}`} className={`flex gap-3 ${message.role === 'user' ? 'justify-end' : ''}`}>{message.role === 'assistant' && <span className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-accent/20 bg-accent/10 text-accent"><Bot size={15} /></span>}<div className={`max-w-[82%] rounded-2xl px-4 py-3 text-sm leading-6 ${message.role === 'user' ? 'rounded-tr-sm bg-accent text-white' : 'rounded-tl-sm border border-border bg-surface text-slate-200'}`}>{message.content}<div className={`mt-2 text-[10px] ${message.role === 'user' ? 'text-white/60' : 'text-muted'}`}>{new Date(message.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</div></div></div>)}{busy && <div className="flex gap-3"><span className="flex h-8 w-8 items-center justify-center rounded-full bg-accent/10 text-accent"><Bot size={15}/></span><div className="rounded-2xl rounded-tl-sm border border-border bg-surface px-4 py-3 text-sm text-muted"><Loader2 size={14} className="mr-2 inline animate-spin" />Planning the next safe step...</div></div>}<div ref={endRef} /></div>
        {error && <div className="mx-5 mb-3 rounded-lg border border-red-500/25 bg-red-500/10 px-4 py-3 text-sm text-red-300 md:mx-8">{error}</div>}
        <div className="border-t border-border bg-surface p-4 md:px-8"><div className="rounded-xl border border-border bg-background p-2 focus-within:border-accent"><textarea value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); send(); } }} rows="3" disabled={busy || session.status === 'submitted'} placeholder={session.status === 'submitted' ? 'This proposal is already in Requests.' : 'Answer the planner or describe what should change...'} className="w-full resize-none bg-transparent px-2 py-1 text-sm text-text outline-none placeholder:text-muted disabled:opacity-50" /><div className="flex items-center justify-between gap-3 px-2 pt-2"><span className="text-[11px] text-muted">Enter to send · Shift+Enter for a new line</span><Button onClick={send} disabled={busy || !input.trim() || session.status === 'submitted'}><Send size={14} /> Send</Button></div></div></div>
      </>}
    </main>

    <aside className="shrink-0 border-t border-border bg-surface md:w-80 md:border-l md:border-t-0">
      <div className="border-b border-border p-5"><div className="flex items-center justify-between"><h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-muted">Build status</h2>{session && <span className="text-[10px] capitalize text-muted">{session.status.replace('_', ' ')}</span>}</div></div>
      {!session ? <p className="p-5 text-sm text-muted">Planning stages appear after you start a session.</p> : <div className="max-h-[calc(100svh-62px)] overflow-y-auto">
        <div className="space-y-1 p-4">{(session.stages || []).map((stage) => <div key={stage.id} className={`flex items-center gap-3 rounded-lg px-3 py-2.5 ${stage.status === 'active' ? 'bg-accent/10' : ''}`}><StageIcon status={stage.status} /><span className={`text-xs ${stage.status === 'queued' ? 'text-muted' : 'text-text'}`}>{stage.label}</span></div>)}</div>
        <div className="border-t border-border p-5"><div className="flex items-center justify-between"><h3 className="text-xs font-medium uppercase tracking-wider text-muted">Latest phase activity</h3><span className="text-[10px] text-muted">Grouped</span></div><div className="mt-4 space-y-4">{latestPhaseActivity(session.activity).map((entry, index) => <div key={`${entry.created_at}-${index}`} className="relative pl-4 before:absolute before:bottom-[-18px] before:left-[3px] before:top-3 before:w-px before:bg-border last:before:hidden"><span className={`absolute left-0 top-1.5 h-2 w-2 rounded-full ${entry.status === 'failed' ? 'bg-red-400' : entry.status === 'running' ? 'animate-pulse bg-accent' : entry.status === 'waiting' ? 'bg-amber-400' : 'bg-emerald-400'}`} /><div className="text-xs font-medium">{entry.phase}</div><p className="mt-1 text-[11px] leading-4 text-muted">{entry.detail}</p></div>)}</div></div>
        {session.draft && <div className="border-t border-border p-5"><div className="mb-3 flex items-center gap-2"><ShieldCheck size={15} className="text-emerald-400" /><h3 className="text-sm font-medium">Typed draft ready</h3></div><div className="rounded-lg border border-border bg-background p-3"><div className="font-mono text-xs text-accent">{session.draft.id}</div><p className="mt-2 text-xs leading-5 text-muted">{session.draft.description}</p><div className="mt-3 flex gap-2 text-[10px] text-muted"><span>{session.draft.authorization?.replace('_', ' ')}</span><span>·</span><span>{session.draft.policy?.usage_limits?.max_per_minute || 10}/min</span></div></div><Button className="mt-3 w-full" onClick={submit} disabled={busy || Boolean(session.proposal_request_id)}>{session.proposal_request_id ? 'Submitted to Requests' : 'Submit for owner approval'}</Button></div>}
      </div>}
    </aside>
  </div>;
}
