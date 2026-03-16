import { useEffect, useMemo, useRef, useState } from 'react';
import './App.css';
import { api } from './lib/api';
import type {
  Holding,
  RunningStrategy,
  SymbolSnapshot,
  LogsStreamEvent,
  SystemStatus,
} from './lib/types';
import { Sidebar, type Tab } from './components/Sidebar';
import { HeaderBar } from './components/HeaderBar';
import { SystemStatusPanel } from './components/HealthPanel';
import { StrategiesPanel } from './components/StrategiesPanel';
import { SymbolPanel } from './components/SymbolPanel';
import { LogsPanel } from './components/LogsPanel';

export default function App() {
  const [tab, setTab] = useState<Tab>('Strategies')
  const [health, setHealth] = useState<{ ok: boolean; env_mode?: string } | null>(null)
  const [healthErr, setHealthErr] = useState<string>('')

  const [available, setAvailable] = useState<string[]>([])
  const [running, setRunning] = useState<RunningStrategy[]>([])
  const [busy, setBusy] = useState<string>('')
  const [selectedName, setSelectedName] = useState<string>('')

  const [startStrategy, setStartStrategy] = useState<string>('Strat1Pine')
  const [startSymbol, setStartSymbol] = useState<string>('BTCUSDT')
  const [actionErr, setActionErr] = useState<string>('')

  const [positions, setPositions] = useState<Record<string, Holding>>({})
  const [allSymbols, setAllSymbols] = useState<Record<string, SymbolSnapshot>>({})
  const [pairs, setPairs] = useState<string[]>([])

  const [logs, setLogs] = useState<string[]>([])
  const [logsOn, setLogsOn] = useState<boolean>(true)
  const logBoxRef = useRef<HTMLDivElement>(null as unknown as HTMLDivElement)
  const [system, setSystem] = useState<SystemStatus>({ running: false, mode: null })

  const apiBase = api.baseUrl;

  const pills = useMemo(() => {
    const ok = health?.ok === true;
    const label = ok ? `OK (${health?.env_mode ?? 'unknown'})` : healthErr ? 'DOWN' : '…';
    return { ok, label };
  }, [health, healthErr]);

  async function refreshAll() {
    setActionErr('')
    try {
      const st = await api.systemStatus()
      setSystem(st)
      if (!st.running) {
        setHealth(null)
        setHealthErr('system not running')
        setAvailable([])
        setRunning([])
        setPositions({})
        return
      }

      const [h, a, r, p, pr] = await Promise.all([
        api.health(),
        api.availableStrategies(),
        api.runningStrategies(),
        api.positions(),
        api.pairs(),
      ])
      setHealth(h)
      setHealthErr('')
      setAvailable(a.available)
      setRunning(r.running)
      setPositions(p.holdings || {})
      setPairs(pr.pairs || [])
    } catch (e: any) {
      setHealth(null)
      setHealthErr(e?.message || String(e))
    }
  }

  useEffect(() => {
    refreshAll()
    const t = window.setInterval(() => refreshAll(), 3000)
    return () => window.clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (tab === 'Symbols') {
      api.symbols()
        .then((res) => setAllSymbols(res.symbols || {}))
        .catch(() => setAllSymbols({}))
      const t = window.setInterval(() => {
        api.symbols()
          .then((res) => setAllSymbols(res.symbols || {}))
          .catch(() => setAllSymbols({}))
      }, 2000)
      return () => window.clearInterval(t)
    }
    if (tab === 'Logs') {
      api.logsTail(200).then((r) => setLogs(r.lines)).catch(() => setLogs([]))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab])

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
    <div className="app">
      <Sidebar
        tab={tab}
        setTab={setTab}
        apiBase={apiBase}
        pills={pills}
      />

      <main className="main">
        <HeaderBar title={tab === 'Symbols' ? 'Symbols' : tab} onRefresh={refreshAll} />

        {tab === 'System' && (
          <SystemStatusPanel
            health={health}
            healthErr={healthErr}
            system={system}
            onStartMock={() => {
              api.systemStart('mock').then(() => refreshAll()).catch(() => {})
            }}
            onStartLive={() => {
              api.systemStart('real').then(() => refreshAll()).catch(() => {})
            }}
            onStopSystem={() => {
              api.systemStop().then(() => refreshAll()).catch(() => {})
            }}
          />
        )}

        {tab === 'Strategies' && (
          <StrategiesPanel
            available={available}
            running={running}
            activeNames={activeNames}
            holdings={positions}
            pairs={pairs}
            selectedName={selectedName}
            onSelect={(name) => setSelectedName(name)}
            startStrategy={startStrategy}
            setStartStrategy={setStartStrategy}
            startSymbol={startSymbol}
            setStartSymbol={setStartSymbol}
            busy={busy}
            actionErr={actionErr}
            onAdd={async () => {
              setBusy('add')
              setActionErr('')
              try {
                const res = await api.addStrategy({ strategy: startStrategy, symbol: startSymbol })
                setSelectedName(res.name)
                await refreshAll()
              } catch (e: any) {
                setActionErr(e?.message || String(e))
              } finally {
                setBusy('')
              }
            }}
            onInit={async (name: string) => {
              setBusy(name)
              setActionErr('')
              try {
                await api.initStrategy({ name })
                await refreshAll()
              } catch (e: any) {
                setActionErr(e?.message || String(e))
              } finally {
                setBusy('')
              }
            }}
            onStartSelected={async () => {
              if (!selectedName) return
              setBusy('start')
              setActionErr('')
              try {
                await api.startStrategyByName({ name: selectedName })
                await refreshAll()
              } catch (e: any) {
                setActionErr(e?.message || String(e))
              } finally {
                setBusy('')
              }
            }}
            onStop={async (name: string) => {
              setBusy(name)
              setActionErr('')
              try {
                await api.stopStrategy({ name })
                await refreshAll()
              } catch (e: any) {
                setActionErr(e?.message || String(e))
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
              } catch (e: any) {
                setActionErr(e?.message || String(e))
              } finally {
                setBusy('')
              }
            }}
          />
        )}

        {tab === 'Symbols' && (
          <SymbolPanel symbols={allSymbols} />
        )}

        {tab === 'Logs' && (
          <LogsPanel
            logs={logs}
            logsOn={logsOn}
            setLogsOn={setLogsOn}
            onTail={() => api.logsTail(200).then((r) => setLogs(r.lines)).catch(() => {})}
            onClear={() => setLogs([])}
            logBoxRef={logBoxRef}
          />
        )}
      </main>
    </div>
  )
}
