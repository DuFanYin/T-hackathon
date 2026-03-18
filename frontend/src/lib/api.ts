import type {
  AddStrategyPayload,
  AddStrategyResponse,
  AccountBalanceResponse,
  AccountOrdersResponse,
  AccountPendingCountResponse,
  AvailableStrategiesResponse,
  CloseAllPositionsResponse,
  ClosePositionsPayload,
  ClosePositionsResponse,
  DeleteStrategyPayload,
  DeleteStrategyResponse,
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

let ADMIN_TOKEN: string | null = null;

export function setAdminToken(token: string | null) {
  ADMIN_TOKEN = token;
}

const API_BASE =
  import.meta.env?.VITE_API_BASE?.toString?.() || 'https://marlyn-auntlike-verla.ngrok-free.dev';

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method || 'GET').toUpperCase();
  const hasBody = init?.body !== undefined && init?.body !== null;
  const headers: Record<string, string> = { 'ngrok-skip-browser-warning': 'true' };
  // Only set Content-Type when we actually send a body.
  // Setting it on GET triggers CORS preflight (OPTIONS) unnecessarily.
  if (hasBody && method !== 'GET') headers['Content-Type'] = 'application/json';
  if (ADMIN_TOKEN) headers['x-admin-token'] = ADMIN_TOKEN;

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
  checkAdmin: async (token: string): Promise<boolean> => {
    try {
      await http<{ ok: boolean }>('/auth/check', {
        headers: { 'x-admin-token': token },
      });
      return true;
    } catch {
      return false;
    }
  },
  systemStatus: () => http<SystemStatus>('/system/status'),
  systemStart: (mode: 'mock' | 'real') =>
    http<SystemStatus>('/system/start', { method: 'POST', body: JSON.stringify({ mode }) }),
  systemStop: () => http<SystemStatus>('/system/stop', { method: 'POST', body: JSON.stringify({}) }),
  availableStrategies: () => http<AvailableStrategiesResponse>('/strategies/available'),
  runningStrategies: () => http<RunningStrategiesResponse>('/strategies/running'),
  addStrategy: (payload: AddStrategyPayload) =>
    http<AddStrategyResponse>('/strategies/add', {
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
  closePositions: (payload: ClosePositionsPayload) =>
    http<ClosePositionsResponse>('/positions/close', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  closeAllPositions: () =>
    http<CloseAllPositionsResponse>('/positions/close_all', {
      method: 'POST',
      body: JSON.stringify({}),
    }),
  logsTail: (n = 200) => http<LogsTailResponse>(`/logs/tail?n=${n}`),
  logsStreamUrl: () => `${API_BASE}/logs/stream`,
  accountBalance: () => http<AccountBalanceResponse>('/account/balance'),
  accountPendingCount: () => http<AccountPendingCountResponse>('/account/pending_count'),
  accountOrders: (pendingOnly = true, limit = 200) =>
    http<AccountOrdersResponse>(`/account/orders?pending_only=${pendingOnly ? 'true' : 'false'}&limit=${limit}`),
  orders: (strategy?: string, symbol?: string, limit = 500) => {
    const q = new URLSearchParams()
    if (strategy) q.set('strategy', strategy)
    if (symbol) q.set('symbol', symbol)
    q.set('limit', String(limit))
    const qs = q.toString()
    return http<OrdersResponse>(`/orders${qs ? `?${qs}` : ''}`)
  },
};

