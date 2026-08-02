// Async document -> extraction job -> triples client used by the studio UI.
// Mirrors the request/error conventions already established in AuthPanel.jsx.

async function apiRequest(path, options = {}) {
  const response = await fetch(path, {
    credentials: 'same-origin',
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
  })
  const requestId = response.headers.get('X-Request-ID') || null
  const data = await response.json().catch(() => ({}))

  if (!response.ok) {
    const error = new Error(data.detail || response.statusText)
    error.requestId = requestId
    error.status = response.status
    throw error
  }

  return { data, requestId }
}

export function createDocument(text, title) {
  return apiRequest('/api/documents', {
    method: 'POST',
    body: JSON.stringify(title ? { text, title } : { text }),
  })
}

export function getDocument(documentId) {
  return apiRequest(`/api/documents/${documentId}`)
}

export function createExtractionJob({
  documentId,
  model,
  promptType,
  kgType,
  embeddingModel,
  ontologyLanguage,
}) {
  return apiRequest('/api/extraction-jobs', {
    method: 'POST',
    body: JSON.stringify({
      document_id: documentId,
      model,
      prompt_type: promptType,
      kg_type: kgType,
      embedding_model: embeddingModel,
      ontology_language: ontologyLanguage,
    }),
  })
}

export function getExtractionJob(jobId) {
  return apiRequest(`/api/extraction-jobs/${jobId}`)
}

export function getJobTriples(jobId) {
  return apiRequest(`/api/extraction-jobs/${jobId}/triples`)
}

// The backend stores triples with English field names (subject/predicate/object);
// the studio UI (ResultCard, KGGraph, exports, ...) speaks the original Turkish
// triple schema (baş/ilişki/uç). This is the single place that bridges the two.
export function mapTriplesToLegacyFormat(triples = []) {
  const triplets = triples.map(triple => ({
    baş: triple.subject ?? '',
    baş_tipi: triple.subject_type ?? '',
    ilişki: triple.predicate ?? '',
    uç: triple.object ?? '',
    uç_tipi: triple.object_type ?? '',
    qualifiers: triple.qualifiers ?? [],
    kaynak_cumle: triple.evidence?.[0]?.source_text ?? '',
  }))
  const highlight = [...new Set(triplets.map(triplet => triplet.baş).filter(Boolean))]
  return { triplets, highlight }
}

// queued/running are both surfaced as the existing "loading" card state; the
// UI does not yet distinguish between "not picked up by a worker" and
// "actively extracting".
export function mapJobStatusToCardStatus(jobStatus) {
  if (jobStatus === 'completed') return 'done'
  if (jobStatus === 'failed') return 'error'
  return 'loading'
}

export function computeDurationMs(startedAtIso, completedAtIso) {
  const start = new Date(startedAtIso).getTime()
  const end = completedAtIso ? new Date(completedAtIso).getTime() : Date.now()
  if (!Number.isFinite(start) || !Number.isFinite(end)) return null
  return end - start
}
