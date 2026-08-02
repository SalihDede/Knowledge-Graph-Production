// Tracks in-flight extraction job ids in localStorage so a page reload does
// not orphan jobs that are still queued/running on the backend.

const STORAGE_KEY = 'kg-active-extraction-jobs'

function isValidEntry(entry) {
  return Boolean(entry && typeof entry.jobId === 'string' && typeof entry.documentId === 'string')
}

export function loadActiveJobs() {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter(isValidEntry) : []
  } catch {
    return []
  }
}

function saveActiveJobs(jobs) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(jobs))
  } catch {
    // localStorage unavailable (private mode, quota exceeded, ...); active
    // jobs simply won't survive a reload, polling still works this session.
  }
}

export function addActiveJob(entry) {
  if (!isValidEntry(entry)) return
  const jobs = loadActiveJobs()
  if (jobs.some(job => job.jobId === entry.jobId)) return
  saveActiveJobs([...jobs, entry])
}

export function removeActiveJob(jobId) {
  saveActiveJobs(loadActiveJobs().filter(job => job.jobId !== jobId))
}
