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
  <div className="card">
    <div className="row" style={{ marginBottom: 'var(--space-md)' }}>
      <div className="field">
        <label>Strategy</label>
        <select value={startStrategy} onChange={(e) => setStartStrategy(e.target.value)}>
          {available.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label>Symbol</label>
        <select value={startSymbol} onChange={(e) => setStartSymbol(e.target.value)}>
          {(pairs.length ? pairs : [startSymbol]).map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </div>
      <button className="btn" disabled={busy === 'add'} onClick={onAdd}>
        Add
      </button>
      <button
        className="btn primary"
        disabled={!selectedName || busy === 'start'}
        onClick={onStartSelected}
      >
        Start
      </button>
      <button
        className="btn"
        disabled={!selectedName || busy === selectedName}
        onClick={() => onInit(selectedName)}
      >
        Init
      </button>
      <button
        className="btn danger"
        disabled={!selectedName || busy === selectedName}
        onClick={() => onStop(selectedName)}
      >
        Stop
      </button>
      <button
        className="btn"
        disabled={!selectedName || busy === `${selectedName}-del`}
        onClick={() => onDelete(selectedName)}
      >
        Delete
      </button>
      <div className="muted mono" style={{ alignSelf: 'center' }}>
        {actionErr}
      </div>
    </div>

    <div className="table-wrapper">
    <table className="table">
      <thead>
        <tr>
          <th>Name</th>
          <th>Inited</th>
          <th>Started</th>
          <th>Error</th>
          <th className="mono">Error msg</th>
          <th>Pos</th>
          <th className="num">Total cost</th>
          <th className="num">Value</th>
          <th className="num">U PnL</th>
          <th className="num">R PnL</th>
          <th className="num">PnL</th>
          <th className="mono">Selected</th>
        </tr>
      </thead>
      <tbody>
        {running.map((s) => (
          <tr
            key={s.name}
            className={selectedName === s.name ? 'selected' : ''}
            onClick={() => onSelect(s.name)}
            style={{ cursor: 'pointer' }}
          >
            <td className="mono">{s.name}</td>
            <td>{String(s.inited)}</td>
            <td>{String(s.started)}</td>
            <td>{String(s.error)}</td>
            <td className="mono muted">{s.error_msg}</td>
            <td className="mono">
              {(() => {
                const h = holdings[s.name];
                if (!h) return '-';
                const ps = Object.values(h.positions || {}).filter((p) => p.quantity !== 0);
                if (ps.length === 0) return 'FLAT';
                return ps.map((p) => `${p.symbol}:${p.quantity}`).join(', ');
              })()}
            </td>
            <td className="mono num">
              {holdings[s.name] ? (holdings[s.name].total_cost ?? 0).toFixed(2) : '-'}
            </td>
            <td className="mono num">
              {holdings[s.name] ? (holdings[s.name].current_value ?? 0).toFixed(2) : '-'}
            </td>
            <td className="mono num">
              {holdings[s.name] ? (holdings[s.name].unrealized_pnl ?? 0).toFixed(2) : '-'}
            </td>
            <td className="mono num">
              {holdings[s.name] ? (holdings[s.name].realized_pnl ?? 0).toFixed(2) : '-'}
            </td>
            <td className="mono num">
              {holdings[s.name] ? (holdings[s.name].pnl ?? 0).toFixed(2) : '-'}
            </td>
            <td className="mono">{selectedName === s.name ? 'YES' : ''}</td>
          </tr>
        ))}
        {running.length === 0 && (
          <tr>
            <td colSpan={6} className="muted">
              No running strategies (use the form above to start one).
            </td>
          </tr>
        )}
      </tbody>
    </table>
    </div>

    <div className="meta" style={{ marginTop: 10 }}>
      Available strategies: {available.length ? available.join(', ') : '(none)'}
      <br />
      Active instances: {activeNames.size}
    </div>
  </div>
);

