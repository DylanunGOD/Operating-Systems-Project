import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const api = axios.create({
  baseURL: API_URL,
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json',
  },
})

api.interceptors.response.use(
  response => response,
  error => {
    console.error('API Error:', error.response?.data || error.message)
    return Promise.reject(error)
  }
)

export const jobsAPI = {
  getJobs: (status, workerId, limit = 100, offset = 0) =>
    api.get('/jobs', { params: { status, worker_id: workerId, limit, offset } }),

  getJob: (jobId) =>
    api.get(`/jobs/${jobId}`),

  createJob: (jobData) =>
    api.post('/jobs', jobData),

  updateJob: (jobId, updates) =>
    api.patch(`/jobs/${jobId}`, updates),

  deleteJob: (jobId) =>
    api.delete(`/jobs/${jobId}`),
}

export const workersAPI = {
  getWorkers: () =>
    api.get('/workers'),

  getWorker: (workerId) =>
    api.get(`/workers/${workerId}`),
}

export const metricsAPI = {
  getMetrics: () =>
    api.get('/metrics'),
}

export default api
