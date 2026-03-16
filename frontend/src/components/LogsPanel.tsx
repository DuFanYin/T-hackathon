import type { FC, MutableRefObject } from 'react';

interface LogsPanelProps {
  logs: string[];
  logsOn: boolean;
  setLogsOn: (v: boolean) => void;
  onTail: () => void;
  onClear: () => void;
  logBoxRef: MutableRefObject<HTMLDivElement | null>;
}

export const LogsPanel: FC<LogsPanelProps> = ({
  logs,
  logsOn,
  setLogsOn,
  onTail,
  onClear,
  logBoxRef,
}) => (
  <div className="card">
    <div className="row" style={{ marginBottom: 'var(--space-md)' }}>
      <button className="btn" onClick={onTail}>
        Tail 200
      </button>
      <button className="btn" onClick={onClear}>
        Clear
      </button>
      <button className={`btn ${logsOn ? 'primary' : ''}`} onClick={() => setLogsOn(!logsOn)}>
        {logsOn ? 'SSE: ON' : 'SSE: OFF'}
      </button>
    </div>

    <div ref={logBoxRef} className="logs mono">
      {logs.join('\n')}
    </div>
  </div>
);

