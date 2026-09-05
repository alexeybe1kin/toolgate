import { useEffect, useRef, useState } from 'react';
import { Link, useLocation } from 'wouter';
import { Activity, Bot, Boxes, Gauge, KeyRound, LockKeyhole, MoreHorizontal, Settings, ShieldCheck, Wrench, Workflow } from 'lucide-react';
import Logo from './Logo';
import { api } from '../lib/api';

const NAV_GROUPS = [
  { label: 'Operate', items: [
    { to: '/command-center', label: 'Command Center', icon: Gauge },
    { to: '/activity', label: 'Live Activity', icon: Activity },
    { to: '/ai-builder', label: 'ToolGate AI', icon: Bot },
  ] },
  { label: 'Capabilities', items: [
    { to: '/automations', label: 'Automations', icon: Workflow },
    { to: '/tools', label: 'Tools', icon: Wrench },
    { to: '/services', label: 'Services', icon: Boxes },
  ] },
  { label: 'Control', items: [
    { to: '/requests', label: 'Requests', icon: ShieldCheck },
    { to: '/verification', label: 'Verification', icon: LockKeyhole },
    { to: '/security', label: 'Security', icon: ShieldCheck },
    { to: '/secrets', label: 'Secrets', icon: KeyRound },
  ] },
  { label: 'System', items: [
    { to: '/settings', label: 'Settings', icon: Settings },
  ] },
];

const ALL_NAV_ITEMS = NAV_GROUPS.flatMap((group) => group.items);
const MOBILE_PRIMARY = ALL_NAV_ITEMS.slice(0, 4);
const MOBILE_OVERFLOW = ALL_NAV_ITEMS.slice(4);

function NavItem({ to, label, icon: Icon }) {
  const [pathname] = useLocation();
  const active = pathname === to || (to !== '/command-center' && pathname.startsWith(`${to}/`));
  return <Link to={to} className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors ${active ? 'bg-white/[0.06] text-text' : 'text-muted hover:bg-white/[0.04] hover:text-text'}`}><Icon size={16} strokeWidth={2} /><span>{label}</span></Link>;
}

function DesktopSidebar({ online }) {
  return <aside className="fixed inset-y-0 left-0 z-20 hidden w-60 flex-col border-r border-border bg-surface md:flex"><div className="px-5 py-5"><Logo /></div><nav className="flex flex-1 flex-col gap-5 overflow-y-auto px-3 pb-4">{NAV_GROUPS.map((group) => <div key={group.label}><div className="mb-1.5 px-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-muted/60">{group.label}</div><div className="space-y-0.5">{group.items.map((item) => <NavItem key={item.to} {...item} />)}</div></div>)}</nav><div className="border-t border-border px-5 py-4"><div className="mb-1 flex items-center gap-1.5 text-xs text-muted"><span className={`h-1.5 w-1.5 rounded-full ${online ? 'bg-emerald-500' : 'bg-red-500'}`} /> ToolGate {online ? 'online' : 'unreachable'}</div><div className="text-xs text-muted">v2.0.0</div></div></aside>;
}

function MobileTabBar() {
  const [moreOpen, setMoreOpen] = useState(false); const ref = useRef(null);
  const [pathname] = useLocation();
  useEffect(() => { const onClick = (event) => { if (ref.current && !ref.current.contains(event.target)) setMoreOpen(false); }; document.addEventListener('mousedown', onClick); return () => document.removeEventListener('mousedown', onClick); }, []);
  const active = (to) => pathname === to || pathname.startsWith(`${to}/`);
  return <nav className="fixed inset-x-0 bottom-0 z-20 border-t border-border bg-surface/95 backdrop-blur md:hidden" ref={ref}>{moreOpen && <div className="border-b border-border bg-surface">{MOBILE_OVERFLOW.map(({ to, label, icon: Icon }) => <Link key={to} to={to} onClick={() => setMoreOpen(false)} className={`flex items-center gap-2.5 px-5 py-2.5 text-sm ${active(to) ? 'text-accent' : 'text-muted'}`}><Icon size={16} strokeWidth={2} />{label}</Link>)}</div>}<div className="flex">{MOBILE_PRIMARY.map(({ to, label, icon: Icon }) => <Link key={to} to={to} className={`flex flex-1 flex-col items-center gap-1 py-2.5 text-[11px] ${active(to) ? 'text-accent' : 'text-muted'}`}><Icon size={20} strokeWidth={2} />{label}</Link>)}<button onClick={() => setMoreOpen((open) => !open)} className={`flex flex-1 flex-col items-center gap-1 py-2.5 text-[11px] ${moreOpen ? 'text-accent' : 'text-muted'}`}><MoreHorizontal size={20} strokeWidth={2} />More</button></div></nav>;
}

export default function Layout({ children }) {
  const [online, setOnline] = useState(true);
  useEffect(() => {
    let active = true;
    const check = () => api.get('/v2/status').then(() => active && setOnline(true)).catch(() => active && setOnline(false));
    check();
    const timer = setInterval(check, 10000);
    return () => { active = false; clearInterval(timer); };
  }, []);
  return <div className="min-h-svh bg-background text-text"><DesktopSidebar online={online} /><MobileTabBar /><main className="pb-28 md:ml-60 md:pb-0">{children}</main></div>;
}
