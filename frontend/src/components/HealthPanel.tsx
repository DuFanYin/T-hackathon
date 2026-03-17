import type { FC } from 'react';
import type { SystemStatus } from '../lib/types';

interface SystemStatusPanelProps {
  health: { ok: boolean; env_mode?: string } | null;
  healthErr: string;
  system: SystemStatus;
  onStartMock: () => void;
  onStartLive: () => void;
  onStopSystem: () => void;
}

export const SystemStatusPanel: FC<SystemStatusPanelProps> = ({
  health,
  healthErr,
  system,
  onStartMock,
  onStartLive,
  onStopSystem,
}) => (
  <div className="flex h-full w-full flex-col rounded-xl border border-white/10 bg-white/5 p-4 shadow-[0_10px_30px_rgba(0,0,0,0.5)]">
    <div className="mb-3 flex flex-wrap items-center gap-3">
      <div className="space-y-1">
        <div className="text-xs text-white/70">Engine mode</div>
        <div className="font-mono text-sm text-slate-50">
          {system.running ? system.mode?.toUpperCase() : 'STOPPED'}
        </div>
      </div>
      <div className="ml-auto flex flex-wrap items-center gap-2">
        <button
          className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-white/20 bg-white/10 px-3 py-2 text-xs font-medium text-slate-50 transition hover:border-emerald-400/80 hover:bg-emerald-400/10 disabled:cursor-not-allowed disabled:opacity-40"
          disabled={system.running}
          onClick={onStartMock}
        >
          Start mock
        </button>
        <button
          className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-white/20 bg-white/10 px-3 py-2 text-xs font-medium text-slate-50 transition hover:border-emerald-400/80 hover:bg-emerald-400/10 disabled:cursor-not-allowed disabled:opacity-40"
          disabled={system.running}
          onClick={onStartLive}
        >
          Start live
        </button>
        <button
          className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-rose-400/80 bg-rose-500/10 px-3 py-2 text-xs font-medium text-rose-100 transition hover:bg-rose-500/20 disabled:cursor-not-allowed disabled:opacity-40"
          disabled={!system.running}
          onClick={onStopSystem}
        >
          Stop system
        </button>
      </div>
    </div>
    <div className="font-mono text-[11px] uppercase tracking-wide text-white/50">
      Engine health payload (/health)
    </div>
    <div className="mt-2 rounded-lg border border-white/10 bg-black/40 p-3">
      {health ? (
        <pre className="font-mono text-[11px] leading-snug text-slate-100">
          {JSON.stringify(health, null, 2)}
        </pre>
      ) : (
        <div className="font-mono text-xs text-white/70">{healthErr || 'No data'}</div>
      )}
    </div>
  </div>
);

