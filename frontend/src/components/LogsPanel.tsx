import type { FC, MutableRefObject } from 'react';

interface LogsPanelProps {
  logs: string[];
  isAuthed: boolean;
  onTail: () => void;
  onClear: () => void;
  logBoxRef: MutableRefObject<HTMLDivElement | null>;
}

export const LogsPanel: FC<LogsPanelProps> = ({
  logs,
  isAuthed,
  onTail,
  onClear,
  logBoxRef,
}) => {
  const renderLine = (line: string, idx: number) => {
    const raw = line.trim();
    if (!raw) {
      return <div key={idx}>&nbsp;</div>;
    }

    // Backend-generated timestamp prefix: "MM-DD HH:MM:SS | rest..."
    let timestamp: string | null = null;
    let msg = raw;

    const m = raw.match(/^(\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*\|\s*(.*)$/);
    if (m) {
      timestamp = m[1];
      msg = m[2];
    }

    return (
      <div key={idx} className="flex items-start gap-3 text-xs">
        {timestamp && (
          <span className="shrink-0 font-mono text-emerald-300">
            {timestamp}
          </span>
        )}
        <span className="flex-1 text-slate-100">{msg}</span>
      </div>
    );
  };

  return (
    <div className="flex h-full w-full flex-col rounded-xl border border-white/10 bg-white/5 p-4 shadow-[0_10px_30px_rgba(0,0,0,0.5)]">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <button
          className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-white/20 bg-white/10 px-3 py-2 text-xs font-medium text-slate-50 transition hover:border-white/40 hover:bg-white/20"
          disabled={!isAuthed}
          onClick={onTail}
        >
          Tail 200
        </button>
        <button
          className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-white/20 bg-white/5 px-3 py-2 text-xs font-medium text-slate-50 transition hover:border-white/40 hover:bg-white/10"
          disabled={!isAuthed}
          onClick={onClear}
        >
          Clear
        </button>
      </div>

      <div
        ref={logBoxRef}
        className="flex-1 overflow-auto rounded-lg border border-white/10 bg-black/40 p-3 font-mono leading-relaxed text-xs"
      >
        {logs.map(renderLine)}
      </div>
    </div>
  );
};

