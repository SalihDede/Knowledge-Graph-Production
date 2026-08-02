import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  buildCardFromJob,
  computeDurationMs,
  createDocument,
  createExtractionJob,
  getDocument,
  getExtractionJob,
  getJobTriples,
  listExtractionJobs,
  mapJobStatusToCardStatus,
  mapTriplesToLegacyFormat,
  updateTripleStatus,
} from './extraction'

function jsonResponse(body, { ok = true, status = 200, requestId = 'req_test123' } = {}) {
  return {
    ok,
    status,
    statusText: ok ? 'OK' : 'Error',
    headers: { get: header => (header === 'X-Request-ID' ? requestId : null) },
    json: async () => body,
  }
}

describe('mapTriplesToLegacyFormat', () => {
  it('maps backend field names to the legacy Turkish schema', () => {
    const { triplets, highlight } = mapTriplesToLegacyFormat([
      {
        subject: 'Atatürk',
        subject_type: 'Kişi',
        predicate: 'doğum_yeri',
        object: 'Selanik',
        object_type: 'Yer',
        qualifiers: [{ relation: 'year', object: '1881' }],
        evidence: [{ source_text: "Atatürk 1881 yılında Selanik'te doğdu.", char_start: 0, char_end: 38 }],
      },
    ])

    expect(triplets).toEqual([
      {
        baş: 'Atatürk',
        baş_tipi: 'Kişi',
        ilişki: 'doğum_yeri',
        uç: 'Selanik',
        uç_tipi: 'Yer',
        qualifiers: [{ relation: 'year', object: '1881' }],
        kaynak_cumle: "Atatürk 1881 yılında Selanik'te doğdu.",
      },
    ])
    expect(highlight).toEqual(['Atatürk'])
  })

  it('tolerates missing evidence, qualifiers and types', () => {
    const { triplets } = mapTriplesToLegacyFormat([
      { subject: 'A', predicate: 'rel', object: 'B' },
    ])

    expect(triplets[0]).toEqual({
      baş: 'A',
      baş_tipi: '',
      ilişki: 'rel',
      uç: 'B',
      uç_tipi: '',
      qualifiers: [],
      kaynak_cumle: '',
    })
  })

  it('deduplicates the highlight list', () => {
    const { highlight } = mapTriplesToLegacyFormat([
      { subject: 'A', predicate: 'r1', object: 'B' },
      { subject: 'A', predicate: 'r2', object: 'C' },
    ])

    expect(highlight).toEqual(['A'])
  })

  it('returns empty results for an empty triple list', () => {
    expect(mapTriplesToLegacyFormat([])).toEqual({ triplets: [], highlight: [] })
    expect(mapTriplesToLegacyFormat()).toEqual({ triplets: [], highlight: [] })
  })
})

describe('mapJobStatusToCardStatus', () => {
  it('maps queued and running to loading', () => {
    expect(mapJobStatusToCardStatus('queued')).toBe('loading')
    expect(mapJobStatusToCardStatus('running')).toBe('loading')
  })

  it('maps completed to done and failed to error', () => {
    expect(mapJobStatusToCardStatus('completed')).toBe('done')
    expect(mapJobStatusToCardStatus('failed')).toBe('error')
  })
})

describe('computeDurationMs', () => {
  it('computes the difference between two ISO timestamps', () => {
    expect(computeDurationMs('2026-01-01T00:00:00.000Z', '2026-01-01T00:00:01.500Z')).toBe(1500)
  })

  it('falls back to Date.now() when no completion timestamp is given', () => {
    const now = new Date('2026-01-01T00:00:05.000Z')
    vi.useFakeTimers()
    vi.setSystemTime(now)
    try {
      expect(computeDurationMs('2026-01-01T00:00:00.000Z', null)).toBe(5000)
    } finally {
      vi.useRealTimers()
    }
  })

  it('returns null for invalid input', () => {
    expect(computeDurationMs('not-a-date', null)).toBeNull()
  })
})

