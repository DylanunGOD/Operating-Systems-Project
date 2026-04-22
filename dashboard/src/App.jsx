import { useState, useEffect } from 'react'
import { JobsTable } from './components/JobsTable'
import { WorkersStatus } from './components/WorkersStatus'
import { metricsAPI } from './api'
import styles from './App.module.css'

function App() {
  const [metrics, setMetrics] = useState(null)
  const [loading, setLoading] = useState(true)
  const [isOnline, setIsOnline] = useState(true)

  useEffect(() => {
    fetchMetrics()
    const interval = setInterval(fetchMetrics, 5000)
    return () => clearInterval(interval)
  }, [])

  useEffect(() => {
    const handleOnline = () => setIsOnline(true)
    const handleOffline = () => setIsOnline(false)

    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)

    return () => {
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
    }
  }, [])

  const fetchMetrics = async () => {
    try {
      setLoading(true)
      const response = await metricsAPI.getMetrics()
      setMetrics(response.data)
      setIsOnline(true)
    } catch (error) {
      console.error('Error fetching metrics:', error)
      setIsOnline(false)
    } finally {
      setLoading(false)
    }
  }

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
              isOnline ? styles.online : styles.offline
            }`}
          />
          <span>{isOnline ? 'En línea' : 'Sin conexión'}</span>
        </div>
      </header>

      <main className={styles.main}>
        {metrics && (
          <section className={styles.metricsBar}>
            <div className={styles.metric}>
              <span className={styles.label}>Cola</span>
              <span className={styles.value}>{metrics.queue_length}</span>
            </div>
            <div className={styles.metric}>
              <span className={styles.label}>Total Jobs</span>
              <span className={styles.value}>{metrics.jobs_total}</span>
            </div>
            <div className={styles.metric}>
              <span className={styles.label}>Completados</span>
              <span className={`${styles.value} ${styles.success}`}>
                {metrics.jobs_completed}
              </span>
            </div>
            <div className={styles.metric}>
              <span className={styles.label}>Fallidos</span>
              <span className={`${styles.value} ${styles.danger}`}>
                {metrics.jobs_failed}
              </span>
            </div>
            <div className={styles.metric}>
              <span className={styles.label}>Procesando</span>
              <span className={`${styles.value} ${styles.primary}`}>
                {metrics.jobs_processing}
              </span>
            </div>
            <div className={styles.metric}>
              <span className={styles.label}>Workers</span>
              <span className={styles.value}>{metrics.workers_online}</span>
            </div>
            <div className={styles.metric}>
              <span className={styles.label}>Idle</span>
              <span className={`${styles.value} ${styles.success}`}>
                {metrics.workers_idle}
              </span>
            </div>
            <div className={styles.metric}>
              <span className={styles.label}>Busy</span>
              <span className={`${styles.value} ${styles.warning}`}>
                {metrics.workers_busy}
              </span>
            </div>
          </section>
        )}

        <div className={styles.content}>
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
