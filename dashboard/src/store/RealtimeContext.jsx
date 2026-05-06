import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
} from 'react'
import { jobsAPI, workersAPI } from '../api'
import { useWebSocket } from '../hooks/useWebSocket'

const JOBS_REFRESH_INTERVAL_MS = 15000
const WORKERS_REFRESH_INTERVAL_MS = 3000

const initialState = {
  jobsById: {},
  workersById: {},
  queueSnapshot: null,
  jobsInitialized: false,
  workersInitialized: false,
}

function mergeJob(prev, event) {
  const base = prev || { id: event.job_id }
  return { ...base, ...event, id: base.id || event.job_id }
}

function realtimeReducer(state, action) {
  switch (action.type) {
    case 'jobs/hydrate': {
      const next = {}
      for (const job of action.jobs) next[job.id] = job
      return { ...state, jobsById: next, jobsInitialized: true }
    }

    case 'workers/hydrate': {
      const next = {}
      for (const worker of action.workers) next[worker.id] = worker
      return { ...state, workersById: next, workersInitialized: true }
    }

    case 'ws/job_started':
    case 'ws/job_progress':
    case 'ws/job_completed':
    case 'ws/job_failed': {
      const { event } = action
      const prev = state.jobsById[event.job_id]
      const type = action.type.split('/')[1]

      const patch = {
        id: event.job_id,
        worker_id: event.worker_id ?? prev?.worker_id,
      }
      if (type === 'job_started') {
        patch.status = 'processing'
        patch.started_at = event.timestamp ?? prev?.started_at
        patch.progress = prev?.progress ?? 0
      } else if (type === 'job_progress') {
        patch.status = prev?.status === 'processing' ? prev.status : 'processing'
        patch.progress = event.progress
      } else if (type === 'job_completed') {
        patch.status = 'completed'
        patch.progress = 100
        patch.completed_at = event.timestamp ?? prev?.completed_at
        patch.output_path = event.output_path ?? prev?.output_path
      } else if (type === 'job_failed') {
        patch.status = 'failed'
        patch.completed_at = event.timestamp ?? prev?.completed_at
        patch.error = event.error ?? prev?.error
      }

      return {
        ...state,
        jobsById: {
          ...state.jobsById,
          [event.job_id]: mergeJob(prev, patch),
        },
      }
    }

    case 'ws/queue_snapshot': {
      const {
        queue_length,
        queue_by_priority,
        workers_online,
        workers_idle,
        workers_busy,
      } = action.event
      return {
        ...state,
        queueSnapshot: {
          queue_length,
          queue_by_priority: queue_by_priority || null,
          workers_online,
          workers_idle,
          workers_busy,
        },
      }
    }

    default:
      return state
  }
}

const RealtimeContext = createContext(null)

export function RealtimeProvider({ children }) {
  const [state, dispatch] = useReducer(realtimeReducer, initialState)
  const dispatchRef = useRef(dispatch)
  dispatchRef.current = dispatch

  const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000'
  const wsUrl = useMemo(() => {
    try {
      const url = new URL(apiUrl)
      const protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
      return `${protocol}//${url.host}/ws`
    } catch {
      return 'ws://localhost:8000/ws'
    }
  }, [apiUrl])

  const handleMessage = useCallback((msg) => {
    if (!msg || !msg.type) return
    const handlers = {
      job_started: true,
      job_progress: true,
      job_completed: true,
      job_failed: true,
      queue_snapshot: true,
    }
    if (handlers[msg.type]) {
      dispatchRef.current({ type: `ws/${msg.type}`, event: msg })
    }
  }, [])

  const { isConnected } = useWebSocket(wsUrl, handleMessage)

  const refreshJobs = useCallback(async () => {
    try {
      const response = await jobsAPI.getJobs()
      const jobs = response.data.jobs || []
      dispatchRef.current({ type: 'jobs/hydrate', jobs })
    } catch (err) {
      console.error('Failed to fetch jobs:', err)
    }
  }, [])

  const refreshWorkers = useCallback(async () => {
    try {
      const response = await workersAPI.getWorkers()
      const workers = response.data.workers || []
      dispatchRef.current({ type: 'workers/hydrate', workers })
    } catch (err) {
      console.error('Failed to fetch workers:', err)
    }
  }, [])

  useEffect(() => {
    refreshJobs()
    const interval = setInterval(refreshJobs, JOBS_REFRESH_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [refreshJobs])

  useEffect(() => {
    refreshWorkers()
    const interval = setInterval(refreshWorkers, WORKERS_REFRESH_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [refreshWorkers])

  const value = useMemo(
    () => ({
      ...state,
      isConnected,
      refreshJobs,
      refreshWorkers,
    }),
    [state, isConnected, refreshJobs, refreshWorkers]
  )

  return <RealtimeContext.Provider value={value}>{children}</RealtimeContext.Provider>
}

export function useRealtime() {
  const ctx = useContext(RealtimeContext)
  if (!ctx) {
    throw new Error('useRealtime must be used inside RealtimeProvider')
  }
  return ctx
}

export function useJobs() {
  const { jobsById, jobsInitialized } = useRealtime()
  const jobs = useMemo(() => {
    return Object.values(jobsById).sort((a, b) => {
      const ta = a.created_at ? new Date(a.created_at).getTime() : 0
      const tb = b.created_at ? new Date(b.created_at).getTime() : 0
      return tb - ta
    })
  }, [jobsById])
  return { jobs, initialized: jobsInitialized }
}

export function useWorkers() {
  const { workersById, workersInitialized } = useRealtime()
  const workers = useMemo(
    () => Object.values(workersById).sort((a, b) => a.id.localeCompare(b.id)),
    [workersById]
  )
  return { workers, initialized: workersInitialized }
}

export function useQueueSnapshot() {
  const { queueSnapshot } = useRealtime()
  return queueSnapshot
}

export function useJobCounts() {
  const { jobsById } = useRealtime()
  return useMemo(() => {
    const counts = {
      total: 0,
      completed: 0,
      failed: 0,
      processing: 0,
      pending: 0,
      queued: 0,
    }
    for (const job of Object.values(jobsById)) {
      counts.total += 1
      if (job.status && Object.prototype.hasOwnProperty.call(counts, job.status)) {
        counts[job.status] += 1
      }
    }
    return counts
  }, [jobsById])
}
