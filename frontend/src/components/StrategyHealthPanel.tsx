import { useEffect, useState, useRef, type FC } from 'react';
import { api } from '../lib/api';
import type { Holding, RunningStrategy } from '../lib/types';

/* ================================================================
   Strategy Health Panel — parse strategy logs + API data to show
   a "is the bot working?" view even when no trades happen.
   ================================================================ */

// ── Parsed state types ──

interface RegimeState {
  bullish: boolean;
  btcPrice: number;
  btcMa: number;
  spreadPct: number;
}

interface MomentumEntry {
  coin: string;
  momentumPct: number;
}

interface MalikiPositionState {
  coin: string;
  entryPrice: number;
  currentPrice: number;
  peakPrice: number;
  trailPct: number;
  ticksHeld: number;
  minHold: number;
}

interface RebalanceState {
  tickCount: number;
  rebalEvery: number;
}

interface JHPairState {
  symbol: string;
  supPrice: number | null;
  hitCount: number;
  lastSignal: string | null;
  hasPosition: boolean;
  entryPrice: number;
  stop: number;
  target: number;
  currentPrice: number;
}

// ── Log line parsers ──

function parseRegime(lines: string[]): RegimeState | null {
  for (let i = lines.length - 1; i >= 0; i--) {
    const l = lines[i];
    if (!l.includes('REBALANCE') || !l.includes('regime=')) continue;
    const bull = l.includes("regime='BULL'") || l.includes('regime=BULL');
    const bear = l.includes("regime='BEAR'") || l.includes('regime=BEAR');
    if (!bull && !bear) continue;

    const btcM = l.match(/BTC_last=([\d.]+)/);
    const maM = l.match(/MA\(\d+\)=([\d.]+)/);
    const spreadM = l.match(/spread=([+-]?[\d.]+)/);

    return {
      bullish: bull,
      btcPrice: btcM ? parseFloat(btcM[1]) : 0,
      btcMa: maM ? parseFloat(maM[1]) : 0,
      spreadPct: spreadM && maM ? (parseFloat(spreadM[1]) / parseFloat(maM[1])) * 100 : 0,
    };
  }
  return null;
}

