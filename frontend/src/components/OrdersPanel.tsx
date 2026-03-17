import type { FC } from 'react';
import { useMemo } from 'react';

import type { OrderRow } from '../lib/types';

function fmtTsSec(ts: number | null | undefined): string {
  if (!ts || !Number.isFinite(ts)) return '';
  try {
    return new Date(ts * 1000).toLocaleString();
  } catch {
    return '';
  }
}

interface OrdersPanelProps {
  isAuthed: boolean;
  busy: boolean;
  strategy: string;
  setStrategy: (v: string) => void;
  symbol: string;
  setSymbol: (v: string) => void;
  limit: number;
  setLimit: (v: number) => void;
  err: string;
  rows: OrderRow[];
  onRefresh: () => void;
}

export const OrdersPanel: FC<OrdersPanelProps> = ({
  isAuthed,
  busy,
  strategy,
  setStrategy,
  symbol,
  setSymbol,
  limit,
  setLimit,
  err,
  rows,
  onRefresh,
}) => {
  const shown = useMemo(() => rows || [], [rows]);
  const strategyOptions = useMemo(() => {
    const set = new Set<string>();
    for (const r of shown) {
      const s = (r?.strategy_name || '').trim();
      if (s) set.add(s);
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b));
  }, [shown]);
  const symbolOptions = useMemo(() => {
    const set = new Set<string>();
    for (const r of shown) {
      const s = (r?.symbol || '').trim();
      if (s) set.add(s);
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b));
  }, [shown]);

  return (
    <div className="flex h-full w-full flex-col rounded-xl border border-white/10 bg-white/5 p-4 shadow-[0_10px_30px_rgba(0,0,0,0.5)]">
      <div className="mb-3 flex flex-wrap items-end gap-2">
        <button
          type="button"
          className="inline-flex items-center justify-center rounded-xl border border-white/20 bg-white/10 px-3 py-2 text-xs font-medium text-slate-50 transition hover:border-white/40 hover:bg-white/20 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={!isAuthed || busy}
          onClick={onRefresh}
        >
          Refresh
        </button>
        <div className="text-xs text-white/70">{isAuthed ? 'Orders' : 'Login to view orders.'}</div>
        {err ? <div className="ml-auto font-mono text-[11px] text-rose-300">{err}</div> : null}
      </div>

      <div className="mb-3 grid grid-cols-1 gap-2 md:grid-cols-3">
        <div className="rounded-lg border border-white/10 bg-black/40 p-3">
          <div className="mb-1 text-[11px] text-white/60">Strategy</div>
          <select
            value={strategy}
            onChange={(e) => setStrategy(e.target.value)}
            className="w-full rounded-lg border border-white/20 bg-black/40 px-2 py-1.5 text-[12px] text-slate-50 outline-none focus:border-emerald-400"
            disabled={!isAuthed}
          >
            <option value="">Any</option>
            {strategyOptions.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <div className="rounded-lg border border-white/10 bg-black/40 p-3">
          <div className="mb-1 text-[11px] text-white/60">Symbol</div>
          <select
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            className="w-full rounded-lg border border-white/20 bg-black/40 px-2 py-1.5 text-[12px] text-slate-50 outline-none focus:border-emerald-400"
            disabled={!isAuthed}
          >
            <option value="">Any</option>
            {symbolOptions.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <div className="rounded-lg border border-white/10 bg-black/40 p-3">
          <div className="mb-1 text-[11px] text-white/60">Limit</div>
          <input
            value={String(limit)}
            onChange={(e) => {
              const n = Number(e.target.value);
              setLimit(Number.isFinite(n) ? Math.max(1, Math.min(5000, Math.floor(n))) : 500);
            }}
            placeholder="500"
            className="w-full rounded-lg border border-white/20 bg-black/40 px-2 py-1.5 text-[12px] text-slate-50 outline-none focus:border-emerald-400"
            disabled={!isAuthed}
          />
        </div>
      </div>

      <div className="flex-1 overflow-auto rounded-lg border border-white/10 bg-black/40">
        <table className="w-full table-fixed border-collapse text-left">
          <thead>
            <tr className="bg-white/5 text-[11px] text-white/70">
              <th className="w-[14%] px-2 py-2">Order</th>
              <th className="w-[16%] px-2 py-2">Strategy</th>
              <th className="w-[12%] px-2 py-2">Symbol</th>
              <th className="w-[8%] px-2 py-2">Side</th>
              <th className="w-[14%] px-2 py-2">Status</th>
              <th className="w-[12%] px-2 py-2 text-right">Qty</th>
              <th className="w-[12%] px-2 py-2 text-right">Filled</th>
              <th className="w-[12%] px-2 py-2">Updated</th>
            </tr>
          </thead>
          <tbody>
            {shown.length ? (
              shown.map((r) => (
                <tr key={r.order_id} className="border-t border-white/5 text-[12px]">
                  <td className="px-2 py-2 font-mono text-slate-100">{r.order_id}</td>
                  <td className="px-2 py-2 font-mono text-slate-100">{r.strategy_name || '-'}</td>
                  <td className="px-2 py-2 font-mono text-slate-100">{r.symbol || '-'}</td>
                  <td className="px-2 py-2 font-mono text-slate-100">{r.side || '-'}</td>
                  <td className="px-2 py-2 font-mono text-slate-100">{r.status || '-'}</td>
                  <td className="px-2 py-2 text-right font-mono text-slate-100">{r.quantity}</td>
                  <td className="px-2 py-2 text-right font-mono text-slate-100">{r.filled_quantity}</td>
                  <td className="px-2 py-2 font-mono text-[11px] text-white/70">{fmtTsSec(r.updated_ts)}</td>
                </tr>
              ))
            ) : (
              <tr className="border-t border-white/5">
                <td className="px-2 py-3 text-xs text-white/70" colSpan={8}>
                  No orders found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

