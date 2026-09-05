import { useEffect, useState } from 'react';
import { useLocation } from 'wouter';
import { Activity, Bot, Check, Loader2, Lock, Plus, RefreshCw, Search, ShieldAlert, Wrench } from 'lucide-react';
import { api } from '../lib/api';
import Button from '../components/Button';
import Modal from '../components/Modal';
import TextField from '../components/TextField';

function Page({ title, note, actions, children }) { return <div className="mx-auto max-w-[1640px] px-5 py-7 md:px-8"><div className="mb-6 flex flex-wrap items-start justify-between gap-4"><div><h1 className="text-xl font-semibold tracking-[-0.02em] text-text">{title}</h1><p className="mt-1 max-w-3xl text-sm leading-6 text-muted">{note}</p></div>{actions}</div>{children}</div>; }
function Card({ children, className = '' }) { return <div className={`rounded-xl border border-border bg-surface ${className}`}>{children}</div>; }
function Empty({ children }) { return <p className="px-5 py-12 text-center text-sm text-muted">{children}</p>; }
function useData(path, interval = 0) { const [data, setData] = useState(null); const [error, setError] = useState(''); async function load() { try { const result = await api.get(path); setData(result); setError(''); return result; } catch (err) { setError(err.message); return null; } } useEffect(() => { let alive = true; const refresh = async () => { const result = await api.get(path).catch((err) => { if (alive) setError(err.message); return null; }); if (alive && result !== null) { setData(result); setError(''); } }; refresh(); if (!interval) return () => { alive = false; }; const timer = setInterval(refresh, interval); return () => { alive = false; clearInterval(timer); }; }, [path, interval]); return { data, error, reload: load }; }

export function CommandCenterScreen() { const { data, reload } = useData('/v2/status', 5000); const { data: events } = useData('/v2/events?limit=8', 5000); const stats = [['Tools', data?.tools ?? '-'], ['Automations', data?.automations ?? '-'], ['Services', data?.services ?? '-'], ['Pending requests', data?.pending_requests ?? '-']]; return <Page title="Command Center" note="Live operating state for the local agent control plane." actions={<Button variant="secondary" onClick={reload}><RefreshCw size={14} /> Refresh</Button>}>{data?.lockdown && <div className="mb-5 flex items-center gap-2 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300"><ShieldAlert size={16} /> Lockdown is active.</div>}<div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{stats.map(([label, value]) => <Card key={label} className="p-5"><div className="text-2xl font-semibold">{value}</div><div className="mt-1 text-xs uppercase tracking-wider text-muted">{label}</div></Card>)}</div><Card className="mt-6"><div className="border-b border-border px-5 py-4 text-sm font-medium">Recent activity</div>{events?.length ? events.map((event) => <div key={event.id} className="flex gap-3 border-b border-border px-5 py-3 last:border-0"><Activity size={15} className="mt-0.5 text-accent" /><div><div className="font-mono text-xs">{event.event_type}</div><div className="mt-1 text-xs text-muted">{event.subject_type} {event.subject_id || ''} - {new Date(event.created_at).toLocaleString()}</div></div></div>) : <Empty>No activity yet.</Empty>}</Card></Page>; }

export function ServicesScreen() { const { data: services, reload } = useData('/v2/services'); const [adding, setAdding] = useState(false); const [name, setName] = useState(''); async function add() { await api.post('/v2/services', { name, description: '', secret_refs: [] }); setName(''); setAdding(false); reload(); } return <Page title="Services" note="Provider connections, secret references, health, linked capabilities, and destination policy." actions={<Button onClick={() => setAdding(true)}><Plus size={14}/> Add service</Button>}>{adding && <Card className="mb-5 p-4"><div className="flex gap-2"><TextField value={name} onChange={(e) => setName(e.target.value)} placeholder="Service name, e.g. MemoryGate" /><Button onClick={add} disabled={!name.trim()}>Save</Button><Button variant="secondary" onClick={() => setAdding(false)}>Cancel</Button></div></Card>}<div className="grid gap-4 md:grid-cols-2">{services?.length ? services.map((service) => <Card key={service.id} className="p-5"><div className="flex items-start justify-between"><div><h2 className="font-medium">{service.name}</h2><p className="mt-1 text-sm text-muted">{service.description || 'No description yet.'}</p></div><span className="rounded bg-white/[0.06] px-2 py-1 text-xs">{service.health}</span></div><div className="mt-5 text-xs text-muted">Secret refs: {service.secret_refs?.length || 0} - {service.status}</div></Card>) : <div className="md:col-span-2"><Empty>No services configured.</Empty></div>}</div></Page>; }

