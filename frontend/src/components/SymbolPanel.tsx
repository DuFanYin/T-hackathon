import type { FC } from 'react';
import { useEffect, useRef, useState } from 'react';
import type { SymbolSnapshot } from '../lib/types';

interface SymbolPanelProps {
  symbols: Record<string, SymbolSnapshot>;
}

export const SymbolPanel: FC<SymbolPanelProps> = ({ symbols }) => {
  const entries = Object.values(symbols).sort((a, b) => a.symbol.localeCompare(b.symbol));
  const lastPriceRef = useRef<Record<string, number>>({});
  const [directions, setDirections] = useState<Record<string, 'up' | 'down' | null>>({});
  const directionsRef = useRef<Record<string, 'up' | 'down' | null>>({});
  const changeRef = useRef<Record<string, number>>({});
  const [changeDirs, setChangeDirs] = useState<Record<string, 'up' | 'down' | null>>({});
  const changeDirsRef = useRef<Record<string, 'up' | 'down' | null>>({});

  useEffect(() => {
    const nextDirections: Record<string, 'up' | 'down' | null> = {};
    const nextChangeDirs: Record<string, 'up' | 'down' | null> = {};
    const nextEntries = Object.values(symbols).sort((a, b) => a.symbol.localeCompare(b.symbol));
    for (const s of nextEntries) {
      const prevPrice = lastPriceRef.current[s.symbol];
      const curr = Number(s.last_price);
      let dir: 'up' | 'down' | null = directionsRef.current[s.symbol] ?? null;
      if (Number.isFinite(prevPrice)) {
        if (curr > prevPrice) dir = 'up';
        else if (curr < prevPrice) dir = 'down';
      }
      nextDirections[s.symbol] = dir;
      lastPriceRef.current[s.symbol] = curr;

      const prevChange = changeRef.current[s.symbol];
      const currChange = s.change_24h == null ? NaN : Number(s.change_24h);
      let cdir: 'up' | 'down' | null = changeDirsRef.current[s.symbol] ?? null;
      if (Number.isFinite(prevChange) && Number.isFinite(currChange)) {
        if (currChange > prevChange) cdir = 'up';
        else if (currChange < prevChange) cdir = 'down';
      }
      nextChangeDirs[s.symbol] = cdir;
      changeRef.current[s.symbol] = currChange;
    }
    directionsRef.current = nextDirections;
    setDirections(nextDirections);
    changeDirsRef.current = nextChangeDirs;
    setChangeDirs(nextChangeDirs);
  }, [symbols]);

  return (
    <div className="flex h-full w-full flex-col rounded-xl border border-white/10 bg-white/5 p-4 shadow-[0_10px_30px_rgba(0,0,0,0.5)]">
      <div className="mb-2 text-xs text-white/70">
        Realtime market snapshots for all symbols. Last price and 24h change highlight moves.
      </div>
      {entries.length === 0 ? (
        <div className="text-xs text-white/70">
          No symbol data yet. Start the system and wait for ticks.
        </div>
      ) : (
        <div className="mt-2 flex-1 overflow-auto rounded-lg border border-white/10 bg-black/40">
          <table className="w-full border-collapse text-left text-[13px]">
            <thead>
              <tr className="bg-white/5 text-xs text-white/80">
                <th className="px-2 py-2">Symbol</th>
                <th className="px-2 py-2 text-right">Last</th>
                <th className="px-2 py-2 text-right">Bid</th>
                <th className="px-2 py-2 text-right">Ask</th>
                <th className="px-2 py-2 text-right">24h Vol</th>
                <th className="px-2 py-2 text-right">24h Notional</th>
                <th className="px-2 py-2 text-right">24h Change</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((s) => (
                <tr key={s.symbol} className="border-t border-white/5 hover:bg-white/10">
                  <td className="px-2 py-1.5 text-xs text-slate-100">{s.symbol}</td>
                  <td
                    className={[
                      'px-2 py-1.5 text-right tabular-nums',
                      directions[s.symbol] === 'up'
                        ? 'text-rose-400'
                        : directions[s.symbol] === 'down'
                        ? 'text-emerald-400'
                        : 'text-slate-100',
                    ].join(' ')}
                  >
                    {s.last_price}
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums">
                    {s.bid_price ?? '-'}
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums">
                    {s.ask_price ?? '-'}
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums">
                    {s.volume_24h ?? '-'}
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums">
                    {s.notional_24h ?? '-'}
                  </td>
                  <td
                    className={[
                      'px-2 py-1.5 text-right tabular-nums',
                      changeDirs[s.symbol] === 'up'
                        ? 'text-rose-400'
                        : changeDirs[s.symbol] === 'down'
                        ? 'text-emerald-400'
                        : 'text-slate-100',
                    ].join(' ')}
                  >
                    {s.change_24h ?? '-'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

