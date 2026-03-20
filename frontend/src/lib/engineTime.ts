/**
 * Engine UI: **Asia/Singapore**, **24-hour** (SGT). Use for all user-visible dates/times.
 */

export const ENGINE_TIME_ZONE = 'Asia/Singapore' as const;

const LOCALE = 'en-SG';

/** Date + time, Singapore, 24h (e.g. order timestamps, last-query time). */
const dateTime24hSG: Intl.DateTimeFormatOptions = {
  timeZone: ENGINE_TIME_ZONE,
  hour12: false,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
};

/** Time-only, Singapore, 24h (e.g. sidebar clock). */
const time24hSG: Intl.DateTimeFormatOptions = {
  timeZone: ENGINE_TIME_ZONE,
  hour12: false,
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
};

/**
 * Format Unix time (seconds or ms) as Singapore local date+time, 24-hour.
 */
export function formatEngineDateTime(unixSecondsOrMs: number): string {
  const ms = unixSecondsOrMs < 1e12 ? unixSecondsOrMs * 1000 : unixSecondsOrMs;
  return new Date(ms).toLocaleString(LOCALE, dateTime24hSG);
}

/**
 * Format a `Date` (typically `new Date()` in the browser) as Singapore time-of-day, 24-hour.
 */
export function formatEngineClock(now: Date): string {
  return now.toLocaleTimeString(LOCALE, time24hSG);
}

/**
 * Safe wrapper for nullable / invalid timestamps (API fields).
 */
export function formatEngineDateTimeOrDash(ts: number | null | undefined): string {
  if (ts == null || !Number.isFinite(ts)) return '-';
  try {
    return formatEngineDateTime(ts);
  } catch {
    return '-';
  }
}