export function AiProposalModal({ targetKind, onClose, onCreated }) {
  const label = targetKind === 'tool' ? 'Tool' : 'Automation';
  const [messages, setMessages] = useState([{ role: 'assistant', content: `I am the ToolGate planner. Tell me what this ${label.toLowerCase()} should accomplish, what it may touch, and when it needs your approval.` }]);
  const [input, setInput] = useState(''); const [draft, setDraft] = useState(null); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  async function send() { if (!input.trim() || busy) return; const next = [...messages, { role: 'user', content: input.trim() }]; setMessages(next); setInput(''); setBusy(true); setError(''); try { const result = await api.post('/v2/ai/conversation', { target_kind: targetKind, messages: next }); setMessages([...next, { role: 'assistant', content: result.reply }]); if (result.ready) setDraft(result.draft); } catch (err) { setError(err.message); } finally { setBusy(false); } }
  async function submit() { setBusy(true); try { await api.post('/v2/ai/proposals', { target_kind: targetKind, draft, conversation: messages }); onCreated(); onClose(); } catch (err) { setError(err.message); } finally { setBusy(false); } }
  return <Modal title="" onClose={onClose} width="max-w-6xl"><div className="-m-1 overflow-hidden rounded-xl border border-border bg-surface"><div className="flex items-center justify-between border-b border-border bg-background px-6 py-4"><div className="flex items-center gap-3"><span className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent/15 text-accent"><Bot size={18} /></span><div><h2 className="text-sm font-semibold">ToolGate AI · {label} designer</h2><p className="mt-0.5 text-xs text-muted">Draft-only planner. No secrets, execution, testing, or self-approval.</p></div></div><span className="rounded-full border border-border px-2.5 py-1 text-[10px] font-medium uppercase tracking-wider text-muted">Safe planning</span></div><div className="grid min-h-[620px] lg:grid-cols-[1.35fr_.65fr]"><section className="flex min-h-0 flex-col border-r border-border"><div className="border-b border-border px-6 py-3 text-xs text-muted">Conversation · describe the outcome naturally. The planner will ask for only the missing safety details.</div><div className="flex-1 space-y-5 overflow-y-auto bg-background px-6 py-6">{messages.map((message, index) => <div key={`${message.role}-${index}`} className={`flex gap-3 ${message.role === 'user' ? 'justify-end' : ''}`}>{message.role === 'assistant' && <span className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent/15 text-accent"><Bot size={14} /></span>}<div className={`max-w-[82%] rounded-2xl px-4 py-3 text-sm leading-6 ${message.role === 'user' ? 'rounded-tr-sm bg-accent text-white' : 'rounded-tl-sm border border-border bg-surface text-slate-200'}`}>{message.content}</div></div>)}{busy && <div className="flex gap-3"><span className="flex h-7 w-7 items-center justify-center rounded-full bg-accent/15 text-accent"><Bot size={14} /></span><div className="rounded-2xl rounded-tl-sm border border-border bg-surface px-4 py-3 text-sm text-muted">Thinking through the safety contract...</div></div>}</div><div className="border-t border-border bg-surface p-4"><div className="rounded-xl border border-border bg-background p-2 focus-within:border-accent"><textarea value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); send(); } }} placeholder={`Describe the ${label.toLowerCase()} you want to build...`} autoFocus rows="3" className="w-full resize-none bg-transparent px-2 py-1 text-sm text-text outline-none placeholder:text-muted" /><div className="flex items-center justify-between px-2 pt-2"><span className="text-[11px] text-muted">Enter to send · Shift+Enter for a new line</span><Button onClick={send} disabled={busy || !input.trim()}>Send message</Button></div></div></div></section><aside className="bg-surface p-5"><div className="text-xs font-medium uppercase tracking-[0.14em] text-muted">Proposed {label}</div>{draft ? <div className="mt-4"><div className="rounded-xl border border-emerald-500/25 bg-emerald-500/10 p-4"><div className="text-sm font-medium text-emerald-100">Draft ready for your review</div><div className="mt-1 font-mono text-xs text-emerald-300">{draft.id}</div></div><p className="mt-4 text-xs leading-5 text-muted">Approval creates it as a draft you can edit in the full {label.toLowerCase()} editor before it is made active.</p><pre className="mt-4 max-h-[300px] overflow-auto rounded-lg border border-border bg-background p-3 text-xs leading-5 text-slate-300">{JSON.stringify(draft, null, 2)}</pre></div> : <div className="mt-5 rounded-xl border border-dashed border-border p-4"><div className="text-sm font-medium">The draft will appear here</div><p className="mt-2 text-xs leading-5 text-muted">This panel turns into a review card once the planner has a name, input contract, workflow, and safety choice.</p></div>}<div className="mt-8 rounded-lg border border-border bg-background p-3 text-xs leading-5 text-muted"><strong className="block text-text">What ToolGate AI can do</strong>Draft, clarify, explain, and recommend. It cannot see secrets or execute anything.</div></aside></div><div className="flex items-center justify-between border-t border-border bg-background px-6 py-4">{error ? <span className="text-sm text-red-400">{error}</span> : <span className="text-xs text-muted">You remain in control of every created capability.</span>}<div className="flex gap-2"><Button variant="secondary" onClick={onClose}>Cancel</Button><Button onClick={submit} disabled={!draft || busy}>Create owner proposal</Button></div></div></div></Modal>;
}

