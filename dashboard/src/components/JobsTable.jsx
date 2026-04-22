import { useState, useEffect } from 'react'
import { jobsAPI } from '../api'
import styles from './JobsTable.module.css'

export function JobsTable() {
  const [jobs, setJobs] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [statusFilter, setStatusFilter] = useState('')

  useEffect(() => {
    fetchJobs()
    const interval = setInterval(fetchJobs, 2000)
    return () => clearInterval(interval)
  }, [statusFilter])

  const fetchJobs = async () => {
    try {
      setLoading(true)
      const response = await jobsAPI.getJobs(statusFilter || undefined)
      setJobs(response.data.jobs || [])
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const getStatusBadgeClass = (status) => {
    return `badge badge-${
      status === 'completed'
        ? 'success'
        : status === 'failed'
        ? 'danger'
        : status === 'processing'
        ? 'primary'
        : 'warning'
    }`
  }

  const formatDate = (dateString) => {
    if (!dateString) return '-'
    return new Date(dateString).toLocaleString()
  }

  const formatBytes = (bytes) => {
    if (!bytes) return '-'
    return (bytes / 1024 / 1024).toFixed(2) + ' MB'
  }

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h2>Jobs</h2>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className={styles.filter}
        >
          <option value="">Todos los estados</option>
          <option value="pending">Pendiente</option>
          <option value="queued">Encolado</option>
          <option value="processing">Procesando</option>
          <option value="completed">Completado</option>
          <option value="failed">Fallido</option>
        </select>
      </div>

      {loading && <div className={styles.loading}>Cargando...</div>}
      {error && <div className={styles.error}>Error: {error}</div>}

      {!loading && jobs.length === 0 && (
        <div className={styles.empty}>No hay jobs para mostrar</div>
      )}

      {!loading && jobs.length > 0 && (
        <div className={styles.tableWrapper}>
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Tipo</th>
                <th>Estado</th>
                <th>Progreso</th>
                <th>Worker</th>
                <th>Creado</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.id}>
                  <td className={styles.jobId}>
                    {job.id.substring(0, 8)}...
                  </td>
                  <td>{job.type}</td>
                  <td>
                    <span className={getStatusBadgeClass(job.status)}>
                      {job.status}
                    </span>
                  </td>
                  <td>
                    <div className={styles.progressBar}>
                      <div
                        className={styles.progressFill}
                        style={{ width: `${job.progress}%` }}
                      />
                      <span className={styles.progressText}>
                        {job.progress}%
                      </span>
                    </div>
                  </td>
                  <td>{job.worker_id || '-'}</td>
                  <td>{formatDate(job.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
