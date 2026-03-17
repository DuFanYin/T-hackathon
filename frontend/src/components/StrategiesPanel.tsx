import type { FC } from 'react';
import type { Holding, RunningStrategy } from '../lib/types';

interface StrategiesPanelProps {
  available: string[];
  running: RunningStrategy[];
  activeNames: Set<string>;
  holdings: Record<string, Holding>;
  pairs: string[];
  selectedName: string;
  onSelect: (name: string) => void;
  isAuthed: boolean;
  startStrategy: string;
  setStartStrategy: (s: string) => void;
  startSymbol: string;
  setStartSymbol: (s: string) => void;
  busy: string;
  actionErr: string;
  onAdd: () => Promise<void>;
  onInit: (name: string) => Promise<void>;
  onStartSelected: () => Promise<void>;
  onStop: (name: string) => Promise<void>;
  onDelete: (name: string) => Promise<void>;
}

export const StrategiesPanel: FC<StrategiesPanelProps> = ({
  available,
  running,
  activeNames,
  holdings,
  pairs,
  selectedName,
  onSelect,
  isAuthed,
  startStrategy,
  setStartStrategy,
  startSymbol,
  setStartSymbol,
  busy,
  actionErr,
  onAdd,
  onInit,
  onStartSelected,
  onStop,
  onDelete,
}) => (
  <div className="flex h-full w-full flex-col rounded-xl border border-white/10 bg-white/5 p-4 shadow-[0_10px_30px_rgba(0,0,0,0.5)]">
    <div className="mb-3 flex flex-wrap items-end gap-3">
      <div className="flex flex-col gap-1">
        <label className="text-xs text-white/80">Strategy</label>
        <select
          className="min-w-[220px] rounded-xl border border-white/20 bg-black/40 px-2.5 py-2 text-sm text-slate-50 outline-none ring-0 focus:border-emerald-400 focus:ring-1 focus:ring-emerald-400/40"
          value={startStrategy}
          onChange={(e) => setStartStrategy(e.target.value)}
        >
          {available.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-xs text-white/80">Symbol</label>
        <select
          className="min-w-[220px] rounded-xl border border-white/20 bg-black/40 px-2.5 py-2 text-sm text-slate-50 outline-none ring-0 focus:border-emerald-400 focus:ring-1 focus:ring-emerald-400/40"
          value={startSymbol}
          onChange={(e) => setStartSymbol(e.target.value)}
        >
          {(pairs.length ? pairs : [startSymbol]).map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button
          className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-white/20 bg-white/10 px-3 py-2 text-xs font-medium text-slate-50 transition hover:border-white/40 hover:bg-white/20 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={!isAuthed || busy === 'add'}
          onClick={onAdd}
        >
          Add
        </button>
        <button
          className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-emerald-400/80 bg-emerald-500/10 px-3 py-2 text-xs font-medium text-emerald-100 transition hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={!isAuthed || !selectedName || busy === 'start'}
          onClick={onStartSelected}
        >
          Start
        </button>
        <button
          className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-white/20 bg-white/10 px-3 py-2 text-xs font-medium text-slate-50 transition hover:border-white/40 hover:bg-white/20 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={!isAuthed || !selectedName || busy === selectedName}
          onClick={() => onInit(selectedName)}
        >
          Init
        </button>
        <button
          className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-rose-400/80 bg-rose-500/10 px-3 py-2 text-xs font-medium text-rose-100 transition hover:bg-rose-500/20 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={!isAuthed || !selectedName || busy === selectedName}
          onClick={() => onStop(selectedName)}
        >
          Stop
        </button>
        <button
          className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-white/20 bg-white/5 px-3 py-2 text-xs font-medium text-slate-200 transition hover:border-white/40 hover:bg-white/15 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={!isAuthed || !selectedName || busy === `${selectedName}-del`}
          onClick={() => onDelete(selectedName)}
        >
          Delete
        </button>
      </div>
      {actionErr && (
        <div className="ml-auto font-mono text-[11px] text-rose-300">{actionErr}</div>
      )}
    </div>

    <div className="mt-2 flex-1 overflow-auto rounded-lg border border-white/10 bg-black/40">
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="bg-white/5 text-xs text-white/80">
            <th className="px-2 py-2">Name</th>
            <th className="px-2 py-2">Inited</th>
            <th className="px-2 py-2">Started</th>
            <th className="px-2 py-2">Error</th>
            <th className="px-2 py-2 font-mono">Error msg</th>
            <th className="px-2 py-2">Pos</th>
            <th className="px-2 py-2 text-right">Total cost</th>
            <th className="px-2 py-2 text-right">Value</th>
            <th className="px-2 py-2 text-right">U PnL</th>
            <th className="px-2 py-2 text-right">R PnL</th>
            <th className="px-2 py-2 text-right">PnL</th>
            <th className="px-2 py-2 font-mono">Selected</th>
          </tr>
        </thead>
        <tbody>
          {running.map((s) => (
            <tr
              key={s.name}
              className={[
                'cursor-pointer border-t border-white/5 text-[13px] hover:bg-white/10',
                selectedName === s.name ? 'bg-white/10' : '',
              ].join(' ')}
              onClick={() => onSelect(s.name)}
            >
              <td className="px-2 py-1.5 font-mono text-xs text-slate-100">{s.name}</td>
              <td className="px-2 py-1.5">{String(s.inited)}</td>
              <td className="px-2 py-1.5">{String(s.started)}</td>
              <td className="px-2 py-1.5">{String(s.error)}</td>
              <td className="px-2 py-1.5 font-mono text-[11px] text-white/60">
                {s.error_msg}
              </td>
              <td className="px-2 py-1.5 font-mono text-[11px] text-slate-100">
                {(() => {
                  const h = holdings[s.name];
                  if (!h) return '-';
                  const ps = Object.values(h.positions || {}).filter((p) => p.quantity !== 0);
                  if (ps.length === 0) return 'FLAT';
                  return ps.map((p) => `${p.symbol}:${p.quantity}`).join(', ');
                })()}
              </td>
              <td className="px-2 py-1.5 text-right font-mono text-[11px] tabular-nums">
                {holdings[s.name] ? (holdings[s.name].total_cost ?? 0).toFixed(2) : '-'}
              </td>
              <td className="px-2 py-1.5 text-right font-mono text-[11px] tabular-nums">
                {holdings[s.name] ? (holdings[s.name].current_value ?? 0).toFixed(2) : '-'}
              </td>
              <td className="px-2 py-1.5 text-right font-mono text-[11px] tabular-nums">
                {holdings[s.name] ? (holdings[s.name].unrealized_pnl ?? 0).toFixed(2) : '-'}
              </td>
              <td className="px-2 py-1.5 text-right font-mono text-[11px] tabular-nums">
                {holdings[s.name] ? (holdings[s.name].realized_pnl ?? 0).toFixed(2) : '-'}
              </td>
              <td className="px-2 py-1.5 text-right font-mono text-[11px] tabular-nums">
                {holdings[s.name] ? (holdings[s.name].pnl ?? 0).toFixed(2) : '-'}
              </td>
              <td className="px-2 py-1.5 font-mono text-[11px]">
                {selectedName === s.name ? 'YES' : ''}
              </td>
            </tr>
          ))}
          {running.length === 0 && (
            <tr>
              <td
                colSpan={12}
                className="px-2 py-4 text-center text-xs text-white/70"
              >
                No running strategies (use the form above to start one).
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>

    <div className="mt-3 text-xs text-white/70">
      Available strategies:{' '}
      {available.length ? (
        <span className="font-mono text-[11px] text-slate-100">
          {available.join(', ')}
        </span>
      ) : (
        '(none)'
      )}
      <br />
      Active instances:{' '}
      <span className="font-mono text-[11px] text-slate-100">{activeNames.size}</span>
    </div>
  </div>
);

