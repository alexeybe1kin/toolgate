import { useEffect, useState } from 'react';
import { KeyRound, Loader2, Pencil, Plus, Trash2 } from 'lucide-react';
import { api } from '../lib/api';
import Modal from '../components/Modal';
import Button, { IconButton } from '../components/Button';
import TextField from '../components/TextField';

function SecretModal({ mode, name, onClose, onSaved }) {
  const [secretName, setSecretName] = useState(name || '');
  const [value, setValue] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const isAdd = mode === 'add';

  async function save() {
    if (!secretName || !value) return;
    setSaving(true);
    setError('');
    try {
      if (isAdd) await api.post('/vault/secrets', { name: secretName, value });
      else await api.put(`/vault/secrets/${secretName}`, { value });
      await onSaved();
      onClose();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSaving(false);
    }
  }

  return <Modal title={isAdd ? 'Add secret' : `Replace ${secretName}`} onClose={onClose}>
    <div className="space-y-3">
      <TextField label="Vault reference" value={secretName} disabled={!isAdd}
        onChange={(event) => setSecretName(event.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, '_'))}
        placeholder="GITHUB_TOKEN" autoFocus={isAdd} />
      <TextField label={isAdd ? 'Secret value' : 'New secret value'} type="password" value={value}
        onChange={(event) => setValue(event.target.value)} placeholder="************" autoFocus={!isAdd}
        onKeyDown={(event) => event.key === 'Enter' && save()} />
      <p className="text-xs leading-5 text-muted">Values are accepted once and remain write-only. They cannot be revealed later from ToolGate.</p>
      {error && <p className="text-sm text-red-400">{error}</p>}
    </div>
    <div className="mt-5 flex justify-end gap-2">
      <Button variant="secondary" onClick={onClose}>Cancel</Button>
      <Button onClick={save} disabled={saving || !secretName || !value}>
        {saving ? <Loader2 size={14} className="animate-spin" /> : isAdd ? 'Store secret' : 'Replace secret'}
      </Button>
    </div>
  </Modal>;
}

function DeleteSecretModal({ name, onClose, onDeleted }) {
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState('');

  async function remove() {
    setDeleting(true);
    setError('');
    try {
      await api.del(`/vault/secrets/${name}`);
      await onDeleted();
      onClose();
    } catch (requestError) {
      setError(requestError.message);
      setDeleting(false);
    }
  }

  return <Modal title="Delete secret" onClose={onClose}>
    <p className="text-sm leading-6 text-muted">Delete <span className="font-mono text-text">{name}</span>? Capabilities that reference it will fail closed until a replacement is stored.</p>
    {error && <p className="mt-2 text-sm text-red-400">{error}</p>}
    <div className="mt-5 flex justify-end gap-2">
      <Button variant="secondary" onClick={onClose}>Cancel</Button>
      <Button variant="danger" onClick={remove} disabled={deleting}>
        {deleting ? <Loader2 size={14} className="animate-spin" /> : 'Delete'}
      </Button>
    </div>
  </Modal>;
}

export default function SecretsScreen() {
  const [names, setNames] = useState(null);
  const [modal, setModal] = useState(null);
  const [error, setError] = useState('');

  async function load() {
    try {
      setNames(await api.get('/vault/secrets'));
      setError('');
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  useEffect(() => { load(); }, []);

  return <div className="workspace-page">
    <div className="workspace-header">
      <div><h1>Secrets</h1><p>Write-only credentials injected into explicitly linked services and tools.</p></div>
      <Button onClick={() => setModal({ type: 'add' })}><Plus size={15} /> Add secret</Button>
    </div>

    <div className="mb-5 rounded-xl border border-emerald-500/20 bg-emerald-500/[0.04] px-4 py-3">
      <div className="flex items-center gap-2 text-sm font-medium text-emerald-300"><KeyRound size={15} /> Values never leave the vault</div>
      <p className="mt-1 text-xs leading-5 text-muted">The dashboard and agent APIs can list reference names, but there is no endpoint to reveal stored values. Replace a value when rotation is needed.</p>
    </div>

    {error && <p className="mb-4 text-sm text-red-400">{error}</p>}
    {names === null && !error && <div className="flex items-center gap-2 text-sm text-muted"><Loader2 size={14} className="animate-spin" /> Loading...</div>}
    {names?.length === 0 && <div className="rounded-xl border border-dashed border-border py-16 text-center"><KeyRound size={22} className="mx-auto mb-3 text-muted" /><p className="text-sm text-muted">No vault references yet.</p></div>}
    {names?.length > 0 && <div className="overflow-hidden rounded-xl border border-border bg-surface">
      {names.map((name, index) => <div key={name} className={`flex items-center gap-4 px-4 py-3 ${index ? 'border-t border-border' : ''}`}>
        <span className="min-w-0 flex-1 truncate font-mono text-sm text-text">{name}</span>
        <span className="hidden flex-1 text-center text-muted tracking-widest sm:block">************</span>
        <div className="flex shrink-0 items-center gap-1">
          <IconButton title="Replace value" onClick={() => setModal({ type: 'edit', name })}><Pencil size={15} /></IconButton>
          <IconButton title="Delete" onClick={() => setModal({ type: 'delete', name })}><Trash2 size={15} /></IconButton>
        </div>
      </div>)}
    </div>}

    {modal?.type === 'add' && <SecretModal mode="add" onClose={() => setModal(null)} onSaved={load} />}
    {modal?.type === 'edit' && <SecretModal mode="edit" name={modal.name} onClose={() => setModal(null)} onSaved={load} />}
    {modal?.type === 'delete' && <DeleteSecretModal name={modal.name} onClose={() => setModal(null)} onDeleted={load} />}
  </div>;
}