function Catalog({ kind }) {
  const isTool = kind === 'tools';
  const path = `/v2/${kind}`;
  const [, navigate] = useLocation();
  const { data, error: loadError, reload } = useData(path);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState('');
  const [query, setQuery] = useState('');
  const rows = (data || []).filter((item) => `${item.name} ${item.id} ${item.description}`.toLowerCase().includes(query.toLowerCase()));

  async function add() {
    setCreating(true);
    setCreateError('');
    const suffix = Date.now().toString(36);
    const id = `${isTool ? 'untitled-tool' : 'untitled-automation'}-${suffix}`;
    const body = isTool
      ? { id, name: 'Untitled tool', description: 'New typed tool draft.', execution: { type: 'echo' }, inputs: [], outputs: [], authorization: 'auto', status: 'draft' }
      : { id, name: 'Untitled automation', description: '', workflow: [], inputs: [], policy: {}, authorization: 'auto', status: 'draft' };
    try {
      const created = await api.post(path, body);
      await reload();
      navigate(`/${kind}/${created.id}`);
    } catch (err) {
      setCreateError(err.message);
    } finally {
      setCreating(false);
    }
  }

  return <Page
    title={isTool ? 'Tools' : 'Automations'}
    note={isTool ? 'Atomic, typed capabilities exposed to scoped agents.' : 'Versioned workflows that combine approved tools and deterministic control blocks.'}
    actions={<Button onClick={add} disabled={creating}>{creating ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14}/>} {creating ? 'Creating draft...' : `New ${isTool ? 'tool' : 'automation'}`}</Button>}
  >
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
      <label className="relative block w-full max-w-sm"><Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={`Search ${kind}...`} className="w-full rounded-lg border border-border bg-surface py-2 pl-9 pr-3 text-sm text-text outline-none placeholder:text-muted focus:border-accent" /></label>
      <span className="text-xs text-muted">{data ? `${rows.length} of ${data.length}` : 'Loading catalog...'}</span>
    </div>
    {(createError || loadError) && <div className="mb-4 rounded-lg border border-red-500/25 bg-red-500/10 px-4 py-3 text-sm text-red-300">{createError || loadError}</div>}
    <Card>{data === null ? <Empty>Loading {kind}...</Empty> : rows.length ? rows.map((item, index) => <button key={item.id} onClick={() => navigate(`/${kind}/${item.id}`)} className={`group flex w-full flex-wrap items-center gap-4 px-5 py-4 text-left transition-colors hover:bg-white/[0.025] ${index ? 'border-t border-border' : ''}`}><span className="flex h-9 w-9 items-center justify-center rounded-lg border border-border bg-background text-accent"><Wrench size={16}/></span><div className="min-w-52 flex-1"><div className="text-sm font-medium text-text">{item.name || item.id}</div><div className="mt-1 truncate text-xs text-muted">{item.description || item.id} · version {item.version}</div></div><span className="rounded-md border border-border bg-background px-2 py-1 text-xs capitalize text-muted">{item.category || item.status}</span><span className="text-xs capitalize text-muted">{item.authorization?.replace('_', ' ')}</span></button>) : <Empty>{query ? 'No capabilities match this search.' : `No ${kind} yet. Create a draft or design one with AI.`}</Empty>}</Card>
  </Page>;
}
export function ToolsScreen() { return <Catalog kind="tools" />; }
export function AutomationsScreen() { return <Catalog kind="automations" />; }

