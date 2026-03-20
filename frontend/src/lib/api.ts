import type {
  AccountBalanceResponse,
  AccountOrdersResponse,
  AccountPendingCountResponse,
  AccountPnlResponse,
  AvailableStrategiesResponse,
  CloseAllPositionsResponse,
  ClosePositionsPayload,
  ClosePositionsResponse,
  LogsTailResponse,
  OrdersResponse,
  PositionsResponse,
  RunningStrategiesResponse,
  StartStrategyPayload,
  StartStrategyResponse,
  StartStrategyByNamePayload,
  StartStrategyByNameResponse,
  StopStrategyPayload,
  StopStrategyResponse,
  SystemStatus,
} from './types';

const API_BASE =
  import.meta.env?.VITE_API_BASE?.toString?.() || 'http://localhost:8000';

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method || 'GET').toUpperCase();
  const hasBody = init?.body !== undefined && init?.body !== null;
  const headers: Record<string, string> = { 'ngrok-skip-browser-warning': 'true' };
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
  systemStop: () => http<SystemStatus>('/system/stop', { method: 'POST' }),
  availableStrategies: () => http<AvailableStrategiesResponse>('/strategies/available'),
  runningStrategies: () => http<RunningStrategiesResponse>('/strategies/running'),
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
  positions: () => http<PositionsResponse>('/positions'),
  closePositions: (payload: ClosePositionsPayload) =>
    http<ClosePositionsResponse>('/positions/close', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  closeAllPositions: () =>
    http<CloseAllPositionsResponse>('/positions/close_all', {
      method: 'POST',
    }),
  logsTail: (n = 200) => http<LogsTailResponse>(`/logs/tail?n=${n}`),
  accountBalance: () => http<AccountBalanceResponse>('/account/balance'),
  accountPendingCount: () => http<AccountPendingCountResponse>('/account/pending_count'),
  accountPnl: () => http<AccountPnlResponse>('/account/pnl'),
  accountOrders: () => http<AccountOrdersResponse>('/account/orders'),
  orders: (strategy?: string, symbol?: string, limit = 500) => {
    const q = new URLSearchParams()
    if (strategy) q.set('strategy', strategy)
    if (symbol) q.set('symbol', symbol)
    q.set('limit', String(limit))
    const qs = q.toString()
    return http<OrdersResponse>(`/orders${qs ? `?${qs}` : ''}`)
  },
};