describe('API client', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('createDocument posts the trimmed payload and returns data + requestId', async () => {
    fetch.mockResolvedValueOnce(jsonResponse({ id: 'doc-1', normalized_text: 'metin' }))

    const { data, requestId } = await createDocument('metin')

    expect(fetch).toHaveBeenCalledWith('/api/documents', expect.objectContaining({
      method: 'POST',
      credentials: 'same-origin',
      body: JSON.stringify({ text: 'metin' }),
    }))
    expect(data).toEqual({ id: 'doc-1', normalized_text: 'metin' })
    expect(requestId).toBe('req_test123')
  })

  it('createExtractionJob sends snake_case pipeline params', async () => {
    fetch.mockResolvedValueOnce(jsonResponse({ id: 'job-1', status: 'queued' }))

    await createExtractionJob({
      documentId: 'doc-1',
      model: 'google/gemini-2.5-flash-lite',
      promptType: 'temel',
      kgType: 'wikipedia',
      embeddingModel: 'contriever',
      ontologyLanguage: 'en',
    })

    expect(fetch).toHaveBeenCalledWith('/api/extraction-jobs', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({
        document_id: 'doc-1',
        model: 'google/gemini-2.5-flash-lite',
        prompt_type: 'temel',
        kg_type: 'wikipedia',
        embedding_model: 'contriever',
        ontology_language: 'en',
      }),
    }))
  })

  it('getExtractionJob and getJobTriples hit the expected URLs', async () => {
    fetch.mockResolvedValue(jsonResponse({}))

    await getExtractionJob('job-1')
    await getJobTriples('job-1')
    await getDocument('doc-1')

    expect(fetch).toHaveBeenNthCalledWith(1, '/api/extraction-jobs/job-1', expect.any(Object))
    expect(fetch).toHaveBeenNthCalledWith(2, '/api/extraction-jobs/job-1/triples', expect.any(Object))
    expect(fetch).toHaveBeenNthCalledWith(3, '/api/documents/doc-1', expect.any(Object))
  })

  it('throws an Error carrying the request id and status on failure', async () => {
    fetch.mockResolvedValueOnce(
      jsonResponse({ detail: 'Doküman bulunamadı' }, { ok: false, status: 404, requestId: 'req_abc' })
    )

    await expect(getExtractionJob('missing')).rejects.toMatchObject({
      message: 'Doküman bulunamadı',
      status: 404,
      requestId: 'req_abc',
    })
  })

  it('listExtractionJobs encodes pagination and filters as query params', async () => {
    fetch.mockResolvedValueOnce(jsonResponse([]))

    await listExtractionJobs({ status: 'completed', documentId: 'doc-1', limit: 10, offset: 20 })

    const [url] = fetch.mock.calls[0]
    expect(url).toBe('/api/extraction-jobs?limit=10&offset=20&status=completed&document_id=doc-1')
  })

  it('listExtractionJobs defaults to limit 50 offset 0 with no filters', async () => {
    fetch.mockResolvedValueOnce(jsonResponse([]))

    await listExtractionJobs()

    const [url] = fetch.mock.calls[0]
    expect(url).toBe('/api/extraction-jobs?limit=50&offset=0')
  })

  it('updateTripleStatus PATCHes the new status', async () => {
    fetch.mockResolvedValueOnce(jsonResponse({ id: 'triple-1', status: 'verified' }))

    await updateTripleStatus('triple-1', 'verified')

    expect(fetch).toHaveBeenCalledWith('/api/triples/triple-1/status', expect.objectContaining({
      method: 'PATCH',
      body: JSON.stringify({ status: 'verified' }),
    }))
  })
})

describe('buildCardFromJob', () => {
  const baseJob = {
    id: 'job-1',
    document_id: 'doc-1',
    model: 'google/gemini-2.5-flash-lite',
    kg_type: 'wikipedia',
    prompt_type: 'temel',
    embedding_model: 'contriever',
    ontology_language: 'en',
    status: 'completed',
    error_message: null,
    created_at: '2026-01-01T00:00:00.000Z',
    completed_at: '2026-01-01T00:00:05.000Z',
  }

  it('builds a completed card with mapped triplets and raw triples preserved', () => {
    const card = buildCardFromJob({
      cardId: 'card-1',
      job: baseJob,
      documentText: 'Tam metin.',
      rawTriples: [{ id: 't1', subject: 'A', predicate: 'rel', object: 'B', evidence: [] }],
    })

    expect(card.id).toBe('card-1')
    expect(card.jobId).toBe('job-1')
    expect(card.documentId).toBe('doc-1')
    expect(card.status).toBe('done')
    expect(card.text).toBe('Tam metin.')
    expect(card.triplets).toEqual([
      { baş: 'A', baş_tipi: '', ilişki: 'rel', uç: 'B', uç_tipi: '', qualifiers: [], kaynak_cumle: '' },
    ])
    expect(card.rawTriples).toHaveLength(1)
    expect(card.durationMs).toBe(5000)
    expect(card.errorMessage).toBe('')
  })

  it('surfaces the error message for a failed job', () => {
    const card = buildCardFromJob({
      cardId: 'card-2',
      job: { ...baseJob, status: 'failed', error_message: 'Model reddedildi.' },
      documentText: 'Tam metin.',
    })

    expect(card.status).toBe('error')
    expect(card.errorMessage).toBe('Model reddedildi.')
  })

  it('maps queued/running jobs to the loading card status', () => {
    const queuedCard = buildCardFromJob({ cardId: 'c', job: { ...baseJob, status: 'queued' }, documentText: '' })
    const runningCard = buildCardFromJob({ cardId: 'c', job: { ...baseJob, status: 'running' }, documentText: '' })

    expect(queuedCard.status).toBe('loading')
    expect(runningCard.status).toBe('loading')
  })
})