export function RequestsScreen() { const { data: requests, reload } = useData('/v2/requests'); const [tab, setTab] = useState('Action needed'); const tabs = { 'Action needed': (r) => r.status === 'pending', Verification: (r) => r.status === 'pending' && r.kind === 'verification', Warnings: (r) => r.status === 'pending' && r.kind === 'warning', Updates: (r) => r.status === 'pending' && ['suggestion', 'update'].includes(r.kind), History: (r) => r.status !== 'pending' }; const rows = (requests || []).filter(tabs[tab]); async function decide(id, status) { await api.post(`/v2/requests/${id}/decision`, { status }); reload(); } return <Page title="Requests" note="Owner inbox for proposed changes, verification, warnings, and ToolGate AI drafts."><div className="mb-5 flex flex-wrap gap-2">{Object.keys(tabs).map((label) => <button key={label} onClick={() => setTab(label)} className={`rounded-lg px-3 py-2 text-sm ${tab === label ? 'bg-accent text-white' : 'bg-surface text-muted hover:text-text'}`}>{label}</button>)}</div><Card>{rows.length ? rows.map((request, index) => <div key={request.id} className={`px-5 py-4 ${index ? 'border-t border-border' : ''}`}><div className="flex flex-wrap items-start justify-between gap-3"><div><div className="flex items-center gap-2"><span className="font-medium">{request.title}</span><span className="rounded bg-white/[0.06] px-2 py-0.5 text-xs">{request.kind}</span></div><p className="mt-1 text-sm text-muted">{request.details}</p><p className="mt-2 text-xs text-muted">{request.actor} · {new Date(request.created_at).toLocaleString()}</p></div>{request.status === 'pending' && <div className="flex gap-2"><Button className="!py-1.5 text-xs" onClick={() => decide(request.id, 'approved')}><Check size={13}/> Approve</Button><Button variant="danger" className="!py-1.5 text-xs" onClick={() => decide(request.id, 'rejected')}>Reject</Button></div>}</div></div>) : <Empty>Nothing in this category.</Empty>}</Card></Page>; }

