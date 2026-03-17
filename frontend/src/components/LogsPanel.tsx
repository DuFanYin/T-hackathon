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
}) => (
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
      className="flex-1 overflow-auto whitespace-pre-wrap rounded-lg border border-white/10 bg-black/40 p-3 font-mono text-[11px] leading-tight text-slate-100"
    >
      {logs.join('\n')}
    </div>
  </div>
);

