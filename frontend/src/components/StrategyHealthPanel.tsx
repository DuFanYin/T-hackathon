import { useCallback, useEffect, useRef, useState, type FC } from 'react';
import { api } from '../lib/api';
import type { Holding, RunningStrategy, StrategiesHealthResponse } from '../lib/types';

/* ================================================================
   Strategy Health — live state from GET /strategies/health (in-memory
   strategies). Holdings from /positions still used for avg_cost / PnL.
   ================================================================ */

const MOM_THRESHOLD_PCT = 3;
/** ~minutes per Maliki strategy step with default timer_trigger=300 @ 1s engine tick */
const MALIKI_STEP_MINUTES = 5;

/** Must match `setInterval` below — shown in UI so operators know exact cadence */
const HEALTH_POLL_INTERVAL_MS = 15_000;
const HEALTH_POLL_INTERVAL_SEC = HEALTH_POLL_INTERVAL_MS / 1000;

interface StrategyHealthBase {
  strategy_name: string;
  kind: string;
  inited: boolean;
  started: boolean;
  error: boolean;
  error_msg: string;
  timer_trigger: number;
  engine_subtick: number;
  engine_subticks_until_fire: number;
}

interface PositionReconciliation {
  ok: boolean;
  issues: Array<{
    type?: string;
    coin?: string;
    symbol?: string;
    quantity?: number;
    detail?: string;
    [key: string]: unknown;
  }>;
  notes?: Array<{ type?: string; detail?: string; symbol?: string; [key: string]: unknown }>;
}

interface MalikiHealth extends StrategyHealthBase {
  kind: 'maliki';
  regime: 'BULL' | 'BEAR' | 'UNKNOWN';
  regime_bullish: boolean;
  btc_last: number;
  btc_ma: number;
  spread_pct: number;
  btc_bar_count: number;
  regime_ma_candles: number;
  warmup_ok: boolean;
  strategy_step_tick: number;
  rebalance_every: number;
  ticks_until_rebalance: number;
  momentum_top: { coin: string; momentum_pct: number; notional_24h: number }[];
  momentum_candidates: number;
  min_momentum_pct: number;
  trail_state: {
    coin: string;
    symbol: string;
    quantity: number;
    mid_price: number;
    peak_price: number;
    entry_price: number;
    current_price: number;
    drawdown_from_peak_pct: number;
    ticks_held: number;
    min_hold_candles: number;
    trailing_stop_pct: number;
  }[];
  held_coins: string[];
  trailing_stop_pct: number;
  min_hold_candles: number;
  lookback_candles: number;
  interval: string;
  top_n: number;
  position_reconciliation?: PositionReconciliation;
}

interface JHPairHealth {
  symbol: string;
  sup_price: number | null;
  hit_count: number;
  active_stop: number | null;
  active_target: number | null;
  pending_order_id: string;
  has_position: boolean;
  quantity: number;
  entry_price: number;
  last_price: number;
  mid_price: number;
}

interface JHHealth extends StrategyHealthBase {
  kind: 'jh';
  pairs: JHPairHealth[];
  interval: string;
  pivot_len: number;
  atr_len: number;
  rr: number;
  position_reconciliation?: PositionReconciliation;
}

function asMalikiHealth(x: unknown): MalikiHealth | null {
  if (!x || typeof x !== 'object') return null;
  const o = x as Record<string, unknown>;
  return o.kind === 'maliki' ? (o as unknown as MalikiHealth) : null;
}

function asJHHealth(x: unknown): JHHealth | null {
  if (!x || typeof x !== 'object') return null;
  const o = x as Record<string, unknown>;
  return o.kind === 'jh' ? (o as unknown as JHHealth) : null;
}

// ── Sub-components ──