export function ActivityScreen() { const { data: events } = useData('/v2/events?limit=200', 3000); return <Page title="Live Activity" note="Redacted real-time trace of every ToolGate control-plane event."><Card>{events?.length ? events.map((event, index) => <div key={event.id} className={`flex gap-3 px-5 py-3 ${index ? 'border-t border-border' : ''}`}><div className={`mt-1 h-2 w-2 rounded-full ${event.severity === 'critical' ? 'bg-red-500' : event.severity === 'warning' ? 'bg-amber-400' : 'bg-green-400'}`}/><div><div className="font-mono text-sm">{event.event_type}</div><div className="mt-1 text-xs text-muted">{event.subject_type} {event.subject_id || ''} - {event.actor || 'system'} - {new Date(event.created_at).toLocaleString()}</div></div></div>) : <Empty>No activity yet.</Empty>}</Card></Page>; }
export function AiActivityScreen() { const { data: events } = useData('/v2/events?limit=200', 3000); const aiEvents = (events || []).filter((event) => event.event_type.includes('ai') || event.payload?.kind === 'ai_draft'); return <Page title="AI Activity" note="Live planner conversations, drafts, safety findings, and owner decisions."><Card>{aiEvents.length ? aiEvents.map((event, index) => <div key={event.id} className={`flex gap-3 px-5 py-4 ${index ? 'border-t border-border' : ''}`}><Bot size={16} className="mt-0.5 text-accent"/><div><div className="font-mono text-sm">{event.event_type}</div><p className="mt-1 text-xs text-muted">{event.payload?.reply || event.payload?.title || event.payload?.kind || 'Planner activity'} - {new Date(event.created_at).toLocaleString()}</p></div></div>) : <Empty>No ToolGate AI activity yet.</Empty>}</Card></Page>; }

export function SecurityScreen() {
  const { data: keys, reload } = useData('/v2/agent-keys');
  const { data: status, reload: reloadStatus } = useData('/v2/status');
  const [name, setName] = useState('Primary agent');
  const [scopeText, setScopeText] = useState('tool:*');
  const [created, setCreated] = useState('');
  const [error, setError] = useState('');
  async function create() {
    setError('');
    try {
      const scopes = scopeText.split(',').map((value) => value.trim()).filter(Boolean);
      const result = await api.post('/v2/agent-keys', { name, scopes });
      setCreated(result.key);
      reload();
    } catch (err) { setError(err.message); }
  }
  async function revoke(keyId) {
    if (!window.confirm('Revoke this execution key? The agent will immediately lose its ToolGate access.')) return;
    await api.del(`/v2/agent-keys/${keyId}`);
    reload();
  }
  async function lockdown(enabled) {
    await api.post(`/v2/settings/lockdown?enabled=${enabled}&reason=owner_action`);
    reloadStatus();
  }
  return <Page title="Security Center" note="Scoped agent execution keys, integrity state, and emergency controls." actions={<Button variant={status?.lockdown ? 'secondary' : 'danger'} onClick={() => lockdown(!status?.lockdown)}><Lock size={14}/>{status?.lockdown ? 'Unlock ToolGate' : 'Enable lockdown'}</Button>}>
    {status?.lockdown && <div className="mb-5 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200"><strong>Lockdown is active.</strong> Agent execution and planner work are blocked.</div>}
    {created && <div className="mb-5 rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-100"><strong className="block">Execution key created</strong><p className="mt-1 text-xs text-amber-200/80">This value is shown once. Store it in the agent environment, not in chat or source code.</p><div className="mt-3 break-all rounded-lg bg-black/25 p-3 font-mono text-xs">{created}</div></div>}
    <Card className="mb-5 p-5"><h2 className="text-sm font-medium">Issue scoped execution key</h2><div className="mt-4 grid gap-3 md:grid-cols-[1fr_1.4fr_auto]"><TextField label="Agent name" value={name} onChange={(event) => setName(event.target.value)} /><TextField label="Scopes, comma separated" value={scopeText} onChange={(event) => setScopeText(event.target.value)} placeholder="tool:github-search, automation:daily-report" /><Button className="self-end" onClick={create} disabled={!name.trim() || !scopeText.trim()}>Create key</Button></div>{error && <p className="mt-3 text-sm text-red-400">{error}</p>}</Card>
    <Card>{keys?.length ? keys.map((key, index) => <div key={key.id} className={`flex flex-wrap items-center gap-3 px-5 py-4 ${index ? 'border-t border-border' : ''}`}><Lock size={15} className={key.status === 'active' ? 'text-emerald-400' : 'text-muted'}/><div className="min-w-48 flex-1"><div className="text-sm">{key.name}</div><div className="mt-1 text-xs text-muted">{key.status} · {key.scopes.join(', ') || 'no scopes'}{key.last_used_at ? ` · last used ${new Date(key.last_used_at).toLocaleString()}` : ''}</div></div>{key.status === 'active' && <Button variant="danger" className="!py-1.5 text-xs" onClick={() => revoke(key.id)}>Revoke</Button>}</div>) : <Empty>No agent execution keys exist.</Empty>}</Card>
  </Page>;
}

