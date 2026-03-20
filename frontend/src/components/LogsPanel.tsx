import type { FC, MutableRefObject } from 'react';
import { useMemo, useState } from 'react';

export type LogLevel = 'DEBUG' | 'INFO' | 'WARN' | 'ERROR';

const LOG_LEVELS: LogLevel[] = ['DEBUG', 'INFO', 'WARN', 'ERROR'];

type ParsedLogLine = {
  timestamp: string | null;
  level: LogLevel;
  source: string;
  msg: string;
};

/** Parse line: "MM-DD HH:MM:SS | LEVEL | source | message" (SGT, 24h from backend) or legacy formats */
function parseLogLine(line: string): ParsedLogLine {
  const raw = line.trim();
  if (!raw) {
    return { timestamp: null, level: 'INFO', source: 'System', msg: '' };
  }
  // New format: "MM-DD HH:MM:SS | LEVEL | source | message"
  const parts = raw.split(/\s*\|\s*/);
  if (parts.length >= 4) {
    const [ts, lvl, source, ...rest] = parts;
    const level = (lvl?.toUpperCase() || 'INFO') as LogLevel;
    const validLevel = LOG_LEVELS.includes(level) ? level : 'INFO';
    return {
      timestamp: ts || null,
      level: validLevel,
      source: (source || 'System').trim(),
      msg: rest.join(' | ').trim(),
    };
  }
  // Legacy: "MM-DD HH:MM:SS | LEVEL | message"
  const m1 = raw.match(/^(\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*\|\s*(DEBUG|INFO|WARN|ERROR)\s*\|\s*(.*)$/s);
  if (m1) {
    return { timestamp: m1[1], level: m1[2] as LogLevel, source: 'System', msg: m1[3] };
  }
  // Legacy: "MM-DD HH:MM:SS | message"
  const m2 = raw.match(/^(\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*\|\s*(.*)$/s);
  if (m2) {
    return { timestamp: m2[1], level: 'INFO', source: 'System', msg: m2[2] };
  }
  return { timestamp: null, level: 'INFO', source: 'System', msg: raw };
}

const LEVEL_COLORS: Record<LogLevel, string> = {
  DEBUG: 'text-slate-400',
  INFO: 'text-slate-100',
  WARN: 'text-amber-300',
  ERROR: 'text-rose-400',
};

function levelPassesFilter(level: LogLevel, filter: LogLevel | 'ALL'): boolean {
  if (filter === 'ALL') return true;
  return level === filter;
}

function sourcePassesFilter(source: string, filter: string): boolean {
  if (filter === 'ALL') return true;
  return source === filter;
}

/** Extract unique source/strategy names from logs, sorted (System first, then alphabetically) */
function uniqueSources(logs: string[]): string[] {
  const seen = new Set<string>();
  for (const line of logs) {
    const { source } = parseLogLine(line);
    if (source) seen.add(source);
  }
  const list = Array.from(seen).sort((a, b) => {
    if (a === 'System') return -1;
    if (b === 'System') return 1;
    return a.localeCompare(b);
  });
  return list;
}

function getSgtNowYear(now: Date): number {
  try {
    const parts = new Intl.DateTimeFormat('en-SG', {
      timeZone: 'Asia/Singapore',
      year: 'numeric',
    }).formatToParts(now);
    const yearPart = parts.find((p) => p.type === 'year');
    if (yearPart?.value) return Number(yearPart.value);
  } catch {
    // ignore
  }
  return now.getFullYear();
}

/**
 * Convert backend log timestamp prefix: "MM-DD HH:MM:SS" (Singapore time) to epoch ms.
 * Assumes fixed Singapore offset UTC+8 (no DST).
 */
function parseLogTimestampPrefixToEpochMs(ts: string, sgtYear: number): number | null {
  const m = ts.match(/^(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})$/);
  if (!m) return null;
  const month = Number(m[1]);
  const day = Number(m[2]);
  const hh = Number(m[3]);
  const mm = Number(m[4]);
  const ss = Number(m[5]);
  if (![month, day, hh, mm, ss].every((x) => Number.isFinite(x))) return null;
  const utcMs = Date.UTC(sgtYear, month - 1, day, hh, mm, ss);
  // SGT = UTC+8 ⇒ UTC = SGT - 8 hours
  return utcMs - 8 * 60 * 60 * 1000;
}

interface LogsPanelProps {
  logs: string[];
  onTail: () => void;
  onClear: () => void;
  logBoxRef: MutableRefObject<HTMLDivElement | null>;
  logStartEpochMs: number | null;
}

export const LogsPanel: FC<LogsPanelProps> = ({
  logs,
  onTail,
  onClear,
  logBoxRef,
  logStartEpochMs,
}) => {
  const [levelFilter, setLevelFilter] = useState<LogLevel | 'ALL'>('ALL');
  const [sourceFilter, setSourceFilter] = useState<string>('ALL');

  const sgtNowYear = useMemo(() => getSgtNowYear(new Date()), []);

  const timeFilteredLogs = useMemo(() => {
    if (logStartEpochMs == null) return logs;
    return logs.filter((line) => {
      const { timestamp } = parseLogLine(line);
      if (!timestamp) return false;
      const epoch = parseLogTimestampPrefixToEpochMs(timestamp, sgtNowYear);
      if (epoch == null) return false;
      return epoch >= logStartEpochMs;
    });
  }, [logs, logStartEpochMs, sgtNowYear]);

  const sources = useMemo(() => uniqueSources(timeFilteredLogs), [timeFilteredLogs]);

  const filteredLogs = timeFilteredLogs.filter((line) => {
    const { level, source } = parseLogLine(line);
    return levelPassesFilter(level, levelFilter) && sourcePassesFilter(source, sourceFilter);
  });

  const renderLine = (line: string, idx: number) => {
    const { timestamp, level, source, msg } = parseLogLine(line);
    if (!msg && !timestamp) {
      return <div key={idx}>&nbsp;</div>;
    }

    const colorClass = LEVEL_COLORS[level];

    return (
      <div key={idx} className="flex items-start gap-3 text-xs">
        {timestamp && (
          <span
            className="shrink-0 font-mono text-emerald-300"
            title="Singapore time (24-hour)"
          >
            {timestamp}
          </span>
        )}
        <span className={`shrink-0 w-12 font-mono text-xs uppercase ${colorClass}`}>
          {level}
        </span>
        <span className="shrink-0 max-w-[140px] truncate font-mono text-xs text-cyan-300/90" title={source}>
          {source}
        </span>
        <span className={`flex-1 min-w-0 ${colorClass}`}>{msg}</span>
      </div>
    );
  };

  return (
    <div className="flex h-full w-full flex-col rounded-xl border border-white/10 bg-white/5 p-4 shadow-[0_10px_30px_rgba(0,0,0,0.5)]">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <button
          className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-white/20 bg-white/10 px-3 py-2 text-xs font-medium text-slate-50 transition hover:border-white/40 hover:bg-white/20"
          onClick={onTail}
        >
          Refresh
        </button>
        <button
          className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-white/20 bg-white/5 px-3 py-2 text-xs font-medium text-slate-50 transition hover:border-white/40 hover:bg-white/10"
          onClick={onClear}
        >
          Clear
        </button>
        <span className="ml-2 text-xs text-white/50">Level:</span>
        <div className="flex gap-1">
          {(['ALL', ...LOG_LEVELS] as const).map((lvl) => (
            <button
              key={lvl}
              type="button"
              onClick={() => setLevelFilter(lvl)}
              className={`rounded-lg border px-2.5 py-1.5 text-xs font-medium transition focus:outline-none ${
                levelFilter === lvl
                  ? 'border-white/40 bg-white/20 text-slate-50'
                  : 'border-white/20 bg-black/40 text-slate-300 hover:border-white/30 hover:bg-white/5'
              }`}
            >
              {lvl}
            </button>
          ))}
        </div>
        <span className="ml-2 text-xs text-white/50">Source:</span>
        <select
          value={sourceFilter}
          onChange={(e) => setSourceFilter(e.target.value)}
          className="rounded-lg border border-white/20 bg-black/40 px-2 py-1.5 text-xs text-slate-100 focus:border-white/40 focus:outline-none min-w-[120px]"
        >
          <option value="ALL">All</option>
          {sources.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>

      <div
        ref={logBoxRef}
        className="flex-1 overflow-auto rounded-lg border border-white/10 bg-black/40 p-3 font-mono leading-relaxed text-xs"
      >
        {filteredLogs.map(renderLine)}
      </div>
    </div>
  );
};