const Badge: FC<{ color: 'green' | 'red' | 'yellow' | 'gray' | 'sky'; children: React.ReactNode }> = ({ color, children }) => {
  const cls: Record<string, string> = {
    green: 'border-emerald-400/80 bg-emerald-500/10 text-emerald-100',
    red: 'border-rose-400/80 bg-rose-500/10 text-rose-100',
    yellow: 'border-amber-400/80 bg-amber-500/10 text-amber-100',
    gray: 'border-white/20 bg-white/5 text-white/70',
    sky: 'border-sky-400/70 bg-sky-500/10 text-sky-100',
  };
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${cls[color]}`}>
      {children}
    </span>
  );
};

const Card: FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
  <div className="rounded-lg border border-white/10 bg-white/[0.03] p-3">
    <div className="mb-2 font-mono text-[10px] uppercase tracking-widest text-white/50">{title}</div>
    {children}
  </div>
);

/** Always visible: holdings / pending orders vs strategy internal state */
const StrategyCorrectnessPanel: FC<{
  label: string;
  rec: PositionReconciliation | undefined;
  /** When set, reconciliation was not run (engine has no strategy, snapshot error, etc.) */
  unavailableReason?: string;
}> = ({ label, rec, unavailableReason }) => {
  const issues = rec?.issues ?? [];
  const notes = rec?.notes ?? [];
  const hasRec = rec != null;

  if (unavailableReason) {
    return (
      <div className="mb-3 rounded-lg border border-white/15 bg-white/[0.03] p-3">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <span className="font-mono text-[10px] uppercase tracking-widest text-white/50">Strategy correctness</span>
          <Badge color="gray">N/A</Badge>
          <span className="text-[10px] text-white/40">{label}</span>
        </div>
        <p className="m-0 text-[11px] text-white/55">{unavailableReason}</p>
      </div>
    );
  }

  return (
    <div className="mb-3 rounded-lg border border-white/10 bg-black/35 p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="font-mono text-[10px] uppercase tracking-widest text-white/50">Strategy correctness</span>
        {!hasRec ? (
          <Badge color="yellow">NO DATA</Badge>
        ) : issues.length > 0 ? (
          <Badge color="red">{issues.length} mismatch{issues.length === 1 ? '' : 'es'}</Badge>
        ) : notes.length > 0 ? (
          <Badge color="sky">OK · in-flight</Badge>
        ) : (
          <Badge color="green">OK · in sync</Badge>
        )}
        <span className="text-[10px] text-white/40">{label}</span>
      </div>
      {!hasRec ? (
        <p className="m-0 text-[11px] text-amber-200/90">
          No <span className="font-mono">position_reconciliation</span> in health payload — use a current backend build.
        </p>
      ) : issues.length === 0 && notes.length === 0 ? (
        <p className="m-0 text-[11px] text-emerald-100/85">
          Internal state, engine holdings, and pending orders are consistent for <span className="font-mono">{label}</span>.
        </p>
      ) : null}

      {issues.length > 0 && (
        <div className="mt-2 rounded-md border border-rose-500/45 bg-rose-500/10 px-2.5 py-2 text-[11px]">
          <div className="font-semibold text-rose-100">Expected vs actual — fix or investigate</div>
          <ul className="mt-1 list-inside list-disc space-y-0.5 text-rose-100/90">
            {issues.map((it, i) => (
              <li key={i}>
                <span className="font-mono text-rose-50">{it.type ?? 'issue'}</span>
                {it.symbol ? (
                  <>
                    {' '}
                    <span className="font-mono text-white/80">({it.symbol})</span>
                  </>
                ) : null}
                {it.coin ? (
                  <>
                    {' '}
                    <span className="font-mono text-white/80">{it.coin}</span>
                  </>
                ) : null}
                {it.detail ? <> — {it.detail}</> : null}
              </li>
            ))}
          </ul>
        </div>
      )}
      {notes.length > 0 && (
        <div className="mt-2 rounded-md border border-sky-500/35 bg-sky-500/10 px-2.5 py-2 text-[10px] text-sky-100/90">
          <div className="mb-0.5 font-semibold text-sky-100">In-flight / FYI (not an error)</div>
          <ul className="list-inside list-disc space-y-0.5">
            {notes.map((it, i) => (
              <li key={i}>
                <span className="font-mono">{it.type ?? 'note'}</span>
                {it.symbol ? <> {it.symbol}</> : null}
                {it.detail ? <> — {it.detail}</> : null}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

function formatClock(ts: number): string {
  try {
    return new Date(ts).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return '—';
  }
}

// ── Main component ──

interface StrategyHealthPanelProps {
  running: RunningStrategy[];
  holdings: Record<string, Holding>;
  engineRunning: boolean;
}

export const StrategyHealthPanel: FC<StrategyHealthPanelProps> = ({
  running,
  holdings,
  engineRunning,
}) => {
  const [health, setHealth] = useState<StrategiesHealthResponse | null>(null);
  const [healthErr, setHealthErr] = useState<string | null>(null);
  const [healthFetchedAt, setHealthFetchedAt] = useState<number | null>(null);
  const [refreshBusy, setRefreshBusy] = useState(false);
  const [rebalFlash, setRebalFlash] = useState(false);
  /** Bumps once per second so countdown / progress bar stay live */
  const [, setUiClock] = useState(0);
  const prevMalikiTick = useRef(0);
  const mountedRef = useRef(true);

  useEffect(() => {
    const id = window.setInterval(() => setUiClock(c => c + 1), 1000);
    return () => window.clearInterval(id);
  }, []);

  const pollHealth = useCallback(async () => {
    try {
      const r = await api.strategiesHealth();
      if (!mountedRef.current) return;
      setHealth(r);
      setHealthErr(null);
      setHealthFetchedAt(Date.now());

      const mh = asMalikiHealth(r.strategies.strategy_maliki);
      if (mh && prevMalikiTick.current > 0 && mh.strategy_step_tick > prevMalikiTick.current) {
        const te = mh.rebalance_every;
        const tc = mh.strategy_step_tick;
        if (te > 0 && (tc % te === 0 || tc === 1)) {
          setRebalFlash(true);
          window.setTimeout(() => setRebalFlash(false), 2000);
        }
      }
      if (mh) prevMalikiTick.current = mh.strategy_step_tick;
    } catch (e) {
      if (mountedRef.current) {
        setHealthErr(e instanceof Error ? e.message : 'Failed to fetch /strategies/health');
      }
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    if (engineRunning) void pollHealth();
    const t = window.setInterval(() => {
      if (engineRunning) void pollHealth();
    }, HEALTH_POLL_INTERVAL_MS);
    return () => {
      mountedRef.current = false;
      window.clearInterval(t);
    };
  }, [engineRunning, pollHealth]);

  const handleManualRefresh = () => {
    setRefreshBusy(true);
    void pollHealth().finally(() => setRefreshBusy(false));
  };

  if (!engineRunning) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-white/50">
        Start the engine to see strategy health.
      </div>
    );
  }

  const malikiRunning = running.find(s => s.name === 'strategy_maliki');
  const jhRunning = running.find(s => s.name === 'strategy_JH');

  const malikiHolding = holdings.strategy_maliki;
  const malikiPositions = Object.values(malikiHolding?.positions || {}).filter(p => p.quantity > 0);
  const isFlat = malikiPositions.length === 0;

  const jhHolding = holdings.strategy_JH;
  const jhPositions = Object.entries(jhHolding?.positions || {}).filter(([, p]) => p.quantity > 0);

  const rawMaliki = health?.strategies.strategy_maliki;
  const rawJH = health?.strategies.strategy_JH;
  const mh = asMalikiHealth(rawMaliki);
  const jh = asJHHealth(rawJH);
  const malikiHealthErr =
    rawMaliki && typeof rawMaliki === 'object' && (rawMaliki as { kind?: string }).kind === 'error'
      ? String((rawMaliki as { error_msg?: string }).error_msg || 'health_snapshot failed')
      : null;
  const jhHealthErr =
    rawJH && typeof rawJH === 'object' && (rawJH as { kind?: string }).kind === 'error'
      ? String((rawJH as { error_msg?: string }).error_msg || 'health_snapshot failed')
      : null;

  const trailBySymbol = (sym: string) => mh?.trail_state.find(t => t.symbol === sym);

  const rebalEvery = mh?.rebalance_every ?? 288;
  const stepTick = mh?.strategy_step_tick ?? 0;
  const rebalPct = rebalEvery > 0 ? ((stepTick % rebalEvery) / rebalEvery) * 100 : 0;
  const ticksLeft = mh?.ticks_until_rebalance ?? 0;
  const minsLeft = ticksLeft * MALIKI_STEP_MINUTES;
  const hoursLeft = Math.floor(minsLeft / 60);
  const minsRem = minsLeft % 60;

  const secondsUntilAutoRefresh =
    healthFetchedAt != null
      ? Math.max(0, Math.ceil((healthFetchedAt + HEALTH_POLL_INTERVAL_MS - Date.now()) / 1000))
      : null;
  const fetchElapsedMs =
    healthFetchedAt != null ? Math.min(HEALTH_POLL_INTERVAL_MS, Date.now() - healthFetchedAt) : 0;
  const fetchProgressPct = healthFetchedAt != null ? (fetchElapsedMs / HEALTH_POLL_INTERVAL_MS) * 100 : 0;

  return (
    <div className="flex h-full flex-col gap-3 overflow-auto pr-1">
      <div className="flex flex-col gap-3 rounded-lg border border-white/10 bg-black/30 px-3 py-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-[11px] text-white/55">
            Data: <span className="font-mono text-white/80">GET /strategies/health</span> +{' '}
            <span className="font-mono text-white/80">/positions</span> (PnL / avg cost).{' '}
            <span className="text-white/40">Position/state sync lives under each strategy below.</span>
          </span>
          <button
            type="button"
            disabled={refreshBusy}
            onClick={handleManualRefresh}
            className="inline-flex shrink-0 items-center justify-center gap-1.5 rounded-lg border border-white/20 bg-white/10 px-3 py-1.5 text-xs font-medium text-slate-50 transition hover:border-white/40 hover:bg-white/20 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {refreshBusy ? 'Refreshing…' : 'Refresh now'}
          </button>
        </div>

        <div className="rounded-lg border border-violet-500/30 bg-violet-950/25 px-3 py-2.5">
          <div className="mb-1.5 font-mono text-[10px] uppercase tracking-widest text-violet-200/80">
            Health fetch timing
          </div>
          <div className="grid gap-3 sm:grid-cols-2 sm:items-center">
            <div>
              <div className="text-[11px] leading-relaxed text-white/80">
                <span className="text-white/55">Auto poll every</span>{' '}
                <span className="font-mono font-bold text-white">{HEALTH_POLL_INTERVAL_SEC}s</span>
                <span className="text-white/55"> · next run in </span>
                <span className="font-mono font-bold text-emerald-300">
                  {secondsUntilAutoRefresh != null ? `${secondsUntilAutoRefresh}s` : '—'}
                </span>
              </div>
              <div className="mt-1.5 flex items-center gap-2">
                <div className="h-2 flex-1 overflow-hidden rounded-full bg-black/40 ring-1 ring-violet-500/20">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-violet-500/90 to-fuchsia-400/80 transition-[width] duration-300"
                    style={{ width: `${Math.min(100, fetchProgressPct)}%` }}
                  />
                </div>
                <span className="font-mono text-[10px] tabular-nums text-white/45">
                  {healthFetchedAt != null ? `${Math.round(fetchProgressPct)}%` : ''}
                </span>
              </div>
              <p className="mt-1 m-0 text-[9px] text-white/35">
                Bar fills until the next automatic request; manual refresh resets the timer.
              </p>
            </div>
            <div className="space-y-1 font-mono text-[11px] text-white/70">
              <div>
                <span className="text-white/45">Last successful fetch</span>{' '}
                <span className="text-slate-100">{healthFetchedAt != null ? formatClock(healthFetchedAt) : '—'}</span>
              </div>
              {mh ? (
                <div>
                  <span className="text-white/45">Maliki engine subticks</span>{' '}
                  <span className="text-sky-300/90">
                    {mh.engine_subtick}/{mh.timer_trigger}
                  </span>
                  <span className="text-white/45"> → strategy step ~</span>
                  <span className="text-slate-100">{mh.engine_subticks_until_fire}s</span>
                </div>
              ) : null}
              {refreshBusy ? <div className="text-sky-300">Manual refresh in progress…</div> : null}
            </div>
          </div>
        </div>

        {healthErr ? <p className="m-0 text-[11px] leading-snug text-rose-300/90">{healthErr}</p> : null}
      </div>

      {/* ═══ STRATEGY_MALIKI ═══ */}
      <div className="rounded-lg border border-white/10 bg-white/5 p-3 shadow-[0_4px_12px_rgba(0,0,0,0.4)]">
        <div className="mb-3 flex items-center gap-2">
          <span className="font-mono text-xs font-semibold tracking-wide text-slate-100">STRATEGY_MALIKI</span>
          <span className="text-[10px] text-white/40">Momentum Rotation</span>
          {malikiRunning?.started ? (
            <Badge color="green">Running</Badge>
          ) : (
            <Badge color="gray">Stopped</Badge>
          )}
        </div>

        {malikiRunning?.error ? (
          <div className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-[11px] text-rose-100">
            <span className="font-semibold">strategy_maliki error</span>
            {malikiRunning.error_msg ? `: ${malikiRunning.error_msg}` : ''}
          </div>
        ) : null}

        {!mh && !healthErr ? (
          <p className="text-xs text-white/55">Loading Maliki health…</p>
        ) : !mh ? (
          <div className="space-y-3 text-xs text-white/65">
            <div className="space-y-1">
              <Badge color="gray">NOT IN ENGINE</Badge>
              <p>
                <span className="font-mono">strategy_maliki</span> is not registered on this MainEngine instance (init did not
                add it).
              </p>
            </div>
            <StrategyCorrectnessPanel
              label="strategy_maliki"
              rec={undefined}
              unavailableReason="Strategy not on engine — holdings vs internal-state check does not apply."
            />
          </div>
        ) : malikiHealthErr ? (
          <div className="space-y-3">
            <p className="m-0 text-xs text-rose-300">health_snapshot failed: {malikiHealthErr}</p>
            <StrategyCorrectnessPanel
              label="strategy_maliki"
              rec={undefined}
              unavailableReason={`health_snapshot() failed — cannot evaluate sync until fixed.`}
            />
          </div>
        ) : (
          <>
            {malikiHolding ? (
              <div className="mb-3 grid grid-cols-2 gap-2 rounded-lg border border-white/10 bg-black/25 px-3 py-2 sm:grid-cols-4">
                <div>
                  <div className="text-[9px] uppercase tracking-wider text-white/45">Positions (API)</div>
                  <div className="font-mono text-sm text-slate-100">{malikiPositions.length} open</div>
                </div>
                <div>
                  <div className="text-[9px] uppercase tracking-wider text-white/45">Cost basis</div>
                  <div className="font-mono text-sm tabular-nums text-slate-100">
                    ${malikiHolding.total_cost.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                  </div>
                </div>
                <div>
                  <div className="text-[9px] uppercase tracking-wider text-white/45">Mark value</div>
                  <div className="font-mono text-sm tabular-nums text-slate-100">
                    ${malikiHolding.current_value.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                  </div>
                </div>
                <div>
                  <div className="text-[9px] uppercase tracking-wider text-white/45">Unrealized / Total PnL</div>
                  <div
                    className={`font-mono text-sm tabular-nums ${
                      malikiHolding.unrealized_pnl >= 0 ? 'text-emerald-300' : 'text-rose-300'
                    }`}
                  >
                    {malikiHolding.unrealized_pnl >= 0 ? '+' : ''}
                    {malikiHolding.unrealized_pnl.toFixed(2)} / {malikiHolding.pnl >= 0 ? '+' : ''}
                    {malikiHolding.pnl.toFixed(2)}
                  </div>
                </div>
              </div>
            ) : null}

            <StrategyCorrectnessPanel label="strategy_maliki" rec={mh.position_reconciliation} />

            <div className="mb-2 flex flex-wrap gap-2 font-mono text-[10px] text-white/50">
              <span>
                interval <span className="text-slate-300">{mh.interval}</span>
              </span>
              <span>
                BTC bars <span className="text-slate-300">{mh.btc_bar_count}</span>/{mh.regime_ma_candles}
              </span>
              <span>
                warmup <span className={mh.warmup_ok ? 'text-emerald-400' : 'text-amber-400'}>{mh.warmup_ok ? 'ok' : 'pending'}</span>
              </span>
              <span>
                step tick <span className="text-slate-300">{mh.strategy_step_tick}</span> · rebal every{' '}
                <span className="text-slate-300">{mh.rebalance_every}</span>
              </span>
            </div>

            <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
              <Card title="BTC Regime">
                {!mh.started ? (
                  <div className="space-y-1.5">
                    <Badge color="gray">STRATEGY STOPPED</Badge>
                    <p className="text-xs text-white/65">Start <span className="font-mono">strategy_maliki</span> from Controls.</p>
                  </div>
                ) : mh.regime === 'UNKNOWN' || !mh.warmup_ok ? (
                  <div className="space-y-1.5">
                    <span className="inline-flex items-center gap-2 rounded-lg border border-amber-400/60 bg-amber-500/15 px-4 py-1.5 text-lg font-bold text-amber-200">
                      WARMING UP
                    </span>
                    <p className="text-xs text-white/70">
                      Status: Regime MA needs {mh.regime_ma_candles} BTC bars on {mh.interval} — have {mh.btc_bar_count}.
                    </p>
                  </div>
                ) : (
                  <div className="space-y-1.5">
                    <div>
                      {mh.regime_bullish ? (
                        <span className="inline-flex items-center gap-2 rounded-lg border border-emerald-400/60 bg-emerald-500/15 px-4 py-1.5 text-lg font-bold text-emerald-300">
                          BULL
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-2 rounded-lg border border-rose-400/60 bg-rose-500/15 px-4 py-1.5 text-lg font-bold text-rose-300">
                          BEAR
                        </span>
                      )}
                    </div>
                    <div className="font-mono text-xs text-white/70">
                      BTC <span className="text-slate-100">${mh.btc_last.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
                      {' | '}MA <span className="text-slate-100">${mh.btc_ma.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
                      {' | '}
                      <span className={mh.regime_bullish ? 'text-emerald-400' : 'text-rose-400'}>
                        {mh.spread_pct >= 0 ? '+' : ''}
                        {mh.spread_pct.toFixed(1)}% vs MA
                      </span>
                    </div>
                    {!mh.regime_bullish && (
                      <div className="mt-1 rounded border border-rose-400/30 bg-rose-500/5 px-2 py-1 text-[11px] text-rose-200">
                        Status: <span className="font-medium text-rose-100">CASH</span> — bear regime (BTC below MA).
                      </div>
                    )}
                  </div>
                )}
              </Card>

              <Card title={`Momentum (candidates ≥ ${mh.min_momentum_pct}%)`}>
                {!mh.started ? (
                  <div className="space-y-1.5">
                    <Badge color="gray">STRATEGY STOPPED</Badge>
                  </div>
                ) : mh.momentum_top.length > 0 ? (
                  <div className="max-h-40 overflow-auto">
                    <table className="w-full border-collapse text-left">
                      <thead>
                        <tr className="text-[10px] text-white/60">
                          <th className="px-1 py-0.5">#</th>
                          <th className="px-1 py-0.5">Coin</th>
                          <th className="px-1 py-0.5 text-right">Mom%</th>
                          <th className="px-1 py-0.5 text-right">{`>${MOM_THRESHOLD_PCT}%?`}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {mh.momentum_top.slice(0, 10).map((e, i) => (
                          <tr
                            key={e.coin}
                            className={`border-t border-white/5 text-xs ${i === 0 ? 'bg-emerald-500/10' : ''}`}
                          >
                            <td className="px-1 py-0.5 text-white/50">{i + 1}</td>
                            <td className={`px-1 py-0.5 font-mono ${i === 0 ? 'font-bold text-emerald-200' : 'text-slate-100'}`}>
                              {e.coin}
                            </td>
                            <td
                              className={`px-1 py-0.5 text-right tabular-nums ${
                                e.momentum_pct >= MOM_THRESHOLD_PCT ? 'text-emerald-400' : 'text-white/70'
                              }`}
                            >
                              {e.momentum_pct >= 0 ? '+' : ''}
                              {e.momentum_pct.toFixed(1)}%
                            </td>
                            <td className="px-1 py-0.5 text-right">
                              {e.momentum_pct >= MOM_THRESHOLD_PCT
                                ? <span className="text-emerald-400">Yes</span>
                                : <span className="text-white/40">No</span>}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <div className="mt-1 text-[10px] text-white/40">
                      {mh.momentum_candidates} candidate(s) after liquidity + momentum filter · top_n={mh.top_n}
                    </div>
                  </div>
                ) : (
                  <div className="space-y-1.5">
                    <Badge color="yellow">NO CANDIDATES</Badge>
                    <p className="text-xs text-white/65">
                      Status: No asset passed min momentum ({mh.min_momentum_pct}%) and notional filter — strategy stays in
                      cash when bull regime.
                    </p>
                  </div>
                )}
              </Card>

              <Card title="Rebalance countdown">
                {!mh.started ? (
                  <div className="space-y-1.5">
                    <Badge color="gray">STRATEGY STOPPED</Badge>
                  </div>
                ) : (
                  <div className="space-y-1.5">
                    <div className="flex items-center gap-2">
                      <Badge color="green">TICKING</Badge>
                      <span className="font-mono text-[10px] text-white/45">
                        step {mh.strategy_step_tick} / every {mh.rebalance_every} steps
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <div className="flex-1">
                        <div className={`h-2 overflow-hidden rounded-full bg-white/10 transition-all ${rebalFlash ? 'ring-2 ring-emerald-400/50' : ''}`}>
                          <div
                            className="h-full rounded-full bg-emerald-500/60 transition-all duration-1000"
                            style={{ width: `${rebalPct}%` }}
                          />
                        </div>
                      </div>
                      <span className="font-mono text-xs tabular-nums text-white/70">
                        {stepTick % rebalEvery}/{rebalEvery}
                      </span>
                    </div>
                    <div className="font-mono text-xs text-white/60">
                      Next rebalance in{' '}
                      <span className="text-slate-100">
                        {hoursLeft}h {minsRem}m
                      </span>
                      <span className="ml-2 text-white/40">(~{ticksLeft} steps × ~{MALIKI_STEP_MINUTES}m)</span>
                    </div>
                    {rebalFlash && (
                      <div className="animate-pulse rounded border border-emerald-400/40 bg-emerald-500/10 px-2 py-0.5 text-[10px] text-emerald-200">
                        Rebalance step
                      </div>
                    )}
                  </div>
                )}
              </Card>

              <Card title="Position status">
                {isFlat ? (
                  <div className="space-y-1.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge color="gray">FLAT (API)</Badge>
                      {!mh.started ? <Badge color="gray">STOPPED</Badge> : null}
                    </div>
                    <p className="text-xs leading-relaxed text-white/65">
                      <span className="font-medium text-white/80">Why flat:</span>{' '}
                      {!mh.started
                        ? 'Strategy not started.'
                        : mh.regime === 'UNKNOWN' || !mh.warmup_ok
                          ? 'Still warming up (BTC MA bars).'
                          : !mh.regime_bullish
                            ? 'BEAR regime — cash.'
                            : mh.momentum_candidates === 0
                              ? 'No momentum candidates.'
                              : 'Bull + candidates but no fill yet, or between rotation — see engine logs.'}
                    </p>
                  </div>
                ) : (
                  malikiPositions.map((p) => {
                    const tr = trailBySymbol(p.symbol);
                    const pnl = p.mid_price && p.avg_cost ? ((p.mid_price - p.avg_cost) / p.avg_cost) * 100 : 0;
                    const peak = tr?.peak_price ?? 0;
                    const trailStop = peak > 0 ? peak * (1 - (tr?.trailing_stop_pct ?? mh.trailing_stop_pct) / 100) : 0;
                    const distToStop =
                      p.mid_price && trailStop > 0 ? ((p.mid_price - trailStop) / p.mid_price) * 100 : 0;
                    const minHold = tr?.min_hold_candles ?? mh.min_hold_candles;
                    const ticksHeld = tr?.ticks_held ?? 0;
                    const canExit = ticksHeld >= minHold;
                    const ticksToExit = Math.max(0, minHold - ticksHeld);
                    const hoursToExit = Math.floor((ticksToExit * MALIKI_STEP_MINUTES) / 60);
                    const minsToExit = (ticksToExit * MALIKI_STEP_MINUTES) % 60;

                    return (
                      <div key={p.symbol} className="space-y-1">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-sm font-bold text-slate-100">{p.symbol.replace('USDT', '')}</span>
                          <span className={`font-mono text-sm font-bold tabular-nums ${pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                            {pnl >= 0 ? '+' : ''}
                            {pnl.toFixed(2)}%
                          </span>
                        </div>
                        <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 font-mono text-[11px]">
                          <span className="text-white/50">Entry</span>
                          <span className="text-right tabular-nums text-slate-100">${p.avg_cost.toFixed(2)}</span>
                          <span className="text-white/50">Current</span>
                          <span className="text-right tabular-nums text-slate-100">${p.mid_price.toFixed(2)}</span>
                          {tr && peak > 0 && (
                            <>
                              <span className="text-white/50">Peak / DD</span>
                              <span className="text-right tabular-nums text-slate-100">
                                ${peak.toFixed(2)} / {tr.drawdown_from_peak_pct.toFixed(2)}%
                              </span>
                              <span className="text-white/50">Trail stop (~)</span>
                              <span className="text-right tabular-nums text-slate-100">${trailStop.toFixed(2)}</span>
                              <span className="text-white/50">Dist to stop</span>
                              <span
                                className={`text-right tabular-nums ${distToStop > 4 ? 'text-emerald-400' : distToStop > 2 ? 'text-amber-400' : 'text-rose-400'}`}
                              >
                                {distToStop.toFixed(1)}%
                              </span>
                            </>
                          )}
                          <span className="text-white/50">Qty</span>
                          <span className="text-right tabular-nums text-slate-100">{p.quantity}</span>
                        </div>
                        <div className="mt-1 text-[10px]">
                          {canExit
                            ? <span className="text-emerald-400">Min hold satisfied</span>
                            : <span className="text-amber-300">Min hold in ~{hoursToExit}h {minsToExit}m</span>}
                        </div>
                      </div>
                    );
                  })
                )}
              </Card>
            </div>
          </>
        )}
      </div>

      {/* ═══ STRATEGY_JH ═══ */}
      <div className="rounded-lg border border-white/10 bg-white/5 p-3 shadow-[0_4px_12px_rgba(0,0,0,0.4)]">
        <div className="mb-3 flex items-center gap-2">
          <span className="font-mono text-xs font-semibold tracking-wide text-slate-100">STRATEGY_JH</span>
          <span className="text-[10px] text-white/40">Support Bounce</span>
          {jhRunning?.started ? (
            <Badge color="green">Running</Badge>
          ) : (
            <Badge color="gray">Stopped</Badge>
          )}
        </div>

        {jhRunning?.error ? (
          <div className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-[11px] text-rose-100">
            <span className="font-semibold">strategy_JH error</span>
            {jhRunning.error_msg ? `: ${jhRunning.error_msg}` : ''}
          </div>
        ) : null}

        {!jh && !healthErr ? (
          <p className="text-xs text-white/55">Loading JH health…</p>
        ) : !jh ? (
          <div className="space-y-3 text-xs text-white/65">
            <div className="space-y-1">
              <Badge color="gray">NOT IN ENGINE</Badge>
              <p>
                <span className="font-mono">strategy_JH</span> is not registered on this MainEngine instance.
              </p>
            </div>
            <StrategyCorrectnessPanel
              label="strategy_JH"
              rec={undefined}
              unavailableReason="Strategy not on engine — holdings vs internal-state check does not apply."
            />
          </div>
        ) : jhHealthErr ? (
          <div className="space-y-3">
            <p className="m-0 text-xs text-rose-300">health_snapshot failed: {jhHealthErr}</p>
            <StrategyCorrectnessPanel
              label="strategy_JH"
              rec={undefined}
              unavailableReason={`health_snapshot() failed — cannot evaluate sync until fixed.`}
            />
          </div>
        ) : (
          <>
            <StrategyCorrectnessPanel label="strategy_JH" rec={jh.position_reconciliation} />

            <div className="mb-2 flex flex-wrap gap-2 font-mono text-[10px] text-white/50">
              <span>
                interval <span className="text-slate-300">{jh.interval}</span>
              </span>
              <span>
                pivot/atr/rr <span className="text-slate-300">{jh.pivot_len}</span>/
                <span className="text-slate-300">{jh.atr_len}</span>/
                <span className="text-slate-300">{jh.rr}</span>
              </span>
            </div>

            <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1 rounded-lg border border-white/10 bg-black/25 px-3 py-2 font-mono text-[10px] text-white/55">
              <span>
                Open positions (API): <span className="text-slate-200">{jhPositions.length}</span>
              </span>
              <span>
                Realized PnL:{' '}
                <span className={jhHolding && jhHolding.realized_pnl >= 0 ? 'text-emerald-300' : 'text-rose-300'}>
                  {jhHolding ? `${jhHolding.realized_pnl >= 0 ? '+' : ''}${jhHolding.realized_pnl.toFixed(2)}` : '—'}
                </span>
              </span>
              <span>
                Unrealized / Total:{' '}
                <span className="text-slate-200">
                  {jhHolding
                    ? `${jhHolding.unrealized_pnl >= 0 ? '+' : ''}${jhHolding.unrealized_pnl.toFixed(2)} / ${
                        jhHolding.pnl >= 0 ? '+' : ''
                      }${jhHolding.pnl.toFixed(2)}`
                    : '—'}
                </span>
              </span>
            </div>

            <Card title="Pair scanner (live state)">
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {jh.pairs.map((st) => {
                  const hasPos = st.has_position;
                  const staged = st.active_stop != null && st.active_target != null;
                  const pending = Boolean(st.pending_order_id);
                  const statusColor =
                    hasPos || pending ? 'green' : st.hit_count >= 2 && staged ? 'yellow' : st.hit_count >= 1 ? 'yellow' : 'red';
                  const statusDot =
                    statusColor === 'green' ? 'bg-emerald-400' : statusColor === 'yellow' ? 'bg-amber-400' : 'bg-white/30';
                  const borderCls =
                    statusColor === 'green'
                      ? 'border-emerald-400/30'
                      : statusColor === 'yellow'
                        ? 'border-amber-400/30'
                        : 'border-white/10';

                  const jhPos = jhPositions.find(([s]) => s === st.symbol);

                  return (
                    <div key={st.symbol} className={`rounded-lg border ${borderCls} bg-black/30 p-2`}>
                      <div className="mb-1 flex items-center justify-between">
                        <span className="font-mono text-xs font-bold text-slate-100">
                          {st.symbol.replace('USDT', '')}
                        </span>
                        <span className={`h-2 w-2 rounded-full ${statusDot}`} />
                      </div>

                      <div className="space-y-0.5 font-mono text-[10px]">
                        {st.last_price > 0 ? (
                          <div className="text-white/60">
                            Last <span className="text-slate-100">${st.last_price.toFixed(st.last_price < 0.01 ? 8 : 4)}</span>
                          </div>
                        ) : null}

                        {st.sup_price != null ? (
                          <div className="text-white/60">
                            Support <span className="text-amber-300">${st.sup_price.toFixed(st.sup_price < 0.01 ? 8 : 4)}</span>
                          </div>
                        ) : (
                          <div className="text-white/30">No support</div>
                        )}

                        <div className="text-white/60">
                          Hits{' '}
                          <span
                            className={
                              st.hit_count === 0 ? 'text-white/30' : st.hit_count === 1 ? 'text-amber-300' : 'text-emerald-300'
                            }
                          >
                            H{st.hit_count}
                          </span>
                        </div>

                        {pending && <div className="text-sky-300">Pending order</div>}
                        {st.hit_count >= 2 && staged && !hasPos && <div className="text-amber-200">Staged stop/target</div>}

                        {jhPos && (
                          <div className="mt-1 space-y-0.5 border-t border-white/10 pt-1">
                            <div className="text-emerald-300">IN TRADE</div>
                            <div className="text-white/60">
                              Entry <span className="text-slate-100">{jhPos[1].avg_cost.toFixed(4)}</span>
                            </div>
                            {st.active_stop != null && (
                              <div className="text-white/60">
                                Stop <span className="text-rose-300">{st.active_stop.toFixed(4)}</span>
                              </div>
                            )}
                            {st.active_target != null && (
                              <div className="text-white/60">
                                Target <span className="text-emerald-300">{st.active_target.toFixed(4)}</span>
                              </div>
                            )}
                            {st.active_stop != null && st.active_target != null && jhPos[1].mid_price > 0 && (
                              <div className="mt-0.5">
                                <div className="relative h-1.5 rounded-full bg-white/10">
                                  {(() => {
                                    const range = st.active_target - st.active_stop;
                                    const pos = range > 0 ? ((jhPos[1].mid_price - st.active_stop) / range) * 100 : 50;
                                    const clamped = Math.max(0, Math.min(100, pos));
                                    return (
                                      <div
                                        className="absolute top-0 h-full w-1.5 rounded-full bg-sky-400"
                                        style={{ left: `calc(${clamped}% - 3px)` }}
                                      />
                                    );
                                  })()}
                                  <div className="absolute left-0 top-0 h-full w-px bg-rose-400" />
                                  <div className="absolute right-0 top-0 h-full w-px bg-emerald-400" />
                                </div>
                                <div className="mt-0.5 flex justify-between text-[9px]">
                                  <span className="text-rose-400">Stop</span>
                                  <span
                                    className={`font-bold ${jhPos[1].mid_price >= jhPos[1].avg_cost ? 'text-emerald-400' : 'text-rose-400'}`}
                                  >
                                    {(((jhPos[1].mid_price - jhPos[1].avg_cost) / jhPos[1].avg_cost) * 100).toFixed(1)}%
                                  </span>
                                  <span className="text-emerald-400">Target</span>
                                </div>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </Card>
          </>
        )}
      </div>
    </div>
  );
};