export function VerificationScreen() {
  const { data: requests, reload } = useData('/v2/requests');
  const { data: methods, reload: reloadMethods } = useData('/v2/verification-methods');
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState('Home approval adapter');
  const [secretRef, setSecretRef] = useState('TOOLGATE_CALLBACK_SECRET');
  const [error, setError] = useState('');
  const rows = (requests || []).filter((request) => request.kind === 'verification');

  async function decide(id, status) { await api.post(`/v2/requests/${id}/decision`, { status }); reload(); }
  async function addMethod() {
    setError('');
    try {
      await api.post('/v2/verification-methods', { name, secret_ref: secretRef });
      setAdding(false);
      reloadMethods();
    } catch (err) { setError(err.message); }
  }
  async function removeMethod(id) { await api.del(`/v2/verification-methods/${id}`); reloadMethods(); }

  return <Page title="Verification" note="Replay-safe owner decisions bound to exact action arguments, version, nonce, and expiry." actions={<Button variant="secondary" onClick={() => setAdding(true)}><Plus size={14}/> Callback adapter</Button>}>
    <div className="mb-5 flex items-center gap-3 rounded-xl border border-emerald-500/20 bg-emerald-500/[0.06] p-4"><Check className="text-emerald-400" size={18}/><div><div className="text-sm font-medium">Dashboard confirmation active</div><div className="mt-1 text-xs text-muted">Approved actions are one-time and must be retried with the request ID and unchanged arguments.</div></div></div>
    {adding && <Card className="mb-5 p-5"><h2 className="text-sm font-medium">Add signed callback adapter</h2><p className="mt-1 text-xs leading-5 text-muted">Phone, ring, or home adapters sign the timestamp and canonical JSON using a vault secret.</p><div className="mt-4 grid gap-3 md:grid-cols-[1fr_1fr_auto]"><TextField label="Method name" value={name} onChange={(event) => setName(event.target.value)} /><TextField label="Vault secret reference" value={secretRef} onChange={(event) => setSecretRef(event.target.value.toUpperCase())} /><Button className="self-end" onClick={addMethod}>Create</Button></div>{error && <p className="mt-3 text-xs text-red-400">{error}</p>}<button className="mt-3 text-xs text-muted" onClick={() => setAdding(false)}>Cancel</button></Card>}
    <div className="mb-5 grid gap-3 md:grid-cols-2">{methods?.map((method) => <Card key={method.id} className="p-4"><div className="flex items-start justify-between gap-4"><div><div className="text-sm font-medium">{method.name}</div><div className="mt-1 font-mono text-xs text-muted">{method.secret_ref}</div></div><span className="rounded bg-white/[0.06] px-2 py-1 text-xs text-muted">{method.status}</span></div><div className="mt-4 flex items-center justify-between text-xs text-muted"><span>{method.last_seen_at ? `Last callback ${new Date(method.last_seen_at).toLocaleString()}` : 'No callback received yet'}</span><button className="text-red-400" onClick={() => removeMethod(method.id)}>Remove</button></div></Card>)}</div>
    <Card><div className="border-b border-border px-5 py-4 text-sm font-medium">Approval history</div>{rows.length ? rows.map((request, index) => <div key={request.id} className={`px-5 py-4 ${index ? 'border-t border-border' : ''}`}><div className="flex flex-wrap items-start justify-between gap-4"><div><div className="text-sm font-medium">{request.title}</div><p className="mt-1 text-sm text-muted">{request.details}</p><div className="mt-2 text-xs text-muted">{request.status}{request.payload?.binding?.expires_at ? ` · expires ${new Date(request.payload.binding.expires_at).toLocaleString()}` : ''}{request.payload?.binding?.consumed_at ? ' · consumed' : ''}</div></div>{request.status === 'pending' && <div className="flex gap-2"><Button onClick={() => decide(request.id, 'approved')}><Check size={13}/>Approve</Button><Button variant="danger" onClick={() => decide(request.id, 'rejected')}>Reject</Button></div>}</div></div>) : <Empty>No verification requests.</Empty>}</Card>
  </Page>;
}

