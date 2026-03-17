import type { FC } from 'react';

type WalletEntry = { Free?: number; Lock?: number };
type BalanceShape = {
  Success?: boolean;
  ErrMsg?: string;
  Wallet?: Record<string, WalletEntry>;
  SpotWallet?: Record<string, WalletEntry>;
};
type PendingCountShape = {
  Success?: boolean;
  ErrMsg?: string;
  TotalPending?: number;
  OrderPairs?: Record<string, number>;
};
type CachedOrdersShape = {
  pending_by_strategy?: Record<string, string[]>;
  tracks?: Array<{
    order_id: string;
    strategy_name: string;
    symbol: string;
    side: string;
    last_status: string;
    last_filled_qty: number;
  }>;
  cached_balance_ts?: number | null;
  cached_pending_count_ts?: number | null;
};

function isRecord(v: unknown): v is Record<string, any> {
  return !!v && typeof v === 'object' && !Array.isArray(v);
}

function fmtTs(ts: number | null | undefined): string {
  if (!ts || !Number.isFinite(ts)) return '';
  try {
    return new Date(ts * 1000).toLocaleString();
  } catch {
    return '';
  }
}

interface AccountPanelProps {
  isAuthed: boolean;
  engineRunning: boolean;
  err: string;
  balance: unknown;
  pendingCount: unknown;
  orders: unknown;
}

