import type { FC } from 'react';
import { formatEngineDateTimeOrDash } from '../lib/engineTime';

type OrderTrack = {
  order_id: string;
  strategy_name: string;
  symbol: string;
  pair?: string;
  side: string;
  type?: string;
  status: string;
  price?: number;
  quantity?: number;
  filled_quantity?: number;
  filled_avg_price?: number;
  create_timestamp?: number | null;
  finish_timestamp?: number | null;
  role?: string;
  stop_type?: string;
};

type CachedOrdersShape = {
  tracks?: OrderTrack[];
  last_order_query_ts?: number | null;  // Unix seconds when we last ran query_order
};

function fmtTs(ts: number | null | undefined): string {
  return formatEngineDateTimeOrDash(ts);
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === 'object' && !Array.isArray(v);
}

function StatusTag({ status }: { status: string }) {
  const s = (status || 'UNKNOWN').toUpperCase();
  const style =
    s === 'FILLED'
      ? 'rounded border border-emerald-400/80 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] text-emerald-100'
      : s === 'PENDING' || s === 'NEW'
        ? 'rounded border border-amber-400/80 bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-100'
        : s === 'PARTIALLY_FILLED'
          ? 'rounded border border-sky-400/80 bg-sky-500/10 px-1.5 py-0.5 text-[10px] text-sky-100'
          : s === 'CANCELLED' || s === 'CANCELED' || s === 'REJECTED' || s === 'EXPIRED'
            ? 'rounded border border-rose-400/80 bg-rose-500/10 px-1.5 py-0.5 text-[10px] text-rose-100'
            : 'rounded border border-white/20 bg-white/5 px-1.5 py-0.5 text-[10px] text-slate-100';
  return <span className={style}>{s}</span>;
}

interface OrdersPanelProps {
  engineRunning: boolean;
  orders: unknown;
}

export const OrdersPanel: FC<OrdersPanelProps> = ({
  engineRunning,
  orders,
}) => {
  const ord: CachedOrdersShape | null = isRecord(orders) ? (orders as CachedOrdersShape) : null;
  const tracks = Array.isArray(ord?.tracks) ? ord!.tracks : [];
  const lastQueryTs = ord?.last_order_query_ts;

  return (
    <div className="flex h-full w-full flex-col rounded-lg border border-white/10 bg-white/5 p-2 shadow-[0_4px_12px_rgba(0,0,0,0.4)]">
      <div className="mb-1 text-[10px] text-white/50">
        Last order query: {lastQueryTs != null && Number.isFinite(lastQueryTs) ? fmtTs(lastQueryTs) : '-'}
      </div>
      <div className="min-h-0 flex-1 overflow-auto rounded border border-white/10">
        <table className="w-full table-fixed border-collapse text-left">
          <thead>
            <tr className="bg-white/5 text-[10px] text-white/70">
              <th className="w-[8%] px-1.5 py-1">Order</th>
              <th className="w-[12%] px-1.5 py-1">Strategy</th>
              <th className="w-[10%] px-1.5 py-1">Symbol</th>
              <th className="w-[6%] px-1.5 py-1">Side</th>
              <th className="w-[8%] px-1.5 py-1">Type</th>
              <th className="w-[8%] px-1.5 py-1">Status</th>
              <th className="w-[8%] px-1.5 py-1 text-right">Qty</th>
              <th className="w-[8%] px-1.5 py-1 text-right">Filled</th>
              <th className="w-[8%] px-1.5 py-1 text-right">Price</th>
              <th className="w-[8%] px-1.5 py-1 text-right">Avg</th>
              <th className="w-[14%] px-1.5 py-1">Created</th>
              <th className="w-[14%] px-1.5 py-1">Finished</th>
            </tr>
          </thead>
          <tbody>
            {tracks.length ? (
              tracks.map((t) => (
                <tr key={t.order_id} className="border-t border-white/5 text-xs">
                  <td className="px-1.5 py-1 font-mono text-slate-100">{t.order_id}</td>
                  <td className="px-1.5 py-1 font-mono text-slate-100">{t.strategy_name}</td>
                  <td className="px-1.5 py-1 font-mono text-slate-100">{t.symbol}</td>
                  <td className="px-1.5 py-1 font-mono text-slate-100">{t.side}</td>
                  <td className="px-1.5 py-1 font-mono text-slate-100">{t.type || '-'}</td>
                  <td className="px-1.5 py-1">
                    <StatusTag status={t.status || 'UNKNOWN'} />
                  </td>
                  <td className="px-1.5 py-1 text-right font-mono text-slate-100">{t.quantity ?? '-'}</td>
                  <td className="px-1.5 py-1 text-right font-mono text-slate-100">{t.filled_quantity ?? '-'}</td>
                  <td className="px-1.5 py-1 text-right font-mono text-slate-100">{t.price ?? '-'}</td>
                  <td className="px-1.5 py-1 text-right font-mono text-slate-100">{t.filled_avg_price ?? '-'}</td>
                  <td className="px-1.5 py-1 font-mono text-[10px] text-white/70">{fmtTs(t.create_timestamp)}</td>
                  <td className="px-1.5 py-1 font-mono text-[10px] text-white/70">{fmtTs(t.finish_timestamp)}</td>
                </tr>
              ))
            ) : (
              <tr className="border-t border-white/5">
                <td className="px-1.5 py-2 text-xs text-white/70" colSpan={12}>
                  {!engineRunning ? 'Start the engine to see orders.' : 'No orders in cache.'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};