export function SettingsScreen() {
  const { data, reload } = useData('/v2/settings');
  const [values, setValues] = useState(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => { if (data) setValues(data); }, [data]);
  async function save() {
    await api.put('/v2/settings', {
      planner_model: values.planner_model,
      event_retention_days: Number(values.event_retention_days),
      default_confirmation_expiry_seconds: Number(values.default_confirmation_expiry_seconds),
      producthunt_commercial_use_approved: Boolean(values.producthunt_commercial_use_approved),
    });
    setSaved(true);
    reload();
  }
  if (!values) return <Page title="Settings" note="Global ToolGate defaults."><Empty>Loading settings...</Empty></Page>;
  return <Page title="Settings" note="Global defaults for ToolGate. Sensitive access and emergency controls stay in Security Center."><div className="grid gap-5 lg:grid-cols-2"><Card className="p-5"><h2 className="text-sm font-medium">Planner defaults</h2><div className="mt-5 space-y-4"><TextField label="Planner model" value={values.planner_model} onChange={(event) => setValues({ ...values, planner_model: event.target.value })} /><TextField label="Event retention days" type="number" value={values.event_retention_days} onChange={(event) => setValues({ ...values, event_retention_days: event.target.value })} /><TextField label="Default confirmation expiry (seconds)" type="number" value={values.default_confirmation_expiry_seconds} onChange={(event) => setValues({ ...values, default_confirmation_expiry_seconds: event.target.value })} /></div><div className="mt-5 flex items-center gap-3"><Button onClick={save}>Save settings</Button>{saved && <span className="text-xs text-green-400">Saved</span>}</div></Card><div className="space-y-5"><Card className="p-5"><h2 className="text-sm font-medium">Research providers</h2><label className="mt-4 flex cursor-pointer items-start gap-3 rounded-lg border border-border bg-background p-4"><input type="checkbox" className="mt-0.5 h-4 w-4 accent-blue-500" checked={Boolean(values.producthunt_commercial_use_approved)} onChange={(event) => setValues({ ...values, producthunt_commercial_use_approved: event.target.checked })} /><span><span className="block text-sm text-text">Product Hunt business-use approval confirmed</span><span className="mt-1 block text-xs leading-5 text-muted">Enable the read-only API provider only after Product Hunt approves commercial use and PRODUCTHUNT_TOKEN is stored in Secrets. Search falls back safely when either requirement is missing.</span></span></label></Card><Card className="p-5"><h2 className="text-sm font-medium">Control plane</h2><div className="mt-5 space-y-3 text-sm"><div className="flex justify-between"><span className="text-muted">Execution state</span><span className={values.lockdown ? 'text-red-400' : 'text-green-400'}>{values.lockdown ? 'Lockdown active' : 'Online'}</span></div><div className="flex justify-between"><span className="text-muted">Owner mode</span><span>Single owner</span></div><div className="flex justify-between"><span className="text-muted">Agent access</span><span>Scoped execution keys</span></div></div></Card></div></div></Page>;
}
