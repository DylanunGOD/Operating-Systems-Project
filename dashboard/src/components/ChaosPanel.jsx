import { useCallback, useEffect, useMemo, useState } from 'react'
import { chaosAPI } from '../api'
import styles from './ChaosPanel.module.css'

const ACTIVE_STATE = 'running'
const ACTIVE_POLL_MS = 1000
const IDLE_POLL_MS = 5000

export function ChaosPanel() {
  const [scenarios, setScenarios] = useState([])
  const [runs, setRuns] = useState([])
  const [selectedScenario, setSelectedScenario] = useState('')
  const [startingRun, setStartingRun] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [notice, setNotice] = useState(null)
  const [now, setNow] = useState(() => Date.now())

  const activeRun = useMemo(
    () => runs.find((run) => run.state === ACTIVE_STATE) || null,
    [runs]
  )

  const historyRuns = useMemo(() => {
    return runs
      .filter((run) => run.state !== ACTIVE_STATE)
      .slice()
      .sort((a, b) => {
        const ta = a.started_at ? new Date(a.started_at).getTime() : 0
        const tb = b.started_at ? new Date(b.started_at).getTime() : 0
        return tb - ta
      })
      .slice(0, 10)
  }, [runs])

  useEffect(() => {
    let cancelled = false
    chaosAPI
      .listScenarios()
      .then((response) => {
        if (cancelled) return
        const list = response.data || []
        setScenarios(list)
        if (list.length > 0) {
          setSelectedScenario((prev) => prev || list[0].id)
        }
      })
      .catch((err) => {
        console.error('Failed to load chaos scenarios:', err)
        if (!cancelled) {
          setNotice({ kind: 'error', text: 'No se pudieron cargar los escenarios.' })
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  const refreshRuns = useCallback(async () => {
    try {
      const response = await chaosAPI.listRuns()
      setRuns(response.data || [])
    } catch (err) {
      console.error('Failed to load chaos runs:', err)
    }
  }, [])

  useEffect(() => {
    refreshRuns()
    const interval = setInterval(
      refreshRuns,
      activeRun ? ACTIVE_POLL_MS : IDLE_POLL_MS
    )
    return () => clearInterval(interval)
  }, [refreshRuns, activeRun])

  useEffect(() => {
    if (!activeRun) return undefined
    const tick = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(tick)
  }, [activeRun])

  useEffect(() => {
    if (!notice) return undefined
    const t = setTimeout(() => setNotice(null), 5000)
    return () => clearTimeout(t)
  }, [notice])

  const selectedScenarioDetails = useMemo(
    () => scenarios.find((s) => s.id === selectedScenario) || null,
    [scenarios, selectedScenario]
  )

  const handleStart = useCallback(async () => {
    if (!selectedScenario || startingRun) return
    setStartingRun(true)
    setNotice(null)
    try {
      const response = await chaosAPI.startRun(selectedScenario)
      setNotice({
        kind: 'success',
        text: `Escenario iniciado (run ${response.data.run_id.slice(0, 8)}…).`,
      })
      await refreshRuns()
    } catch (err) {
      const status = err?.response?.status
      const detail = err?.response?.data?.detail || err.message
      if (status === 409) {
        setNotice({
          kind: 'warning',
          text: 'Ya hay un escenario en ejecución. Cancelalo antes de lanzar otro.',
        })
      } else if (status === 404) {
        setNotice({ kind: 'error', text: `Escenario desconocido: ${detail}` })
      } else {
        setNotice({ kind: 'error', text: `No se pudo iniciar: ${detail}` })
      }
    } finally {
      setStartingRun(false)
    }
  }, [selectedScenario, startingRun, refreshRuns])

  const handleCancel = useCallback(async () => {
    if (!activeRun || cancelling) return
    setCancelling(true)
    setNotice(null)
    try {
      await chaosAPI.cancelRun(activeRun.run_id)
      setNotice({ kind: 'success', text: 'Escenario cancelado.' })
      await refreshRuns()
    } catch (err) {
      const detail = err?.response?.data?.detail || err.message
      setNotice({ kind: 'error', text: `No se pudo cancelar: ${detail}` })
    } finally {
      setCancelling(false)
    }
  }, [activeRun, cancelling, refreshRuns])

  const elapsedSeconds = useMemo(() => {
    if (!activeRun?.started_at) return 0
    const started = new Date(activeRun.started_at).getTime()
    if (Number.isNaN(started)) return 0
    return Math.max(0, Math.floor((now - started) / 1000))
  }, [activeRun, now])

  const activeScenarioMeta = useMemo(() => {
    if (!activeRun) return null
    return scenarios.find((s) => s.id === activeRun.scenario_id) || null
  }, [activeRun, scenarios])

  const formatState = (state) => {
    switch (state) {
      case 'running':
        return 'En ejecución'
      case 'completed':
        return 'Completado'
      case 'cancelled':
        return 'Cancelado'
      case 'failed':
        return 'Fallido'
      default:
        return state || '-'
    }
  }

  const formatStarted = (iso) => {
    if (!iso) return '-'
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso
    return d.toLocaleTimeString()
  }

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h2>Chaos Engineering</h2>
        <p className={styles.subtitle}>
          Inyecta fallas controladas para probar la resiliencia del cluster.
        </p>
      </div>

      {notice && (
        <div className={`${styles.notice} ${styles[notice.kind]}`}>
          {notice.text}
        </div>
      )}

      <div className={styles.controls}>
        <label className={styles.field}>
          <span className={styles.fieldLabel}>Escenario</span>
          <select
            value={selectedScenario}
            onChange={(e) => setSelectedScenario(e.target.value)}
            disabled={scenarios.length === 0 || Boolean(activeRun)}
            className={styles.select}
          >
            {scenarios.length === 0 && <option value="">Cargando...</option>}
            {scenarios.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} · {s.duration_seconds}s
              </option>
            ))}
          </select>
        </label>

        <div className={styles.buttonRow}>
          <button
            type="button"
            className={styles.primary}
            onClick={handleStart}
            disabled={
              !selectedScenario || startingRun || Boolean(activeRun)
            }
          >
            {startingRun ? 'Iniciando…' : 'Ejecutar'}
          </button>
          <button
            type="button"
            className={styles.danger}
            onClick={handleCancel}
            disabled={!activeRun || cancelling}
          >
            {cancelling ? 'Cancelando…' : 'Cancelar'}
          </button>
        </div>
      </div>

      {selectedScenarioDetails && !activeRun && (
        <p className={styles.description}>
          {selectedScenarioDetails.description}
        </p>
      )}

      {activeRun && (
        <div className={styles.activeRun}>
          <div className={styles.activeHeader}>
            <span className={styles.liveDot} />
            <span className={styles.activeTitle}>
              {activeScenarioMeta?.name || activeRun.scenario_id}
            </span>
            <span className={styles.elapsed}>
              {elapsedSeconds}s
              {activeScenarioMeta?.duration_seconds
                ? ` / ${activeScenarioMeta.duration_seconds}s`
                : ''}
            </span>
          </div>
          <div className={styles.runId}>run {activeRun.run_id}</div>
          {activeRun.actions_executed?.length > 0 && (
            <ul className={styles.actionList}>
              {activeRun.actions_executed.map((action, idx) => (
                <li key={`${action.type}-${action.at_second}-${idx}`}>
                  <span className={styles.actionTime}>
                    t+{action.at_second}s
                  </span>
                  <span className={styles.actionName}>{action.type}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className={styles.history}>
        <h3>Historial</h3>
        {historyRuns.length === 0 ? (
          <p className={styles.empty}>Sin runs previos.</p>
        ) : (
          <table className={styles.historyTable}>
            <thead>
              <tr>
                <th>Escenario</th>
                <th>Inicio</th>
                <th>Estado</th>
                <th>Acciones</th>
              </tr>
            </thead>
            <tbody>
              {historyRuns.map((run) => (
                <tr key={run.run_id}>
                  <td>{run.scenario_id}</td>
                  <td>{formatStarted(run.started_at)}</td>
                  <td>
                    <span
                      className={`${styles.stateBadge} ${
                        styles[`state_${run.state}`] || ''
                      }`}
                    >
                      {formatState(run.state)}
                    </span>
                  </td>
                  <td>{run.actions_executed?.length ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
