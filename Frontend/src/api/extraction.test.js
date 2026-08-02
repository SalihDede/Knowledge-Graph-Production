import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  computeDurationMs,
  createDocument,
  createExtractionJob,
  getDocument,
  getExtractionJob,
  getJobTriples,
  mapJobStatusToCardStatus,
  mapTriplesToLegacyFormat,
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
})
