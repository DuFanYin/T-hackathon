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
    <div className="card">
      <div className="row" style={{ marginBottom: 'var(--space-md)' }}>
        <div className="muted">
          Realtime market snapshots for all symbols. Last price and 24h change highlight moves.
        </div>
      </div>
      {entries.length === 0 ? (
        <div className="muted">No symbol data yet. Start the system and wait for ticks.</div>
      ) : (
        <div className="table-wrapper">
          <table className="table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th className="num">Last</th>
                <th className="num">Bid</th>
                <th className="num">Ask</th>
                <th className="num">24h Vol</th>
                <th className="num">24h Notional</th>
                <th className="num">24h Change</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((s) => (
                <tr key={s.symbol}>
                  <td>{s.symbol}</td>
                  <td
                    className={`num ${
                      directions[s.symbol] === 'up'
                        ? 'price-up'
                        : directions[s.symbol] === 'down'
                        ? 'price-down'
                        : ''
                    }`}
                  >
                    {s.last_price}
                  </td>
                  <td className="num">{s.bid_price ?? '-'}</td>
                  <td className="num">{s.ask_price ?? '-'}</td>
                  <td className="num">{s.volume_24h ?? '-'}</td>
                  <td className="num">{s.notional_24h ?? '-'}</td>
                  <td
                    className={`num ${
                      changeDirs[s.symbol] === 'up'
                        ? 'price-up'
                        : changeDirs[s.symbol] === 'down'
                        ? 'price-down'
                        : ''
                    }`}
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

