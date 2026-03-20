import { useEffect, useState, type FC } from 'react';
import { api } from '../lib/api';
import { formatEngineClock } from '../lib/engineTime';
import type { Holding, RunningStrategy } from '../lib/types';

export type Tab = 'Strategies' | 'Logs';

interface SidebarProps {
  tab: Tab;
  setTab: (t: Tab) => void;
  apiBase: string;
  backendOk: boolean;
  engineMode: string | null;
  systemRunning: boolean;
  holdings: Record<string, Holding>;
  running: RunningStrategy[];
  onRefresh: () => Promise<void>;
  onEngineStart: () => void;
}

export const Sidebar: FC<SidebarProps> = ({
  tab,
  setTab,
  apiBase,
  backendOk,
  engineMode,
  systemRunning,
  holdings,
  running,
  onRefresh,
  onEngineStart,
}) => {
  const tabs: Tab[] = ['Strategies', 'Logs'];
  const [now, setNow] = useState<Date>(() => new Date());

  useEffect(() => {
    const t = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(t);
  }, []);

  const clockText = (() => {
    try {
      return formatEngineClock(now);
    } catch {
      return '';
    }
  })();

  return (
    <aside className="flex h-screen flex-col justify-between border-r border-white/10 bg-black/40 px-4 py-5">
      <div>
        <div className="mb-3">
          <div className="text-sm font-semibold tracking-wide text-slate-100">SMUvengers</div>
        </div>
        <div className="mb-4 space-y-1 text-xs text-white/75">
          <div className="truncate">
            <span className="text-white/60">API</span>{' '}
            <span className="font-mono text-xs text-slate-200">{apiBase}</span>
          </div>
          <div className="flex items-center justify-between gap-2">
            <span className="text-white/60">Backend</span>
            <span
              className={[
                'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs',
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
                'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs',
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
        <div className="mb-4 space-y-2 text-xs text-white/70">
          <div className="font-mono uppercase tracking-wide">Engine controls</div>
          <div className="flex flex-wrap gap-1.5">
            <button
              className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-white/20 bg-white/5 px-2 py-1.5 text-xs font-medium text-slate-50 transition hover:border-emerald-400/80 hover:bg-emerald-500/10 disabled:cursor-not-allowed disabled:opacity-40"
              disabled={systemRunning}
              onClick={() => {
                onEngineStart()
                api.systemStart('mock').then(() => onRefresh()).catch(() => {})
              }}
            >
              Mock
            </button>
            <button
              className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-white/20 bg-white/5 px-2 py-1.5 text-xs font-medium text-slate-50 transition hover:border-emerald-400/80 hover:bg-emerald-500/10 disabled:cursor-not-allowed disabled:opacity-40"
              disabled={systemRunning}
              onClick={() => {
                onEngineStart()
                api.systemStart('real').then(() => onRefresh()).catch(() => {})
              }}
            >
              Live
            </button>
            <button
              className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-rose-400/80 bg-rose-500/10 px-2 py-1.5 text-xs font-medium text-rose-100 transition hover:bg-rose-500/20 disabled:cursor-not-allowed disabled:opacity-40"
              disabled={!systemRunning}
              onClick={() => {
                void (async () => {
                  const anyOpen = Object.values(holdings || {}).some((holding) => {
                    const positionRows = Object.values(holding?.positions || {})
                    return positionRows.some((position) => (position?.quantity || 0) !== 0)
                  })
                  const anyStarted = running.some((s) => s.started)

                  if (anyOpen) {
                    window.alert('You must close positions before stopping strategies (use “Close pos” / “Close all”).')
                    return
                  }
                  if (anyStarted) {
                    window.alert('You must stop all strategies before stopping the engine.')
                    return
                  }

                  if (!window.confirm('Stop the engine? This is a destructive action.')) return
                  try {
                    await api.systemStop()
                    await onRefresh()
                  } catch (e: unknown) {
                    const msg = e instanceof Error ? e.message : String(e)
                    window.alert(msg)
                  }
                })()
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
      <div className="mt-6 border-t border-white/10 pt-3 text-xs">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="font-mono uppercase tracking-wide text-white/40">Mode</div>
            <div className="text-white/60">
              {!backendOk ? 'Backend down' : systemRunning ? 'Engine running' : 'Engine stopped'}
            </div>
          </div>
          <div
            className="select-none font-mono text-xs tracking-wide text-emerald-300"
            title="Singapore time (24-hour)"
          >
            {clockText}
          </div>
        </div>
      </div>
    </aside>
  );
};

