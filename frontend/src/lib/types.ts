export type AvailableStrategiesResponse = { available: string[] };

export type RunningStrategy = {
  name: string;
  inited: boolean;
  started: boolean;
  error: boolean;
  error_msg: string;
};
export type RunningStrategiesResponse = { running: RunningStrategy[] };

export type StartStrategyPayload = { strategy: string };
export type StartStrategyResponse = { ok: boolean; name: string };

export type StartStrategyByNamePayload = { name: string };
export type StartStrategyByNameResponse = { ok: boolean; name: string };

export type StopStrategyPayload = { name: string };
export type StopStrategyResponse = { ok: boolean; name: string };

export type Position = {
  symbol: string;
  quantity: number;
  avg_cost: number;
  cost_value: number;
  realized_pnl: number;
  mid_price: number;
  current_value: number;
};

export type Holding = {
  positions: Record<string, Position>;
  total_cost: number;
  current_value: number;
  unrealized_pnl: number;
  realized_pnl: number;
  pnl: number;
};

export type PositionsResponse = { holdings: Record<string, Holding> };

export type ClosePositionsPayload = { name: string };
export type ClosePositionsResponse = { ok: boolean; name: string };

export type CloseAllPositionsResponse = { ok: boolean; closed: string[]; errors: Record<string, string> };

export type LogsTailResponse = { lines: string[] };
export type SystemStatus = { running: boolean; mode: 'mock' | 'real' | null };

export type AccountBalanceResponse = { balance: unknown };
export type AccountPendingCountResponse = { pending_count: unknown };
export type AccountOrdersResponse = { orders: unknown };
export type AccountPnlResponse = { equity: number; init_balance: number; pnl: number; pnl_pct: number };

export type OrderRow = {
  order_id: string;
  strategy_name: string;
  symbol: string;
  side: string;
  status: string;
  quantity: number;
  price: number;
  filled_quantity: number;
  filled_avg_price: number;
  updated_ts: number;
  raw_json: string | null;
};

export type OrdersResponse = { rows: OrderRow[] };

