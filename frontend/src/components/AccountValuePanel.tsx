import type { FC } from 'react';

type WalletEntry = { Free?: number; Lock?: number };
type BalanceShape = {
  Success?: boolean;
  ErrMsg?: string;
  Wallet?: Record<string, WalletEntry>;
  SpotWallet?: Record<string, WalletEntry>;
};
function isRecord(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === 'object' && !Array.isArray(v);
}

type PnlData = { equity: number; init_balance: number; pnl: number; pnl_pct: number };

interface AccountValuePanelProps {
  engineRunning: boolean;
  err: string;
  balance: unknown;
  pnl?: PnlData | null;
}

export const AccountValuePanel: FC<AccountValuePanelProps> = ({
  engineRunning,
  err,
  balance,
  pnl,
}) => {
  const bal: BalanceShape | null = isRecord(balance) ? (balance as BalanceShape) : null;

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

  const pnlColor = pnl && pnl.pnl >= 0 ? 'text-emerald-400' : pnl && pnl.pnl < 0 ? 'text-rose-400' : 'text-white/70';

  return (
    <div className="flex h-full w-full flex-col rounded-lg border border-white/10 bg-white/5 p-2 shadow-[0_4px_12px_rgba(0,0,0,0.4)]">
      {err && <div className="mb-1 font-mono text-[10px] text-rose-300">{err}</div>}
      {pnl && (
        <div className="mb-1.5 rounded border border-white/10 bg-black/40 p-2">
          <div className="mb-1 font-mono text-[10px] uppercase tracking-wide text-white/60">PnL</div>
          <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs font-mono">
            <span className="text-white/70">Equity: <span className="text-slate-100">{pnl.equity.toFixed(2)}</span></span>
            <span className="text-white/70">Init: <span className="text-slate-100">{pnl.init_balance.toFixed(2)}</span></span>
            <span className={pnlColor}>PnL: {pnl.pnl >= 0 ? '+' : ''}{pnl.pnl.toFixed(2)}</span>
            <span className={pnlColor}>({pnl.pnl_pct >= 0 ? '+' : ''}{pnl.pnl_pct.toFixed(2)}%)</span>
          </div>
        </div>
      )}
      <div className="overflow-auto">
        <div className="rounded border border-white/10 bg-black/40 p-2">
          <div className="mb-1 font-mono text-[10px] uppercase tracking-wide text-white/60">Balance</div>
          {bal && walletRows.length ? (
            <div className="overflow-auto rounded border border-white/10 max-h-24">
              <table className="w-full table-fixed border-collapse text-left">
                <thead>
                  <tr className="bg-white/5 text-[10px] text-white/70">
                    <th className="w-[30%] px-1.5 py-1">Asset</th>
                    <th className="w-[23%] px-1.5 py-1 text-right">Free</th>
                    <th className="w-[23%] px-1.5 py-1 text-right">Lock</th>
                    <th className="w-[24%] px-1.5 py-1 text-right">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {walletRows.map((r) => (
                    <tr key={r.asset} className="border-t border-white/5 text-xs">
                      <td className="px-1.5 py-1 font-mono text-slate-100">{r.asset}</td>
                      <td className="px-1.5 py-1 text-right font-mono text-slate-100">{r.free}</td>
                      <td className="px-1.5 py-1 text-right font-mono text-slate-100">{r.lock}</td>
                      <td className="px-1.5 py-1 text-right font-mono text-slate-100">{r.total}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-xs text-white/70">
              {!engineRunning ? 'Start the engine.' : 'Waiting for balance…'}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