export const AccountPanel: FC<AccountPanelProps> = ({
  isAuthed,
  engineRunning,
  err,
  balance,
  pendingCount,
  orders,
}) => {
  const bal: BalanceShape | null = isRecord(balance) ? (balance as BalanceShape) : null;
  const pc: PendingCountShape | null = isRecord(pendingCount) ? (pendingCount as PendingCountShape) : null;
  const ord: CachedOrdersShape | null = isRecord(orders) ? (orders as CachedOrdersShape) : null;

  const wallet = ((bal?.Wallet && isRecord(bal.Wallet) ? bal.Wallet : null) ??
    (bal?.SpotWallet && isRecord(bal.SpotWallet) ? bal.SpotWallet : null)) as
    | BalanceShape['Wallet']
    | BalanceShape['SpotWallet']
    | null;
  const walletRows =
    wallet
      ? Object.entries(wallet)
          .map(([asset, v]) => {
            const free = Number(v?.Free ?? 0);
            const lock = Number(v?.Lock ?? 0);
            return { asset, free, lock, total: free + lock };
          })
          .sort((a, b) => b.total - a.total)
      : [];

  const orderPairs = (pc?.OrderPairs && isRecord(pc.OrderPairs) ? pc.OrderPairs : null) as PendingCountShape['OrderPairs'] | null;
  const pairRows =
    orderPairs ? Object.entries(orderPairs).sort((a, b) => (b[1] ?? 0) - (a[1] ?? 0)) : [];

  const tracks = Array.isArray(ord?.tracks) ? ord!.tracks : [];
  const pendingByStrategy = (ord?.pending_by_strategy && isRecord(ord.pending_by_strategy) ? ord.pending_by_strategy : null) as
    | Record<string, string[]>
    | null;

  const balUpdated = fmtTs(ord?.cached_balance_ts);
  const pendingUpdated = fmtTs(ord?.cached_pending_count_ts);

  const pendingNone =
    (typeof pc?.TotalPending === 'number' && pc.TotalPending === 0) &&
    (String(pc?.ErrMsg || '').toLowerCase().includes('no pending order'));


  return (
    <div className="flex h-full w-full flex-col rounded-xl border border-white/10 bg-white/5 p-4 shadow-[0_10px_30px_rgba(0,0,0,0.5)]">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {isAuthed && (balUpdated || pendingUpdated) ? (
          <div className="text-[11px] text-white/50">
            {balUpdated ? <span>Balance updated: <span className="font-mono">{balUpdated}</span></span> : null}
            {balUpdated && pendingUpdated ? <span className="mx-2">•</span> : null}
            {pendingUpdated ? <span>Pending updated: <span className="font-mono">{pendingUpdated}</span></span> : null}
          </div>
        ) : null}
        {err && <div className="ml-auto font-mono text-[11px] text-rose-300">{err}</div>}
      </div>

      <div className="grid grid-cols-1 gap-3 overflow-auto md:grid-cols-3">
        <div className="rounded-lg border border-white/10 bg-black/40 p-3">
          <div className="mb-2 font-mono text-[11px] uppercase tracking-wide text-white/60">
            Balance
          </div>
          {bal ? (
            <>
              {typeof bal.Success === 'boolean' && (
                <div className="mb-2 text-xs text-white/70">
                  {bal.Success ? (
                    <span className="text-emerald-200">Success</span>
                  ) : (
                    <span className="text-rose-200">Failed</span>
                  )}
                  {bal.ErrMsg ? <span className="ml-2 font-mono text-[11px] text-white/60">{bal.ErrMsg}</span> : null}
                </div>
              )}
              {walletRows.length ? (
                <div className="overflow-auto rounded border border-white/10">
                  <table className="w-full table-fixed border-collapse text-left">
                    <thead>
                      <tr className="bg-white/5 text-[11px] text-white/70">
                        <th className="w-[30%] px-2 py-1.5">Asset</th>
                        <th className="w-[23%] px-2 py-1.5 text-right">Free</th>
                        <th className="w-[23%] px-2 py-1.5 text-right">Lock</th>
                        <th className="w-[24%] px-2 py-1.5 text-right">Total</th>
                      </tr>
                    </thead>
                    <tbody>
                      {walletRows.map((r) => (
                        <tr key={r.asset} className="border-t border-white/5 text-[12px]">
                          <td className="px-2 py-1.5 font-mono text-slate-100">{r.asset}</td>
                          <td className="px-2 py-1.5 text-right font-mono text-slate-100">{r.free}</td>
                          <td className="px-2 py-1.5 text-right font-mono text-slate-100">{r.lock}</td>
                          <td className="px-2 py-1.5 text-right font-mono text-slate-100">{r.total}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="text-xs text-white/70">
                  {!engineRunning
                    ? 'Start the engine to see your balance.'
                    : balUpdated
                      ? 'No balance details available.'
                      : 'Waiting for balance…'}
                </div>
              )}
            </>
          ) : (
            <div className="text-xs text-white/70">
              {!engineRunning
                ? 'Start the engine to see your balance.'
                : balUpdated
                  ? 'No balance details available.'
                  : 'Waiting for balance…'}
            </div>
          )}
        </div>

        <div className="rounded-lg border border-white/10 bg-black/40 p-3">
          <div className="mb-2 font-mono text-[11px] uppercase tracking-wide text-white/60">
            Pending count
          </div>
          {pc ? (
            <>
              {typeof pc.TotalPending === 'number' && (
                <div className="mb-2 text-sm text-slate-100">
                  Total pending: <span className="font-mono">{pc.TotalPending}</span>
                </div>
              )}
              {typeof pc.Success === 'boolean' && !pendingNone && (
                <div className="mb-2 text-xs text-white/70">
                  {pc.Success ? (
                    <span className="text-emerald-200">Success</span>
                  ) : (
                    <span className="text-rose-200">Failed</span>
                  )}
                  {pc.ErrMsg ? <span className="ml-2 font-mono text-[11px] text-white/60">{pc.ErrMsg}</span> : null}
                </div>
              )}
              {pairRows.length ? (
                <div className="overflow-auto rounded border border-white/10">
                  <table className="w-full table-fixed border-collapse text-left">
                    <thead>
                      <tr className="bg-white/5 text-[11px] text-white/70">
                        <th className="w-[70%] px-2 py-1.5">Pair</th>
                        <th className="w-[30%] px-2 py-1.5 text-right">Count</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pairRows.map(([pair, cnt]) => (
                        <tr key={pair} className="border-t border-white/5 text-[12px]">
                          <td className="px-2 py-1.5 font-mono text-slate-100">{pair}</td>
                          <td className="px-2 py-1.5 text-right font-mono text-slate-100">{cnt}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="text-xs text-white/70">
                  {!engineRunning
                    ? 'Start the engine to see pending orders.'
                    : pendingNone
                      ? 'No pending orders.'
                      : pendingUpdated
                        ? 'No pending details available.'
                        : 'Waiting for pending orders…'}
                </div>
              )}
            </>
          ) : (
            <div className="text-xs text-white/70">
              {!engineRunning
                ? 'Start the engine to see pending orders.'
                : pendingUpdated
                  ? 'No pending details available.'
                  : 'Waiting for pending orders…'}
            </div>
          )}
        </div>

        <div className="rounded-lg border border-white/10 bg-black/40 p-3 md:col-span-3">
          <div className="mb-2 font-mono text-[11px] uppercase tracking-wide text-white/60">
            Orders
          </div>
          {pendingByStrategy && Object.keys(pendingByStrategy).length ? (
            <div className="mb-3 rounded border border-white/10 bg-white/5 p-2">
              <div className="mb-1 text-[11px] text-white/70">Pending order ids by strategy</div>
              <div className="flex flex-wrap gap-2">
                {Object.entries(pendingByStrategy).map(([s, ids]) => (
                  <div key={s} className="rounded border border-white/10 bg-black/30 px-2 py-1">
                    <div className="font-mono text-[11px] text-slate-100">{s}</div>
                    <div className="font-mono text-[10px] text-white/60">{(ids || []).join(', ') || '-'}</div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {tracks.length ? (
            <div className="overflow-auto rounded border border-white/10">
              <table className="w-full table-fixed border-collapse text-left">
                <thead>
                  <tr className="bg-white/5 text-[11px] text-white/70">
                    <th className="w-[16%] px-2 py-1.5">Order ID</th>
                    <th className="w-[16%] px-2 py-1.5">Strategy</th>
                    <th className="w-[18%] px-2 py-1.5">Symbol</th>
                    <th className="w-[10%] px-2 py-1.5">Side</th>
                    <th className="w-[20%] px-2 py-1.5">Status</th>
                    <th className="w-[20%] px-2 py-1.5 text-right">Filled qty</th>
                  </tr>
                </thead>
                <tbody>
                  {tracks.map((t) => (
                    <tr key={t.order_id} className="border-t border-white/5 text-[12px]">
                      <td className="px-2 py-1.5 font-mono text-slate-100">{t.order_id}</td>
                      <td className="px-2 py-1.5 font-mono text-slate-100">{t.strategy_name}</td>
                      <td className="px-2 py-1.5 font-mono text-slate-100">{t.symbol}</td>
                      <td className="px-2 py-1.5 font-mono text-slate-100">{t.side}</td>
                      <td className="px-2 py-1.5 font-mono text-slate-100">{t.last_status || 'UNKNOWN'}</td>
                      <td className="px-2 py-1.5 text-right font-mono text-slate-100">{t.last_filled_qty}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-xs text-white/70">
              {!engineRunning ? 'Start the engine to see orders.' : 'No orders yet.'}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

