import { useEffect, useState, type FC } from 'react';

export type Tab = 'Strategies' | 'Account' | 'Orders' | 'Logs';

interface SidebarProps {
  tab: Tab;
  setTab: (t: Tab) => void;
  apiBase: string;
  backendOk: boolean;
  engineMode: string | null;
  systemRunning: boolean;
  isAuthed: boolean;
  onLogin: (token: string) => Promise<boolean>;
  onLogout: () => void;
  onStartMock: () => void;
  onStartLive: () => void;
  onStopSystem: () => void | Promise<void>;
}

export const Sidebar: FC<SidebarProps> = ({
  tab,
  setTab,
  apiBase,
  backendOk,
  engineMode,
  systemRunning,
  isAuthed,
  onLogin,
  onLogout,
  onStartMock,
  onStartLive,
  onStopSystem,
}) => {
  const tabs: Tab[] = ['Strategies', 'Account', 'Orders', 'Logs'];
  const [now, setNow] = useState<Date>(() => new Date());

  useEffect(() => {
    const t = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(t);
  }, []);

  const clockText = (() => {
    try {
      return now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch {
      return '';
    }
  })();

  return (
    <aside className="flex h-screen flex-col justify-between border-r border-white/10 bg-black/40 px-4 py-5">
      <div>
        <div className="mb-3 text-sm font-semibold tracking-wide text-slate-100">
          T-hackathon
        </div>
        <div className="mb-4 space-y-1 text-xs text-white/75">
          <div className="truncate">
            <span className="text-white/60">API</span>{' '}
            <span className="font-mono text-[11px] text-slate-200">{apiBase}</span>
          </div>
          <div className="flex items-center justify-between gap-2">
            <span className="text-white/60">Backend</span>
            <span
              className={[
                'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px]',
                backendOk
                  ? 'border-emerald-400/80 text-emerald-200'
                  : 'border-rose-400/80 text-rose-200',
              ].join(' ')}
            >
              <span
                className={[
                  'h-1.5 w-1.5 rounded-full',
                  backendOk ? 'bg-emerald-400' : 'bg-rose-400',
                ].join(' ')}
              />
              {backendOk ? 'UP' : 'DOWN'}
            </span>
          </div>
          <div className="flex items-center justify-between gap-2">
            <span className="text-white/60">Engine</span>
            <span
              className={[
                'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px]',
                systemRunning
                  ? 'border-emerald-400/80 text-emerald-200'
                  : 'border-rose-400/80 text-rose-200',
              ].join(' ')}
            >
              <span
                className={[
                  'h-1.5 w-1.5 rounded-full',
                  systemRunning ? 'bg-emerald-400' : 'bg-rose-400',
                ].join(' ')}
              />
              {systemRunning ? (engineMode || 'RUNNING').toUpperCase() : 'STOPPED'}
            </span>
          </div>
        </div>
        <div className="mb-4 space-y-2 text-[11px] text-white/70">
          <div className="font-mono uppercase tracking-wide">Authentication</div>
          {!isAuthed ? (
            <form
              className="flex flex-col gap-1.5"
              onSubmit={async (e) => {
                e.preventDefault();
                const fd = new FormData(e.currentTarget);
                const token = String(fd.get('admin_token') || '').trim();
                if (token) await onLogin(token);
              }}
            >
              <input
                name="username"
                type="text"
                autoComplete="username"
                className="hidden"
              />
              <input
                name="admin_token"
                type="password"
                autoComplete="new-password"
                placeholder="Admin token"
                className="rounded-lg border border-white/20 bg-black/40 px-2 py-1.5 text-[11px] text-slate-50 outline-none ring-0 focus:border-emerald-400 focus:ring-1 focus:ring-emerald-400/40"
              />
              <button
                type="submit"
                className="inline-flex items-center justify-center rounded-lg border border-white/20 bg-white/10 px-2 py-1.5 text-[11px] font-medium text-slate-50 transition hover:border-white/40 hover:bg-white/20"
              >
                Login
              </button>
            </form>
          ) : (
            <div className="flex items-center justify-between gap-2">
              <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-400/80 bg-emerald-500/10 px-2 py-0.5 text-[11px] text-emerald-100">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                Logged in
              </span>
              <button
                type="button"
                className="rounded-lg border border-white/20 bg-white/5 px-2 py-1 text-[11px] text-slate-100 hover:border-white/40 hover:bg-white/15"
                onClick={onLogout}
              >
                Logout
              </button>
            </div>
          )}
        </div>
        <div className="mb-4 space-y-2 text-[11px] text-white/70">
          <div className="font-mono uppercase tracking-wide">Engine controls</div>
          <div className="flex flex-wrap gap-1.5">
            <button
              className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-white/20 bg-white/5 px-2 py-1.5 text-[11px] font-medium text-slate-50 transition hover:border-emerald-400/80 hover:bg-emerald-500/10 disabled:cursor-not-allowed disabled:opacity-40"
              disabled={!isAuthed || systemRunning}
              onClick={onStartMock}
            >
              Mock
            </button>
            <button
              className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-white/20 bg-white/5 px-2 py-1.5 text-[11px] font-medium text-slate-50 transition hover:border-emerald-400/80 hover:bg-emerald-500/10 disabled:cursor-not-allowed disabled:opacity-40"
              disabled={!isAuthed || systemRunning}
              onClick={onStartLive}
            >
              Live
            </button>
            <button
              className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-rose-400/80 bg-rose-500/10 px-2 py-1.5 text-[11px] font-medium text-rose-100 transition hover:bg-rose-500/20 disabled:cursor-not-allowed disabled:opacity-40"
              disabled={!isAuthed || !systemRunning}
              onClick={() => {
                void onStopSystem();
              }}
            >
              Stop
            </button>
          </div>
        </div>
        <nav className="flex flex-col gap-1 pt-1 border-t border-white/10">
          {tabs.map((t) => {
            const active = tab === t;
            return (
              <button
                key={t}
                className={[
                  'flex items-center justify-between rounded-lg border px-2.5 py-2 text-left text-xs font-medium transition',
                  active
                    ? 'border-emerald-400/70 bg-emerald-400/5 text-emerald-100'
                    : 'border-white/10 bg-white/5 text-slate-100 hover:border-white/30 hover:bg-white/10',
                ].join(' ')}
                onClick={() => setTab(t)}
              >
                <span>{t}</span>
                {active && <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />}
              </button>
            );
          })}
        </nav>
      </div>
      <div className="mt-6 border-t border-white/10 pt-3 text-[11px]">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="font-mono uppercase tracking-wide text-white/40">Mode</div>
            <div className="text-white/60">
              {!backendOk ? 'Backend down' : systemRunning ? 'Engine running' : 'Engine stopped'}
            </div>
          </div>
          <div className="select-none font-mono text-[12px] tracking-wide text-emerald-300">
            {clockText}
          </div>
        </div>
      </div>
    </aside>
  );
};

