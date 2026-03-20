import { useEffect, useState, Fragment, type FC } from 'react';
import { api } from '../lib/api';
import type { Holding, RunningStrategy } from '../lib/types';

interface StrategiesPanelProps {
  running: RunningStrategy[];
  holdings: Record<string, Holding>;
  onRefresh: () => Promise<void>;
}

export const StrategiesPanel: FC<StrategiesPanelProps> = ({
  running,
  holdings,
  onRefresh,
}) => {
  const getErrorMessage = (error: unknown): string =>
    error instanceof Error ? error.message : String(error)

  const [selectedName, setSelectedName] = useState<string>('')
  const [busy, setBusy] = useState<string>('')
  const [startingNames, setStartingNames] = useState<Set<string>>(() => new Set())
  const [actionErr, setActionErr] = useState<string>('')

  useEffect(() => {
    if (selectedName && !running.some((s) => s.name === selectedName)) {
      setSelectedName('')
    }
  }, [running, selectedName])

  const selectedHasOpenPos = (() => {
    const h = selectedName ? holdings[selectedName] : undefined
    if (!h) return false
    const ps = Object.values(h.positions || {})
    return ps.some((p) => (p.quantity || 0) !== 0)
  })()

  const pnlTextClass = (v: number) =>
    v > 0 ? 'text-emerald-400' : v < 0 ? 'text-rose-400' : 'text-slate-100'

  const positionsFor = (strategyName: string) => {
    const h = holdings[strategyName]
    const ps = Object.values(h?.positions || {}).filter((p) => (p.quantity || 0) !== 0)
    return ps
  }

  return (
  <div className="flex h-full w-full flex-col rounded-lg border border-white/10 bg-white/5 p-2 shadow-[0_4px_12px_rgba(0,0,0,0.4)]">
    <div className="mb-1.5 flex flex-wrap items-end gap-2">
      <div className="flex flex-1 flex-wrap items-center gap-1.5">
        <button
          className="inline-flex items-center justify-center gap-1 rounded border border-emerald-400/80 bg-emerald-500/10 px-2 py-1 text-xs font-medium text-emerald-100 transition hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={!selectedName || busy === 'start' || startingNames.has(selectedName)}
          onClick={async () => {
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
              await onRefresh()
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
          title="Start (auto-inits + backfills history as needed)"
        >
          Start
        </button>
        <button
          className="inline-flex items-center justify-center gap-1 rounded border border-rose-400/80 bg-rose-500/10 px-2 py-1 text-xs font-medium text-rose-100 transition hover:bg-rose-500/20 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={!selectedName || busy === selectedName}
          onClick={() => {
            if (selectedHasOpenPos) {
              window.alert('Cannot stop strategy while positions are open. Click “Close pos” first.')
              return
            }
            void (async () => {
              setBusy(selectedName)
              setActionErr('')
              try {
                await api.stopStrategy({ name: selectedName })
                await onRefresh()
              } catch (e: unknown) {
                setActionErr(getErrorMessage(e))
              } finally {
                setBusy('')
              }
            })()
          }}
          title="Stop the selected strategy"
        >
          Stop
        </button>
        <div className="ml-auto flex items-center gap-1.5">
          <button
            className="inline-flex items-center justify-center gap-1 rounded border border-amber-400/80 bg-amber-500/10 px-2 py-1 text-xs font-medium text-amber-100 transition hover:bg-amber-500/20 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!selectedName || busy === `${selectedName}-close`}
            onClick={() => {
              void (async () => {
                setBusy(`${selectedName}-close`)
                setActionErr('')
                try {
                  await api.closePositions({ name: selectedName })
                  await onRefresh()
                } catch (e: unknown) {
                  setActionErr(getErrorMessage(e))
                } finally {
                  setBusy('')
                }
              })()
            }}
            title="Market-close all positions for the selected strategy"
          >
            Close pos
          </button>
          <button
            className="inline-flex items-center justify-center gap-1 rounded border border-amber-400/50 bg-amber-500/5 px-2 py-1 text-xs font-medium text-amber-100 transition hover:bg-amber-500/15 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={running.length === 0 || busy === 'close-all'}
            onClick={() => {
              void (async () => {
                setBusy('close-all')
                setActionErr('')
                try {
                  const res = await api.closeAllPositions()
                  if (res?.errors && Object.keys(res.errors).length) {
                    setActionErr(`close_all: errors for ${Object.keys(res.errors).length} strategies`)
                  }
                  await onRefresh()
                } catch (e: unknown) {
                  setActionErr(getErrorMessage(e))
                } finally {
                  setBusy('')
                }
              })()
            }}
            title="Market-close all positions for all strategies"
          >
            Close all
          </button>
        </div>
      </div>
      {actionErr && (
        <div className="ml-auto font-mono text-[10px] text-rose-300">{actionErr}</div>
      )}
    </div>

    <div className="mt-1.5 flex-1 overflow-auto rounded border border-white/10 bg-black/40">
      <table className="w-full table-fixed border-collapse text-left">
        <thead>
          <tr className="bg-white/5 text-xs text-white/80">
            <th className="w-[25%] px-1.5 py-1 text-left">Name</th>
            <th className="w-[10%] px-1.5 py-1 text-right">Status</th>
            <th className="w-[14%] px-1.5 py-1 text-right">Symbol</th>
            <th className="w-[6%] px-1.5 py-1 text-right">Size</th>
            <th className="w-[11%] px-1.5 py-1 text-right">Total cost</th>
            <th className="w-[11%] px-1.5 py-1 text-right">Value</th>
            <th className="w-[11%] px-1.5 py-1 text-right">U PnL</th>
            <th className="w-[11%] px-1.5 py-1 text-right">R PnL</th>
            <th className="w-[11%] px-1.5 py-1 text-right">PnL</th>
          </tr>
        </thead>
        <tbody>
          {running.map((s) => (
            <Fragment key={s.name}>
              <tr
                key={s.name}
                className={[
                  'cursor-pointer border-t border-white/5 text-xs hover:bg-white/10',
                  selectedName === s.name ? 'bg-white/10' : '',
                ].join(' ')}
                onClick={() => setSelectedName(s.name)}
              >
                <td className="px-1.5 py-1 text-left font-mono text-xs text-slate-100">
                  {s.name}
                </td>
                <td className="px-1.5 py-1 text-right text-xs">
                {startingNames.has(s.name) ? (
                  <span className="inline-flex items-center gap-0.5 rounded border border-amber-400/80 bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-100">
                    <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
                    Starting
                  </span>
                ) : s.error ? (
                  <span className="inline-flex items-center gap-0.5 rounded border border-rose-400/80 bg-rose-500/10 px-1.5 py-0.5 text-[10px] text-rose-100">
                    <span className="h-1.5 w-1.5 rounded-full bg-rose-400" />
                    Error
                  </span>
                ) : s.started ? (
                  <span className="inline-flex items-center gap-0.5 rounded border border-emerald-400/80 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] text-emerald-100">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                    Running
                  </span>
                ) : s.inited ? (
                  <span className="inline-flex items-center gap-0.5 rounded border border-sky-400/80 bg-sky-500/10 px-1.5 py-0.5 text-[10px] text-sky-100">
                    <span className="h-1.5 w-1.5 rounded-full bg-sky-400" />
                    Inited
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-0.5 rounded border border-white/20 bg-white/5 px-1.5 py-0.5 text-[10px] text-slate-100">
                    <span className="h-1.5 w-1.5 rounded-full bg-slate-400" />
                    Created
                  </span>
                )}
                {s.error && s.error_msg && (
                  <div className="mt-0.5 font-mono text-[10px] text-white/60">
                    {s.error_msg}
                  </div>
                )}
                </td>
                <td className="px-1.5 py-1 text-right font-mono text-xs text-slate-100" />
                <td className="px-1.5 py-1 text-right font-mono text-xs text-slate-100" />
                <td className="px-1.5 py-1 text-right font-mono text-xs tabular-nums">
                  {' '}
                </td>
                <td className="px-1.5 py-1 text-right font-mono text-xs tabular-nums">
                  {' '}
                </td>
                <td className="px-1.5 py-1 text-right font-mono text-xs tabular-nums">
                  {' '}
                </td>
                <td className="px-1.5 py-1 text-right font-mono text-xs tabular-nums">
                  {' '}
                </td>
                <td className="px-1.5 py-1 text-right font-mono text-xs tabular-nums">
                  {' '}
                </td>
              </tr>

              <tr key={`${s.name}__posrow`} className="border-t border-white/5 bg-black/20">
                <td className="px-1.5 py-1 text-left font-mono text-[10px] text-white/50">
                  POS
                </td>
                <td className="px-1.5 py-1 text-right font-mono text-[10px] text-white/50">
                  {/* status column intentionally blank on position row */}
                  {' '}
                </td>
                {(() => {
                  const ps = positionsFor(s.name)
                  if (ps.length === 0) {
                    return (
                      <>
                        <td className="px-1.5 py-1 text-right font-mono text-xs text-white/70">FLAT</td>
                        <td className="px-1.5 py-1 text-right font-mono text-xs text-white/70" />
                      </>
                    )
                  }
                  return (
                    <>
                      <td className="px-1.5 py-1 text-right font-mono text-xs text-slate-100">
                        <div className="flex flex-col gap-0.5">
                          {ps.map((p) => (
                            <div key={p.symbol}>{p.symbol}</div>
                          ))}
                        </div>
                      </td>
                      <td className="px-1.5 py-1 text-right font-mono text-xs text-slate-100 tabular-nums">
                        <div className="flex flex-col gap-0.5">
                          {ps.map((p) => (
                            <div key={p.symbol}>{p.quantity}</div>
                          ))}
                        </div>
                      </td>
                    </>
                  )
                })()}
                <td className="px-1.5 py-1 text-right font-mono text-xs tabular-nums text-slate-100">
                  {holdings[s.name] ? (holdings[s.name].total_cost ?? 0).toFixed(2) : '-'}
                </td>
                <td className="px-1.5 py-1 text-right font-mono text-xs tabular-nums text-slate-100">
                  {holdings[s.name] ? (holdings[s.name].current_value ?? 0).toFixed(2) : '-'}
                </td>
                <td className="px-1.5 py-1 text-right font-mono text-xs tabular-nums">
                  {holdings[s.name] ? (
                    <span className={pnlTextClass(holdings[s.name].unrealized_pnl ?? 0)}>
                      {(holdings[s.name].unrealized_pnl ?? 0).toFixed(2)}
                    </span>
                  ) : '-'}
                </td>
                <td className="px-1.5 py-1 text-right font-mono text-xs tabular-nums">
                  {holdings[s.name] ? (
                    <span className={pnlTextClass(holdings[s.name].realized_pnl ?? 0)}>
                      {(holdings[s.name].realized_pnl ?? 0).toFixed(2)}
                    </span>
                  ) : '-'}
                </td>
                <td className="px-1.5 py-1 text-right font-mono text-xs tabular-nums">
                  {holdings[s.name] ? (
                    <span className={pnlTextClass(holdings[s.name].pnl ?? 0)}>
                      {(holdings[s.name].pnl ?? 0).toFixed(2)}
                    </span>
                  ) : '-'}
                </td>
              </tr>
            </Fragment>
          ))}
          {running.length === 0 && (
            <tr>
              <td
                colSpan={9}
                className="px-1.5 py-2 text-center text-xs text-white/70"
              >
                No running strategies (use the form above to start one).
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  </div>
  )
};

