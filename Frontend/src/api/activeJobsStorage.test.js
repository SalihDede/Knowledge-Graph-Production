import { beforeEach, describe, expect, it } from 'vitest'
import { addActiveJob, loadActiveJobs, removeActiveJob } from './activeJobsStorage'

const STORAGE_KEY = 'kg-active-extraction-jobs'

beforeEach(() => {
  window.localStorage.clear()
})

describe('activeJobsStorage', () => {
  it('starts empty when nothing has been stored', () => {
    expect(loadActiveJobs()).toEqual([])
  })

  it('adds and reloads an entry', () => {
    addActiveJob({ jobId: 'job-1', documentId: 'doc-1' })

    expect(loadActiveJobs()).toEqual([{ jobId: 'job-1', documentId: 'doc-1' }])
  })

  it('ignores invalid entries', () => {
    addActiveJob({ jobId: 'job-1' })
    addActiveJob(null)
    addActiveJob({ documentId: 'doc-1' })

    expect(loadActiveJobs()).toEqual([])
  })

  it('does not duplicate an already-tracked job id', () => {
    addActiveJob({ jobId: 'job-1', documentId: 'doc-1' })
    addActiveJob({ jobId: 'job-1', documentId: 'doc-1' })

    expect(loadActiveJobs()).toHaveLength(1)
  })

  it('removes a job by id, leaving the others intact', () => {
    addActiveJob({ jobId: 'job-1', documentId: 'doc-1' })
    addActiveJob({ jobId: 'job-2', documentId: 'doc-2' })

    removeActiveJob('job-1')

    expect(loadActiveJobs()).toEqual([{ jobId: 'job-2', documentId: 'doc-2' }])
  })

  it('recovers from corrupted JSON instead of throwing', () => {
    window.localStorage.setItem(STORAGE_KEY, '{not-json')

    expect(loadActiveJobs()).toEqual([])
  })

  it('filters out malformed entries found in storage', () => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify([
      { jobId: 'job-1', documentId: 'doc-1' },
      { jobId: 'job-2' },
      'not-an-object',
      42,
    ]))

    expect(loadActiveJobs()).toEqual([{ jobId: 'job-1', documentId: 'doc-1' }])
  })
})
