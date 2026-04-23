import { useEffect, useState } from 'react'
import { JobsTable } from './components/JobsTable'
import { WorkersStatus } from './components/WorkersStatus'
import { ChaosPanel } from './components/ChaosPanel'
import {
  useJobCounts,
  useQueueSnapshot,
  useRealtime,
} from './store/RealtimeContext'
import styles from './App.module.css'

function App() {
  const queue = useQueueSnapshot()
  const jobCounts = useJobCounts()
  const { isConnected } = useRealtime()
  const [isBrowserOnline, setIsBrowserOnline] = useState(
    typeof navigator === 'undefined' ? true : navigator.onLine
  )

  useEffect(() => {
    const handleOnline = () => setIsBrowserOnline(true)
    const handleOffline = () => setIsBrowserOnline(false)

    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)

    return () => {
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
    }
  }, [])

  const online = isBrowserOnline && isConnected

  return (
    <div className={styles.app}>
      <header className={styles.header}>
        <div className={styles.headerContent}>
          <h1>🎬 Multimedia Distributed</h1>
          <p>Plataforma de procesamiento distribuido de multimedia</p>
        </div>
        <div className={styles.status}>
          <div
            className={`${styles.statusIndicator} ${
              online ? styles.online : styles.offline
            }`}
          />
          <span>
            {!isBrowserOnline
              ? 'Sin conexión'
              : isConnected
              ? 'En línea'
              : 'Reconectando…'}
          </span>
        </div>
      </header>

      <main className={styles.main}>
        <section className={styles.metricsBar}>
          <div className={styles.metric}>
            <span className={styles.label}>Cola</span>
            <span className={styles.value}>{queue?.queue_length ?? '—'}</span>
          </div>
          <div className={styles.metric}>
            <span className={styles.label}>Total Jobs</span>
            <span className={styles.value}>{jobCounts.total}</span>
          </div>
          <div className={styles.metric}>
            <span className={styles.label}>Completados</span>
            <span className={`${styles.value} ${styles.success}`}>
              {jobCounts.completed}
            </span>
          </div>
          <div className={styles.metric}>
            <span className={styles.label}>Fallidos</span>
            <span className={`${styles.value} ${styles.danger}`}>
              {jobCounts.failed}
            </span>
          </div>
          <div className={styles.metric}>
            <span className={styles.label}>Procesando</span>
            <span className={`${styles.value} ${styles.primary}`}>
              {jobCounts.processing}
            </span>
          </div>
          <div className={styles.metric}>
            <span className={styles.label}>Workers</span>
            <span className={styles.value}>
              {queue?.workers_online ?? '—'}
            </span>
          </div>
          <div className={styles.metric}>
            <span className={styles.label}>Idle</span>
            <span className={`${styles.value} ${styles.success}`}>
              {queue?.workers_idle ?? '—'}
            </span>
          </div>
          <div className={styles.metric}>
            <span className={styles.label}>Busy</span>
            <span className={`${styles.value} ${styles.warning}`}>
              {queue?.workers_busy ?? '—'}
            </span>
          </div>
        </section>

        <div className={styles.content}>
          <ChaosPanel />
          <WorkersStatus />
          <JobsTable />
        </div>
      </main>

      <footer className={styles.footer}>
        <p>
          Sistema operativo distribuido - Procesamiento de multimedia en
          paralelo
        </p>
        <p>API: {import.meta.env.VITE_API_URL || 'http://localhost:8000'}</p>
      </footer>
    </div>
  )
}

export default App
