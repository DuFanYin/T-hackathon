import { useEffect, useRef, useState, type ReactNode } from 'react';
import './App.css';
import { api } from './lib/api';
import type {
  Holding,
  RunningStrategy,
  SystemStatus,
} from './lib/types';
import { Sidebar, type Tab } from './components/Sidebar';
import { StrategiesPanel } from './components/StrategiesPanel';
import { AccountValuePanel } from './components/AccountValuePanel';
import { OrdersPanel } from './components/OrdersPanel';
import { LogsPanel } from './components/LogsPanel';

function HeaderBar({ title, extra }: { title: string; extra?: ReactNode }) {
  return (
    <div className="mb-0.5 flex items-center justify-between gap-2">
      <div>
        <h1 className="m-0 text-sm font-medium tracking-tight text-slate-50">{title}</h1>
      </div>
      <div className="flex flex-wrap items-center gap-2">{extra}</div>
    </div>
  )
}

export default function App() {
  return <AppShell />
}

function AppShell() {
  const getErrorMessage = (error: unknown): string =>
    error instanceof Error ? error.message : String(error)

  const [tab, setTab] = useState<Tab>('Strategies')

  const [running, setRunning] = useState<RunningStrategy[]>([])

  const [positions, setPositions] = useState<Record<string, Holding>>({})
  const [accountBalance, setAccountBalance] = useState<unknown>(null)
  const [accountOrders, setAccountOrders] = useState<unknown>(null)
  const [accountPnl, setAccountPnl] = useState<{ equity: number; init_balance: number; pnl: number; pnl_pct: number } | null>(null)
  const [accountErr, setAccountErr] = useState<string>('')

  const LOGS_CACHE_KEY = 't_logs_cache'
  const LOGS_CACHE_MAX = 500
  const LOG_START_EPOCH_KEY = 't_log_start_epoch_ms'

  const [logs, setLogs] = useState<string[]>(() => {
    try {
      const c = window.localStorage.getItem(LOGS_CACHE_KEY)
      return c ? JSON.parse(c) : []
    } catch {
      return []
    }
  })
  const [logStartEpochMs, setLogStartEpochMs] = useState<number | null>(() => {
    try {
      const v = window.localStorage.getItem(LOG_START_EPOCH_KEY)
      if (!v) return null
      const n = Number(v)
      return Number.isFinite(n) ? n : null
    } catch {
      return null
    }
  })
  const logBoxRef = useRef<HTMLDivElement>(null as unknown as HTMLDivElement)
  const [system, setSystem] = useState<SystemStatus>({ running: false, mode: null })
  const [backendOk, setBackendOk] = useState<boolean>(false)
  const apiBase = api.baseUrl;

  function handleEngineStart() {
    // User clicked Mock/Live: from this moment onwards only show log lines.
    // We store an epoch (ms) and clear current log buffer immediately.
    const epochMs = Math.floor(Date.now() / 1000) * 1000
    setLogStartEpochMs(epochMs)
    try {
      window.localStorage.setItem(LOG_START_EPOCH_KEY, String(epochMs))
    } catch {
      // ignore
    }
    setLogs([])
  }

  async function refreshAll() {
    try {
      const st = await api.systemStatus()
      setSystem(st)
      setBackendOk(true)
      if (!st.running) {
        // Backend is reachable but engine is stopped; clear engine-derived state.
        setRunning([])
        setPositions({})
        setAccountBalance(null)
        setAccountOrders(null)
        setAccountErr('')
        return
      }

      const [r, p] = await Promise.all([
        api.runningStrategies(),
        api.positions(),
      ])
      setRunning(r.running)
      setPositions(p.holdings || {})

      try {
        const [b, o, pnl] = await Promise.all([
          api.accountBalance(),
          api.accountOrders(),
          api.accountPnl(),
        ])
        setAccountBalance(b.balance)
        setAccountOrders(o.orders)
        setAccountPnl(pnl)
        setAccountErr('')
      } catch (e: unknown) {
        setAccountErr(getErrorMessage(e))
      }
    } catch {
      setBackendOk(false)
    }
  }

  useEffect(() => {
    refreshAll()
    const t = window.setInterval(() => refreshAll(), 3000)
    return () => window.clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function refreshLogs() {
    api.logsTail(200).then((r) => setLogs(r.lines)).catch(() => setLogs([]))
  }

  useEffect(() => {
    if (tab !== 'Logs') return
    const el = logBoxRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [logs, tab])

  useEffect(() => {
    try {
      const toStore = logs.slice(-LOGS_CACHE_MAX)
      window.localStorage.setItem(LOGS_CACHE_KEY, JSON.stringify(toStore))
    } catch {
      /* ignore */
    }
  }, [logs])

  return (
    <div className="grid h-screen w-screen grid-cols-[260px,minmax(0,1fr)] bg-[#050505] text-slate-100">
      <Sidebar
        tab={tab}
        setTab={setTab}
        apiBase={apiBase}
        backendOk={backendOk}
        engineMode={system.mode}
        systemRunning={system.running}
        holdings={positions}
        running={running}
        onRefresh={refreshAll}
        onEngineStart={handleEngineStart}
      />

      <main className="flex h-screen w-full flex-col gap-2 overflow-hidden bg-gradient-to-br from-slate-950 via-slate-950 to-slate-900 px-2 py-2 sm:px-3">
        <HeaderBar title={tab} />

        <section className="flex w-full flex-1 flex-col overflow-hidden">
          {tab === 'Strategies' && (
            <div className="flex h-full w-full flex-col gap-2 overflow-hidden">
              <div className="grid min-h-0 flex-[1] grid-cols-1 gap-2 overflow-hidden md:grid-cols-[7fr_3fr]">
                <div className="min-h-0 overflow-hidden">
                  <StrategiesPanel
                    running={running}
                    holdings={positions}
                    onRefresh={refreshAll}
                  />
                </div>
                <div className="min-h-0 overflow-hidden">
                  <AccountValuePanel
                    engineRunning={system.running}
                    err={accountErr}
                    balance={accountBalance}
                    pnl={accountPnl}
                  />
                </div>
              </div>
              <div className="min-h-0 flex-[1] overflow-hidden">
                <OrdersPanel
                  engineRunning={system.running}
                  orders={accountOrders}
                />
              </div>
            </div>
          )}

          {tab === 'Logs' && (
          <LogsPanel
            logs={logs}
            onTail={refreshLogs}
            onClear={() => setLogs([])}
            logBoxRef={logBoxRef}
            logStartEpochMs={logStartEpochMs}
          />
          )}
        </section>
      </main>
    </div>
  )
}
