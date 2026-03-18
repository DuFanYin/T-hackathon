import { useEffect, useRef, useState } from 'react';
import './App.css';
import { api, setAdminToken } from './lib/api';
import type {
  Holding,
  RunningStrategy,
  LogsStreamEvent,
  OrderRow,
  SystemStatus,
} from './lib/types';
import { Sidebar, type Tab } from './components/Sidebar';
import { HeaderBar } from './components/HeaderBar';
import { StrategiesPanel } from './components/StrategiesPanel';
import { AccountPanel } from './components/AccountPanel';
import { OrdersPanel } from './components/OrdersPanel';
import { LogsPanel } from './components/LogsPanel';

export default function App() {
  const getErrorMessage = (error: unknown): string =>
    error instanceof Error ? error.message : String(error)

  const [tab, setTab] = useState<Tab>('Strategies')

  const [available, setAvailable] = useState<string[]>([])
  const [running, setRunning] = useState<RunningStrategy[]>([])
  const [busy, setBusy] = useState<string>('')
  const [selectedName, setSelectedName] = useState<string>('')

  const [startStrategy, setStartStrategy] = useState<string>('Strat1Pine')
  const [actionErr, setActionErr] = useState<string>('')
  const [startingNames, setStartingNames] = useState<Set<string>>(() => new Set())

  const [positions, setPositions] = useState<Record<string, Holding>>({})
  const [accountBalance, setAccountBalance] = useState<unknown>(null)
  const [accountPendingCount, setAccountPendingCount] = useState<unknown>(null)
  const [accountOrders, setAccountOrders] = useState<unknown>(null)
  const [accountErr, setAccountErr] = useState<string>('')

  const [ordersRows, setOrdersRows] = useState<OrderRow[]>([])
  const [ordersErr, setOrdersErr] = useState<string>('')
  const [ordersStrategy, setOrdersStrategy] = useState<string>('')
  const [ordersSymbol, setOrdersSymbol] = useState<string>('')
  const [ordersLimit, setOrdersLimit] = useState<number>(500)
  const [ordersBusy, setOrdersBusy] = useState<boolean>(false)

  const [logs, setLogs] = useState<string[]>([])
  const [logsOn] = useState<boolean>(true)
  const logBoxRef = useRef<HTMLDivElement>(null as unknown as HTMLDivElement)
  const [system, setSystem] = useState<SystemStatus>({ running: false, mode: null })
  const [backendOk, setBackendOk] = useState<boolean>(false)
  const [adminToken, setAdminTokenState] = useState<string | null>(() => {
    try {
      return window.localStorage.getItem('t_admin_token') || null
    } catch {
      return null
    }
  })

  const apiBase = api.baseUrl;

  const isAuthed = !!adminToken

  useEffect(() => {
    setAdminToken(adminToken || null)
    try {
      if (adminToken) {
        window.localStorage.setItem('t_admin_token', adminToken)
      } else {
        window.localStorage.removeItem('t_admin_token')
      }
    } catch {
      // ignore
    }
  }, [adminToken])

  async function refreshAll() {
    setActionErr('')
    try {
      const st = await api.systemStatus()
      setSystem(st)
      setBackendOk(true)
      if (!st.running) {
        // Backend is reachable but engine is stopped; clear engine-derived state.
        setAvailable([])
        setRunning([])
        setPositions({})
        setAccountBalance(null)
        setAccountPendingCount(null)
        setAccountOrders(null)
        setAccountErr('')
        return
      }

      const [a, r, p] = await Promise.all([
        api.availableStrategies(),
        api.runningStrategies(),
        api.positions(),
      ])
      setAvailable(a.available)
      setRunning(r.running)
      setPositions(p.holdings || {})

      if (isAuthed) {
        try {
          const [b, pc, o] = await Promise.all([
            api.accountBalance(),
            api.accountPendingCount(),
            api.accountOrders(true, 200),
          ])
          setAccountBalance(b.balance)
          setAccountPendingCount(pc.pending_count)
          setAccountOrders(o.orders)
          setAccountErr('')
        } catch (e: unknown) {
          setAccountErr(getErrorMessage(e))
        }
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

  useEffect(() => {
    if (tab === 'Logs') {
      api.logsTail(200).then((r) => setLogs(r.lines)).catch(() => setLogs([]))
    }
  }, [tab])

  async function refreshOrdersOnce() {
    if (!isAuthed) {
      setOrdersRows([])
      setOrdersErr('')
      return
    }
    setOrdersBusy(true)
    try {
      const r = await api.orders(ordersStrategy.trim() || undefined, ordersSymbol.trim() || undefined, ordersLimit)
      setOrdersRows((r.rows || []) as OrderRow[])
      setOrdersErr('')
    } catch (e: unknown) {
      setOrdersErr(getErrorMessage(e))
      setOrdersRows([])
    } finally {
      setOrdersBusy(false)
    }
  }

  useEffect(() => {
    if (tab !== 'Orders') return
    if (!isAuthed) {
      setOrdersRows([])
      setOrdersErr('')
      return
    }
    refreshOrdersOnce()
    const t = window.setInterval(() => {
      refreshOrdersOnce()
    }, 3000)
    return () => window.clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, isAuthed, ordersStrategy, ordersSymbol, ordersLimit])

  useEffect(() => {
    if (!logsOn) return
    const es = new EventSource(api.logsStreamUrl())
    es.onmessage = (evt) => {
      try {
        const parsed = JSON.parse(evt.data) as LogsStreamEvent
        if (parsed?.line) {
          setLogs((prev) => {
            const next = prev.length >= 2000 ? prev.slice(-1800) : prev
            return [...next, parsed.line]
          })
        }
      } catch {
        // ignore
      }
    }
    es.onerror = () => {
      // Keep EventSource alive; browser will reconnect automatically.
    }
    return () => es.close()
  }, [logsOn])

  useEffect(() => {
    if (tab !== 'Logs') return
    const el = logBoxRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [logs, tab])

  const activeNames = new Set(running.map((s) => s.name))
  useEffect(() => {
    // If selected strategy is gone (deleted), clear selection.
    if (selectedName && !running.some((s) => s.name === selectedName)) {
      setSelectedName('')
    }
  }, [running, selectedName])

  return (
    <div className="grid h-screen w-screen grid-cols-[260px,minmax(0,1fr)] bg-[#050505] text-slate-100">
      <Sidebar
        tab={tab}
        setTab={setTab}
        apiBase={apiBase}
        backendOk={backendOk}
        engineMode={system.mode}
        systemRunning={system.running}
        isAuthed={isAuthed}
        onLogin={async (token) => {
          const ok = await api.checkAdmin(token)
          if (ok) {
            setAdminTokenState(token)
            return true
          } else {
            // keep locked
            // simple feedback for now
            window.alert('Invalid admin token')
            return false
          }
        }}
        onLogout={() => setAdminTokenState(null)}
        onStartMock={() => {
          api.systemStart('mock').then(() => refreshAll()).catch(() => {})
        }}
        onStartLive={() => {
          api.systemStart('real').then(() => refreshAll()).catch(() => {})
        }}
        onStopSystem={async () => {
          const anyOpen = Object.values(positions || {}).some((holding) => {
            const positionRows = Object.values(holding?.positions || {})
            return positionRows.some((position) => (position?.quantity || 0) !== 0)
          })
          const anyStarted = running.some((s) => s.started)

          if (anyOpen) {
            window.alert('You must close positions before stopping strategies (use “Close pos” / “Close all”).')
            return
          }
          if (anyStarted) {
            window.alert('You must stop all strategies before stopping the engine.')
            return
          }

          const token =
            window.prompt(
              'This is a dangerous action.\n\nEnter admin code to proceed:',
            ) || ''
          const trimmed = token.trim()
          if (!trimmed) return
          const ok = await api.checkAdmin(trimmed)
          if (!ok) {
            window.alert('Invalid admin token')
            return
          }
          setAdminTokenState(trimmed)
          try {
            await api.systemStop()
            await refreshAll()
          } catch (e: unknown) {
            window.alert(getErrorMessage(e))
          }
        }}
      />

      <main className="flex h-screen w-full flex-col gap-4 overflow-hidden bg-gradient-to-br from-slate-950 via-slate-950 to-slate-900 px-3 py-4 sm:px-5">
        <HeaderBar title={tab} />

        <section className="flex w-full flex-1 flex-col overflow-hidden">
          {tab === 'Strategies' && (
            <StrategiesPanel
              available={available}
              running={running}
              activeNames={activeNames}
              holdings={positions}
              selectedName={selectedName}
              onSelect={(name) => setSelectedName(name)}
              isAuthed={isAuthed}
              startStrategy={startStrategy}
              setStartStrategy={setStartStrategy}
              busy={busy}
              startingNames={startingNames}
              actionErr={actionErr}
              onAdd={async () => {
                setBusy('add')
                setActionErr('')
                try {
                  const res = await api.addStrategy({ strategy: startStrategy })
                  setSelectedName(res.name)
                  await refreshAll()
                } catch (e: unknown) {
                  setActionErr(getErrorMessage(e))
                } finally {
                  setBusy('')
                }
              }}
              onStartSelected={async () => {
                if (!selectedName) return
                setBusy('start')
                setActionErr('')
                setStartingNames((prev) => {
                  const next = new Set(prev)
                  next.add(selectedName)
                  return next
                })
                try {
                  await api.startStrategyByName({ name: selectedName })
                  await refreshAll()
                } catch (e: unknown) {
                  setActionErr(getErrorMessage(e))
                } finally {
                  setStartingNames((prev) => {
                    const next = new Set(prev)
                    next.delete(selectedName)
                    return next
                  })
                  setBusy('')
                }
              }}
              onStop={async (name: string) => {
                setBusy(name)
                setActionErr('')
                try {
                  await api.stopStrategy({ name })
                  await refreshAll()
                } catch (e: unknown) {
                  setActionErr(getErrorMessage(e))
                } finally {
                  setBusy('')
                }
              }}
              onClosePositions={async (name: string) => {
                setBusy(`${name}-close`)
                setActionErr('')
                try {
                  await api.closePositions({ name })
                  await refreshAll()
                } catch (e: unknown) {
                  setActionErr(getErrorMessage(e))
                } finally {
                  setBusy('')
                }
              }}
              onCloseAllPositions={async () => {
                setBusy('close-all')
                setActionErr('')
                try {
                  const res = await api.closeAllPositions()
                  if (res?.errors && Object.keys(res.errors).length) {
                    setActionErr(`close_all: errors for ${Object.keys(res.errors).length} strategies`)
                  }
                  await refreshAll()
                } catch (e: unknown) {
                  setActionErr(getErrorMessage(e))
                } finally {
                  setBusy('')
                }
              }}
              onDelete={async (name: string) => {
                setBusy(`${name}-del`)
                setActionErr('')
                try {
                  await api.deleteStrategy({ name })
                  await refreshAll()
                } catch (e: unknown) {
                  setActionErr(getErrorMessage(e))
                } finally {
                  setBusy('')
                }
              }}
            />
          )}

          {tab === 'Account' && (
            <AccountPanel
              isAuthed={isAuthed}
              engineRunning={system.running}
              err={accountErr}
              balance={accountBalance}
              pendingCount={accountPendingCount}
              orders={accountOrders}
            />
          )}

          {tab === 'Orders' && (
            <OrdersPanel
              isAuthed={isAuthed}
              busy={ordersBusy}
              strategy={ordersStrategy}
              setStrategy={setOrdersStrategy}
              symbol={ordersSymbol}
              setSymbol={setOrdersSymbol}
              limit={ordersLimit}
              setLimit={setOrdersLimit}
              err={ordersErr}
              rows={ordersRows}
              onRefresh={() => { refreshOrdersOnce().catch(() => {}) }}
            />
          )}

          {tab === 'Logs' && (
          <LogsPanel
            logs={logs}
            isAuthed={isAuthed}
            onTail={() => api.logsTail(200).then((r) => setLogs(r.lines)).catch(() => {})}
            onClear={() => setLogs([])}
            logBoxRef={logBoxRef}
          />
          )}
        </section>
      </main>
    </div>
  )
}
