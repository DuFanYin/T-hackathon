import type { FC } from 'react';
import type { Holding } from '../lib/types';

interface PositionsPanelProps {
  positions: Record<string, Holding>;
  onRefresh: () => void;
  fmt: (n: unknown, digits?: number) => string;
}

export const PositionsPanel: FC<PositionsPanelProps> = ({ positions, onRefresh, fmt }) => (
  <div className="card">
    <div className="row" style={{ marginBottom: 'var(--space-md)' }}>
      <button className="btn" onClick={onRefresh}>
        Refresh positions
      </button>
      <div className="muted mono" style={{ alignSelf: 'center' }}>
        Snapshot of all holdings grouped by strategy.
      </div>
    </div>

    {Object.keys(positions).length === 0 ? (
      <div className="muted" style={{ marginTop: 'var(--space-sm)' }}>
        No holdings yet.
      </div>
    ) : (
      Object.entries(positions).map(([name, holding]) => (
        <div key={name} style={{ marginTop: 'var(--space-md)' }}>
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <div className="mono">{name}</div>
            <div className="mono muted">
              pnl={fmt(holding.pnl)} current={fmt(holding.current_value)} cost=
              {fmt(holding.total_cost)}
            </div>
          </div>
          <div className="table-wrapper">
            <table className="table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th className="num">Qty</th>
                  <th className="num">Avg</th>
                  <th className="num">Mid</th>
                  <th className="num">Value</th>
                </tr>
              </thead>
              <tbody>
                {Object.values(holding.positions || {}).map((p) => (
                  <tr key={p.symbol}>
                    <td className="mono">{p.symbol}</td>
                    <td className="num">{fmt(p.quantity, 6)}</td>
                    <td className="num">{fmt(p.avg_cost)}</td>
                    <td className="num">{fmt(p.mid_price)}</td>
                    <td className="num">{fmt(p.current_value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))
    )}
  </div>
);