function parseMomentumRankings(lines: string[]): MomentumEntry[] {
  for (let i = lines.length - 1; i >= 0; i--) {
    const l = lines[i];
    if (!l.includes('top movers:')) continue;
    const after = l.split('top movers:')[1] || '';
    const entries: MomentumEntry[] = [];
    const re = /(\w+)\(([+-]?[\d.]+)%/g;
    let m;
    while ((m = re.exec(after)) !== null) {
      entries.push({ coin: m[1], momentumPct: parseFloat(m[2]) });
    }
    return entries;
  }
  return [];
}

function parseRebalance(lines: string[]): RebalanceState | null {
  for (let i = lines.length - 1; i >= 0; i--) {
    const l = lines[i];
    if (!l.includes('[strategy_maliki] TIMER')) continue;
    const tickM = l.match(/tick=(\d+)/);
    const rebalM = l.match(/every (\d+) ticks/);
    if (tickM && rebalM) {
      return { tickCount: parseInt(tickM[1]), rebalEvery: parseInt(rebalM[1]) };
    }
  }
  return null;
}

function parseMalikiTrail(lines: string[]): MalikiPositionState | null {
  for (let i = lines.length - 1; i >= 0; i--) {
    const l = lines[i];
    if (!l.includes('[strategy_maliki] TRAIL') || !l.includes('price=')) continue;
    const coinM = l.match(/TRAIL \| (\w+) \|/);
    const priceM = l.match(/price=([\d.]+)/);
    const peakM = l.match(/peak=([\d.]+)/);
    const ddM = l.match(/dd=([\d.]+)%/);
    const heldM = l.match(/ticks_held=(\d+)/);
    const minM = l.match(/\/(\d+)/);
    if (coinM && priceM && peakM) {
      return {
        coin: coinM[1],
        entryPrice: 0,
        currentPrice: parseFloat(priceM[1]),
        peakPrice: parseFloat(peakM[1]),
        trailPct: ddM ? parseFloat(ddM[1]) : 0,
        ticksHeld: heldM ? parseInt(heldM[1]) : 0,
        minHold: minM ? parseInt(minM[1]) : 288,
      };
    }
  }
  return null;
}

function parseJHPairStates(lines: string[]): Record<string, Partial<JHPairState>> {
  const states: Record<string, Partial<JHPairState>> = {};
  const pairs = ['APTUSDT', 'CRVUSDT', 'EIGENUSDT', 'TAOUSDT', 'UNIUSDT', 'TRUMPUSDT', 'BONKUSDT', 'SHIBUSDT'];
  for (const p of pairs) states[p] = { symbol: p };

  for (const l of lines) {
    if (!l.includes('[strategy_JH')) continue;

    for (const sym of pairs) {
      if (!l.includes(sym)) continue;

      if (l.includes('SIGNAL') && l.includes('pivot_low=')) {
        const plM = l.match(/pivot_low=([\d.]+)/);
        if (plM) {
          states[sym].supPrice = parseFloat(plM[1]);
          states[sym].hitCount = 0;
        }
      }

      if (l.includes('SIGNAL') && l.includes('H1 eval')) {
        states[sym].hitCount = 1;
      }
      if (l.includes('SIGNAL') && l.includes('H2 eval')) {
        states[sym].hitCount = 2;
      }
      if (l.includes('SIGNAL') && l.includes('H2 reset')) {
        states[sym].hitCount = 0;
        states[sym].supPrice = null;
      }

      if (l.includes('SUBMIT BUY LIMIT')) {
        states[sym].lastSignal = 'now';
        const eM = l.match(/entry=([\d.]+)/);
        const sM = l.match(/stop=([\d.]+)/);
        const tM = l.match(/target=([\d.]+)/);
        if (eM) states[sym].entryPrice = parseFloat(eM[1]);
        if (sM) states[sym].stop = parseFloat(sM[1]);
        if (tM) states[sym].target = parseFloat(tM[1]);
      }

      if (l.includes('EXIT') && l.includes('HOLD')) {
        const lastM = l.match(/last=([\d.]+)/);
        if (lastM) states[sym].currentPrice = parseFloat(lastM[1]);
        states[sym].hasPosition = true;
      }
      if (l.includes('EXIT') && (l.includes('TRIGGER STOP') || l.includes('TRIGGER TARGET'))) {
        states[sym].hasPosition = false;
      }
      if (l.includes('EXIT') && l.includes('no active')) {
        states[sym].hasPosition = false;
      }

      if (l.includes('sup=') && l.includes('SIGNAL')) {
        const supM = l.match(/sup=([\d.]+)/);
        if (supM) states[sym].supPrice = parseFloat(supM[1]);
      }
    }
  }
  return states;
}

// ── Sub-components ──

const Badge: FC<{ color: 'green' | 'red' | 'yellow' | 'gray'; children: React.ReactNode }> = ({ color, children }) => {
  const cls: Record<string, string> = {
    green: 'border-emerald-400/80 bg-emerald-500/10 text-emerald-100',
    red: 'border-rose-400/80 bg-rose-500/10 text-rose-100',
    yellow: 'border-amber-400/80 bg-amber-500/10 text-amber-100',
    gray: 'border-white/20 bg-white/5 text-white/70',
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
  const [regime, setRegime] = useState<RegimeState | null>(null);
  const [momentum, setMomentum] = useState<MomentumEntry[]>([]);
  const [rebalance, setRebalance] = useState<RebalanceState | null>(null);
  const [malikiPos, setMalikiPos] = useState<MalikiPositionState | null>(null);
  const [jhPairs, setJhPairs] = useState<Record<string, Partial<JHPairState>>>({});
  const [rebalFlash, setRebalFlash] = useState(false);
  const prevTick = useRef(0);

  useEffect(() => {
    let cancelled = false;
    async function poll() {
      if (cancelled) return;
      try {
        const r = await api.logsTail(500);
        if (!cancelled) {
          const newRegime = parseRegime(r.lines);
          const newMom = parseMomentumRankings(r.lines);
          const newRebal = parseRebalance(r.lines);
          const newTrail = parseMalikiTrail(r.lines);
          const newJH = parseJHPairStates(r.lines);
          if (newRegime) setRegime(newRegime);
          if (newMom.length) setMomentum(newMom);
          if (newRebal) {
            if (prevTick.current > 0 && newRebal.tickCount < prevTick.current) {
              setRebalFlash(true);
              setTimeout(() => setRebalFlash(false), 2000);
            }
            prevTick.current = newRebal.tickCount;
            setRebalance(newRebal);
          }
          setMalikiPos(newTrail);
          setJhPairs(newJH);
        }
      } catch {
        // ignore
      }
    }
    poll();
    const t = setInterval(poll, 15000);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  if (!engineRunning) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-white/50">
        Start the engine to see strategy health.
      </div>
    );
  }

  const malikiRunning = running.find(s => s.name === 'strategy_maliki');
  const jhRunning = running.find(s => s.name === 'strategy_JH');

  const malikiHolding = holdings['strategy_maliki'];
  const malikiPositions = Object.values(malikiHolding?.positions || {}).filter(p => p.quantity > 0);
  const isFlat = malikiPositions.length === 0;

  const jhHolding = holdings['strategy_JH'];
  const jhPositions = Object.entries(jhHolding?.positions || {}).filter(([, p]) => p.quantity > 0);

  // Rebalance progress
  const rebalPct = rebalance ? ((rebalance.tickCount % rebalance.rebalEvery) / rebalance.rebalEvery) * 100 : 0;
  const ticksLeft = rebalance ? rebalance.rebalEvery - (rebalance.tickCount % rebalance.rebalEvery) : 0;
  // Each tick ≈ 5 min (timer_trigger=300 at 1s interval)
  const minsLeft = ticksLeft * 5;
  const hoursLeft = Math.floor(minsLeft / 60);
  const minsRem = minsLeft % 60;

  return (
    <div className="flex h-full flex-col gap-3 overflow-auto pr-1">
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

        <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
          {/* 1. Regime Indicator */}
          <Card title="BTC Regime">
            {regime ? (
              <div className="space-y-1.5">
                <div>
                  {regime.bullish ? (
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
                  BTC <span className="text-slate-100">${regime.btcPrice.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
                  {' | '}MA <span className="text-slate-100">${regime.btcMa.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
                  {' | '}
                  <span className={regime.bullish ? 'text-emerald-400' : 'text-rose-400'}>
                    {regime.spreadPct >= 0 ? '+' : ''}{regime.spreadPct.toFixed(1)}% {regime.bullish ? 'above' : 'below'}
                  </span>
                </div>
                {!regime.bullish && (
                  <div className="mt-1 rounded border border-rose-400/30 bg-rose-500/5 px-2 py-1 text-[11px] text-rose-200">
                    Strategy is in CASH — waiting for BTC to cross above MA
                  </div>
                )}
              </div>
            ) : (
              <div className="text-xs text-white/50">Waiting for regime data...</div>
            )}
          </Card>

          {/* 2. Momentum Rankings */}
          <Card title="Momentum Rankings (top 10)">
            {momentum.length > 0 ? (
              <div className="max-h-40 overflow-auto">
                <table className="w-full border-collapse text-left">
                  <thead>
                    <tr className="text-[10px] text-white/60">
                      <th className="px-1 py-0.5">#</th>
                      <th className="px-1 py-0.5">Coin</th>
                      <th className="px-1 py-0.5 text-right">48h Mom%</th>
                      <th className="px-1 py-0.5 text-right">&gt;3%?</th>
                    </tr>
                  </thead>
                  <tbody>
                    {momentum.slice(0, 10).map((e, i) => (
                      <tr
                        key={e.coin}
                        className={`border-t border-white/5 text-xs ${i === 0 ? 'bg-emerald-500/10' : ''}`}
                      >
                        <td className="px-1 py-0.5 text-white/50">{i + 1}</td>
                        <td className={`px-1 py-0.5 font-mono ${i === 0 ? 'font-bold text-emerald-200' : 'text-slate-100'}`}>
                          {e.coin}
                        </td>
                        <td className={`px-1 py-0.5 text-right tabular-nums ${e.momentumPct >= 3 ? 'text-emerald-400' : 'text-white/70'}`}>
                          {e.momentumPct >= 0 ? '+' : ''}{e.momentumPct.toFixed(1)}%
                        </td>
                        <td className="px-1 py-0.5 text-right">
                          {e.momentumPct >= 3
                            ? <span className="text-emerald-400">Yes</span>
                            : <span className="text-white/40">No</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="text-xs text-white/50">No coin above 3% threshold — staying in cash</div>
            )}
          </Card>

          {/* 3. Rebalance Countdown */}
          <Card title="Rebalance Countdown">
            {rebalance ? (
              <div className="space-y-1.5">
                <div className="flex items-center gap-2">
                  <div className="flex-1">
                    <div className={`h-2 rounded-full bg-white/10 overflow-hidden transition-all ${rebalFlash ? 'ring-2 ring-emerald-400/50' : ''}`}>
                      <div
                        className="h-full rounded-full bg-emerald-500/60 transition-all duration-1000"
                        style={{ width: `${rebalPct}%` }}
                      />
                    </div>
                  </div>
                  <span className="font-mono text-xs tabular-nums text-white/70">
                    {rebalance.tickCount % rebalance.rebalEvery}/{rebalance.rebalEvery}
                  </span>
                </div>
                <div className="font-mono text-xs text-white/60">
                  Next rebalance in{' '}
                  <span className="text-slate-100">
                    {hoursLeft}h {minsRem}m
                  </span>
                  <span className="ml-2 text-white/40">({ticksLeft} ticks)</span>
                </div>
                {rebalFlash && (
                  <div className="animate-pulse rounded border border-emerald-400/40 bg-emerald-500/10 px-2 py-0.5 text-[10px] text-emerald-200">
                    Rebalance triggered!
                  </div>
                )}
              </div>
            ) : (
              <div className="text-xs text-white/50">Waiting for timer data...</div>
            )}
          </Card>

          {/* 4. Position Status */}
          <Card title="Position Status">
            {isFlat ? (
              <div className="space-y-1">
                <Badge color="gray">FLAT</Badge>
                <div className="text-xs text-white/50">
                  {!regime ? 'Waiting for data...'
                    : !regime.bullish ? 'Reason: BEAR regime'
                    : momentum.length === 0 ? 'Reason: No momentum above threshold'
                    : 'Reason: Waiting for rebalance'}
                </div>
              </div>
            ) : (
              malikiPositions.map((p) => {
                const pnl = p.mid_price && p.avg_cost ? ((p.mid_price - p.avg_cost) / p.avg_cost) * 100 : 0;
                const trailStop = malikiPos ? malikiPos.peakPrice * (1 - 0.08) : 0;
                const distToStop = p.mid_price && trailStop ? ((p.mid_price - trailStop) / p.mid_price) * 100 : 0;
                const canExit = malikiPos ? malikiPos.ticksHeld >= malikiPos.minHold : false;
                const ticksToExit = malikiPos ? Math.max(0, malikiPos.minHold - malikiPos.ticksHeld) : 0;
                const hoursToExit = Math.floor((ticksToExit * 5) / 60);
                const minsToExit = (ticksToExit * 5) % 60;

                return (
                  <div key={p.symbol} className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-sm font-bold text-slate-100">{p.symbol.replace('USDT', '')}</span>
                      <span className={`font-mono text-sm font-bold tabular-nums ${pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)}%
                      </span>
                    </div>
                    <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 font-mono text-[11px]">
                      <span className="text-white/50">Entry</span>
                      <span className="text-right tabular-nums text-slate-100">${p.avg_cost.toFixed(2)}</span>
                      <span className="text-white/50">Current</span>
                      <span className="text-right tabular-nums text-slate-100">${p.mid_price.toFixed(2)}</span>
                      {malikiPos && (
                        <>
                          <span className="text-white/50">Trail stop</span>
                          <span className="text-right tabular-nums text-slate-100">${trailStop.toFixed(2)}</span>
                          <span className="text-white/50">Dist to stop</span>
                          <span className={`text-right tabular-nums ${distToStop > 4 ? 'text-emerald-400' : distToStop > 2 ? 'text-amber-400' : 'text-rose-400'}`}>
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
                        : <span className="text-amber-300">Can exit in {hoursToExit}h {minsToExit}m</span>}
                    </div>
                  </div>
                );
              })
            )}
          </Card>
        </div>
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

        {/* 5. Pair Scanner */}
        <Card title="Pair Scanner">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {['APTUSDT', 'CRVUSDT', 'EIGENUSDT', 'TAOUSDT', 'UNIUSDT', 'TRUMPUSDT', 'BONKUSDT', 'SHIBUSDT'].map((sym) => {
              const st = jhPairs[sym] || {};
              const hc = st.hitCount ?? 0;
              const hasPos = st.hasPosition || false;
              const statusColor = hasPos || st.lastSignal ? 'green'
                : hc >= 1 ? 'yellow'
                : 'red';
              const statusDot = statusColor === 'green' ? 'bg-emerald-400'
                : statusColor === 'yellow' ? 'bg-amber-400'
                : 'bg-white/30';
              const borderCls = statusColor === 'green' ? 'border-emerald-400/30'
                : statusColor === 'yellow' ? 'border-amber-400/30'
                : 'border-white/10';

              const jhPos = jhPositions.find(([s]) => s === sym);

              return (
                <div key={sym} className={`rounded-lg border ${borderCls} bg-black/30 p-2`}>
                  <div className="mb-1 flex items-center justify-between">
                    <span className="font-mono text-xs font-bold text-slate-100">
                      {sym.replace('USDT', '')}
                    </span>
                    <span className={`h-2 w-2 rounded-full ${statusDot}`} />
                  </div>

                  <div className="space-y-0.5 font-mono text-[10px]">
                    {st.currentPrice ? (
                      <div className="text-white/60">
                        Price <span className="text-slate-100">${st.currentPrice.toFixed(st.currentPrice < 0.01 ? 8 : 4)}</span>
                      </div>
                    ) : null}

                    {st.supPrice != null ? (
                      <div className="text-white/60">
                        Support <span className="text-amber-300">${st.supPrice.toFixed(st.supPrice < 0.01 ? 8 : 4)}</span>
                      </div>
                    ) : (
                      <div className="text-white/30">No support</div>
                    )}

                    <div className="text-white/60">
                      Hits{' '}
                      <span className={hc === 0 ? 'text-white/30' : hc === 1 ? 'text-amber-300' : 'text-emerald-300'}>
                        H{hc}
                      </span>
                    </div>

                    {st.lastSignal && (
                      <div className="text-emerald-400">Signal fired</div>
                    )}

                    {/* 6. Active trade for this pair */}
                    {jhPos && (
                      <div className="mt-1 space-y-0.5 border-t border-white/10 pt-1">
                        <div className="text-emerald-300">IN TRADE</div>
                        <div className="text-white/60">
                          Entry <span className="text-slate-100">{jhPos[1].avg_cost.toFixed(4)}</span>
                        </div>
                        {st.stop != null && (
                          <div className="text-white/60">
                            Stop <span className="text-rose-300">{st.stop.toFixed(4)}</span>
                          </div>
                        )}
                        {st.target != null && (
                          <div className="text-white/60">
                            Target <span className="text-emerald-300">{st.target.toFixed(4)}</span>
                          </div>
                        )}
                        {st.stop != null && st.target != null && jhPos[1].mid_price > 0 && (
                          <div className="mt-0.5">
                            <div className="relative h-1.5 rounded-full bg-white/10">
                              {(() => {
                                const range = st.target - st.stop;
                                const pos = range > 0 ? ((jhPos[1].mid_price - st.stop) / range) * 100 : 50;
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
                              <span className={`font-bold ${jhPos[1].mid_price >= jhPos[1].avg_cost ? 'text-emerald-400' : 'text-rose-400'}`}>
                                {((jhPos[1].mid_price - jhPos[1].avg_cost) / jhPos[1].avg_cost * 100).toFixed(1)}%
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
      </div>
    </div>
  );
};
