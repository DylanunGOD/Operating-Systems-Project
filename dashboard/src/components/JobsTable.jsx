import { useMemo, useState } from 'react'
import { useJobs } from '../store/RealtimeContext'
import styles from './JobsTable.module.css'

export function JobsTable() {
  const { jobs, initialized } = useJobs()
  const [statusFilter, setStatusFilter] = useState('')

  const visibleJobs = useMemo(() => {
    if (!statusFilter) return jobs
    return jobs.filter((job) => job.status === statusFilter)
  }, [jobs, statusFilter])

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
    const d = new Date(dateString)
    if (Number.isNaN(d.getTime())) return '-'
    return d.toLocaleString()
  }

  const formatJobId = (id) => {
    if (!id) return '-'
    const s = String(id)
    return s.length > 8 ? `${s.substring(0, 8)}...` : s
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

      {!initialized && <div className={styles.loading}>Cargando...</div>}

      {initialized && visibleJobs.length === 0 && (
        <div className={styles.empty}>No hay jobs para mostrar</div>
      )}

      {initialized && visibleJobs.length > 0 && (
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
              {visibleJobs.map((job) => (
                <tr key={job.id}>
                  <td className={styles.jobId}>{formatJobId(job.id)}</td>
                  <td>{job.type || '-'}</td>
                  <td>
                    <span className={getStatusBadgeClass(job.status)}>
                      {job.status || '-'}
                    </span>
                  </td>
                  <td>
                    <div className={styles.progressBar}>
                      <div
                        className={styles.progressFill}
                        style={{ width: `${job.progress || 0}%` }}
                      />
                      <span className={styles.progressText}>
                        {job.progress || 0}%
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
