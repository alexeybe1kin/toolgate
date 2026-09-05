import { useState } from 'react';
import { KeyRound, ArrowRight, Loader2 } from 'lucide-react';
import { useAuth } from '../context/useAuth';
import Logo from '../components/Logo';

export default function AuthScreen() {
  const { login } = useAuth();
  const [value, setValue] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  async function onSubmit(e) {
    e.preventDefault();
    if (!value.trim()) return;
    setSubmitting(true);
    setError('');
    const ok = await login(value.trim());
    setSubmitting(false);
    if (!ok) setError('Invalid key. Check the admin key and try again.');
  }

  return (
    <div className="flex min-h-svh items-center justify-center bg-background px-6">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex justify-center">
          <Logo />
        </div>

        <div className="rounded-xl border border-border bg-surface p-6">
          <h1 className="text-base font-medium text-text">Enter admin key</h1>
          <p className="mt-1 text-sm text-muted">
            Tailscale-only access. Emolga can't reach this.
          </p>

          <form onSubmit={onSubmit} className="mt-5">
            <div className="relative">
              <KeyRound size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
              <input
                autoFocus
                type="password"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                placeholder="TOOLGATE_ADMIN_KEY"
                className="w-full rounded-lg border border-border bg-background py-2.5 pl-9 pr-3 text-sm text-text placeholder:text-muted/70
                           outline-none transition-colors focus-visible:border-accent"
              />
            </div>

            {error && <p className="mt-2 text-sm text-red-400">{error}</p>}

            <button
              type="submit"
              disabled={submitting || !value.trim()}
              className="mt-4 flex w-full items-center justify-center gap-1.5 rounded-lg bg-accent py-2.5 text-sm font-medium text-white
                         transition-colors hover:bg-accent-hover active:translate-y-px disabled:opacity-40 disabled:hover:bg-accent
                         focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              {submitting ? <Loader2 size={15} className="animate-spin" /> : <>Unlock <ArrowRight size={15} /></>}
            </button>
          </form>
        </div>

        <p className="mt-6 text-center text-xs text-muted">
          No cookies. No localStorage. Session only.
        </p>
      </div>
    </div>
  );
}
