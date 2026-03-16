export type Health = { ok: boolean; env_mode?: string };

export type AvailableStrategiesResponse = { available: string[] };

export type RunningStrategy = {
  name: string;
  inited: boolean;
  started: boolean;
  error: boolean;
  error_msg: string;
};
export type RunningStrategiesResponse = { running: RunningStrategy[] };

export type StartStrategyPayload = { strategy: string; symbol: string };
export type StartStrategyResponse = { ok: boolean; name: string };

export type StartStrategyByNamePayload = { name: string };
export type StartStrategyByNameResponse = { ok: boolean; name: string };

export type AddStrategyPayload = { strategy: string; symbol: string };
export type AddStrategyResponse = { ok: boolean; name: string };

export type InitStrategyPayload = { name: string };
export type InitStrategyResponse = { ok: boolean; name: string };

export type StopStrategyPayload = { name: string };
export type StopStrategyResponse = { ok: boolean; name: string };

export type DeleteStrategyPayload = { name: string };
export type DeleteStrategyResponse = { ok: boolean; name: string };

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

export type SymbolSnapshot = {
  symbol: string;
  last_price: number;
  bid_price: number | null;
  ask_price: number | null;
  volume_24h: number | null;
  notional_24h: number | null;
  change_24h: number | null;
  price_precision: number | null;
  amount_precision: number | null;
  min_order_notional: number | null;
};

export type LogsTailResponse = { lines: string[] };
export type LogsStreamEvent = { line: string };

export type SystemStatus = { running: boolean; mode: 'mock' | 'real' | null };

export type PairsResponse = { pairs: string[] };

export type AllSymbolsResponse = { symbols: Record<string, SymbolSnapshot> };

