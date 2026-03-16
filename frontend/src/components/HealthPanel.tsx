import type { FC } from 'react';
import type { SystemStatus } from '../lib/types';

interface SystemStatusPanelProps {
  health: { ok: boolean; env_mode?: string } | null;
  healthErr: string;
  system: SystemStatus;
  onStartMock: () => void;
  onStartLive: () => void;
  onStopSystem: () => void;
}

export const SystemStatusPanel: FC<SystemStatusPanelProps> = ({
  health,
  healthErr,
  system,
  onStartMock,
  onStartLive,
  onStopSystem,
}) => (
  <div className="card">
    <div className="row" style={{ marginBottom: 'var(--space-md)' }}>
      <div>
        <div className="muted">Engine mode</div>
        <div className="mono">
          {system.running ? system.mode?.toUpperCase() : 'STOPPED'}
        </div>
      </div>
      <div style={{ marginLeft: 'auto' }} className="row">
        <button className="btn" disabled={system.running} onClick={onStartMock}>
          Start mock
        </button>
        <button className="btn" disabled={system.running} onClick={onStartLive}>
          Start live
        </button>
        <button className="btn danger" disabled={!system.running} onClick={onStopSystem}>
          Stop system
        </button>
      </div>
    </div>
    <div className="mono muted">Engine health payload (/health)</div>
    <div style={{ marginTop: 10 }}>
      {health ? (
        <pre className="mono">{JSON.stringify(health, null, 2)}</pre>
      ) : (
        <div className="mono">{healthErr || 'No data'}</div>
      )}
    </div>
  </div>
);

