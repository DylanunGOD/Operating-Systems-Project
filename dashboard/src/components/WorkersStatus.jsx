import { useState, useEffect } from 'react'
import { workersAPI } from '../api'
import styles from './WorkersStatus.module.css'

export function WorkersStatus() {
  const [workers, setWorkers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetchWorkers()
    const interval = setInterval(fetchWorkers, 3000)
    return () => clearInterval(interval)
  }, [])

  const fetchWorkers = async () => {
    try {
      setLoading(true)
      const response = await workersAPI.getWorkers()
      setWorkers(response.data.workers || [])
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const getStatusColor = (status) => {
    switch (status) {
      case 'idle':
        return '#10b981'
      case 'busy':
        return '#f59e0b'
      default:
        return '#6b7280'
    }
  }

  const getStatusText = (status) => {
    switch (status) {
      case 'idle':
        return 'Disponible'
      case 'busy':
        return 'Ocupado'
      default:
        return 'Desconectado'
    }
  }

  return (
    <div className={styles.container}>
      <h2>Workers</h2>

      {loading && <div className={styles.loading}>Cargando...</div>}
      {error && <div className={styles.error}>Error: {error}</div>}

      {!loading && workers.length === 0 && (
        <div className={styles.empty}>No hay workers conectados</div>
      )}

      {!loading && workers.length > 0 && (
        <div className={styles.grid}>
          {workers.map((worker) => (
            <div key={worker.id} className={styles.card}>
              <div className={styles.header}>
                <h3>{worker.id}</h3>
                <div
                  className={styles.statusIndicator}
                  style={{ backgroundColor: getStatusColor(worker.status) }}
                  title={getStatusText(worker.status)}
                />
              </div>

              <div className={styles.details}>
                <div className={styles.detailRow}>
                  <span className={styles.label}>Estado:</span>
                  <span className={styles.value}>
                    {getStatusText(worker.status)}
                  </span>
                </div>

                <div className={styles.detailRow}>
                  <span className={styles.label}>CPU:</span>
                  <div className={styles.meterContainer}>
                    <div
                      className={styles.meter}
                      style={{
                        width: `${Math.min(
                          worker.cpu_percent || 0,
                          100
                        )}%`,
                        backgroundColor:
                          worker.cpu_percent > 80
                            ? '#ef4444'
                            : worker.cpu_percent > 50
                            ? '#f59e0b'
                            : '#10b981',
                      }}
                    />
                  </div>
                  <span className={styles.percent}>
                    {Math.round(worker.cpu_percent || 0)}%
                  </span>
                </div>

                <div className={styles.detailRow}>
                  <span className={styles.label}>RAM:</span>
                  <div className={styles.meterContainer}>
                    <div
                      className={styles.meter}
                      style={{
                        width: `${Math.min(
                          worker.mem_percent || 0,
                          100
                        )}%`,
                        backgroundColor:
                          worker.mem_percent > 80
                            ? '#ef4444'
                            : worker.mem_percent > 50
                            ? '#f59e0b'
                            : '#10b981',
                      }}
                    />
                  </div>
                  <span className={styles.percent}>
                    {Math.round(worker.mem_percent || 0)}%
                  </span>
                </div>

                <div className={styles.detailRow}>
                  <span className={styles.label}>Jobs completados:</span>
                  <span className={styles.value}>{worker.jobs_done}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
