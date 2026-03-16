import type {
  AddStrategyPayload,
  AddStrategyResponse,
  AllSymbolsResponse,
  AvailableStrategiesResponse,
  DeleteStrategyPayload,
  DeleteStrategyResponse,
  Health,
  InitStrategyPayload,
  InitStrategyResponse,
  LogsTailResponse,
  PositionsResponse,
  RunningStrategiesResponse,
  StartStrategyPayload,
  StartStrategyResponse,
  StartStrategyByNamePayload,
  StartStrategyByNameResponse,
  StopStrategyPayload,
  StopStrategyResponse,
  SymbolSnapshot,
  SystemStatus,
  PairsResponse,
} from './types';

const API_BASE =
  (import.meta as any).env?.VITE_API_BASE?.toString?.() || 'http://localhost:8000';

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method || 'GET').toUpperCase();
  const hasBody = init?.body !== undefined && init?.body !== null;
  const headers: Record<string, string> = {};
  // Only set Content-Type when we actually send a body.
  // Setting it on GET triggers CORS preflight (OPTIONS) unnecessarily.
  if (hasBody && method !== 'GET') headers['Content-Type'] = 'application/json';

  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...headers,
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`${res.status} ${res.statusText}${text ? ` - ${text}` : ''}`);
  }
  return (await res.json()) as T;
}

export const api = {
  baseUrl: API_BASE,
  systemStatus: () => http<SystemStatus>('/system/status'),
  systemStart: (mode: 'mock' | 'real') =>
    http<SystemStatus>('/system/start', { method: 'POST', body: JSON.stringify({ mode }) }),
  systemStop: () => http<SystemStatus>('/system/stop', { method: 'POST', body: JSON.stringify({}) }),
  health: () => http<Health>('/health'),
  pairs: () => http<PairsResponse>('/pairs'),
  availableStrategies: () => http<AvailableStrategiesResponse>('/strategies/available'),
  runningStrategies: () => http<RunningStrategiesResponse>('/strategies/running'),
  addStrategy: (payload: AddStrategyPayload) =>
    http<AddStrategyResponse>('/strategies/add', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  initStrategy: (payload: InitStrategyPayload) =>
    http<InitStrategyResponse>('/strategies/init', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  startStrategy: (payload: StartStrategyPayload) =>
    http<StartStrategyResponse>('/strategies/start', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  startStrategyByName: (payload: StartStrategyByNamePayload) =>
    http<StartStrategyByNameResponse>('/strategies/start', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  stopStrategy: (payload: StopStrategyPayload) =>
    http<StopStrategyResponse>('/strategies/stop', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  deleteStrategy: (payload: DeleteStrategyPayload) =>
    http<DeleteStrategyResponse>('/strategies/delete', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  positions: () => http<PositionsResponse>('/positions'),
  symbol: (symbol: string) => http<SymbolSnapshot>(`/symbols/${encodeURIComponent(symbol)}`),
  symbols: () => http<AllSymbolsResponse>('/symbols'),
  logsTail: (n = 200) => http<LogsTailResponse>(`/logs/tail?n=${n}`),
  logsStreamUrl: () => `${API_BASE}/logs/stream`,
};

