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

export function presignUpload(filename, contentType = 'application/pdf') {
  return apiRequest('/api/uploads/presign', {
    method: 'POST',
    body: JSON.stringify({ filename, content_type: contentType }),
  })
}

// Uses XMLHttpRequest (not fetch) specifically because fetch has no
// upload-progress event -- the caller needs live percentage feedback while
// the (potentially large) PDF streams directly to MinIO.
export function uploadFileToPresignedUrl(uploadUrl, file, { onProgress } = {}) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('PUT', uploadUrl)
    xhr.setRequestHeader('Content-Type', file.type || 'application/pdf')

    xhr.upload.onprogress = event => {
      if (event.lengthComputable && onProgress) {
        onProgress(event.loaded / event.total)
      }
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve()
      } else {
        reject(new Error(`Dosya yüklenemedi (HTTP ${xhr.status})`))
      }
    }
    xhr.onerror = () => reject(new Error('Dosya yüklenirken bir ağ hatası oluştu'))
    xhr.send(file)
  })
}

export function createPdfDocument(storageKey, title) {
  return apiRequest('/api/documents/pdf', {
    method: 'POST',
    body: JSON.stringify(title ? { storage_key: storageKey, title } : { storage_key: storageKey }),
  })
}

export function createUrlDocument(url, title) {
  return apiRequest('/api/documents/url', {
    method: 'POST',
    body: JSON.stringify(title ? { url, title } : { url }),
  })
}

export function getDocumentIngestion(documentId) {
  return apiRequest(`/api/documents/${documentId}/ingestion`)
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

export function listExtractionJobs({ status, documentId, limit = 50, offset = 0 } = {}) {
  const params = new URLSearchParams()
  params.set('limit', String(limit))
  params.set('offset', String(offset))
  if (status) params.set('status', status)
  if (documentId) params.set('document_id', documentId)
  return apiRequest(`/api/extraction-jobs?${params.toString()}`)
}

export function updateTripleStatus(tripleId, status) {
  return apiRequest(`/api/triples/${tripleId}/status`, {
    method: 'PATCH',
    body: JSON.stringify({ status }),
  })
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

// Builds a full result-card object from a job (either the full
// ExtractionJobResponse or the lighter ExtractionJobSummary from the history
// list -- both carry the same pipeline/status fields) plus the document text
// and, once available, the job's raw triples. Shared by the localStorage
// restore-on-mount flow and the history panel's "load into a slot" action so
// a reconstructed card looks identical regardless of where it came from.
export function buildCardFromJob({ cardId, job, documentText, rawTriples = [], requestId = null }) {
  const { triplets, highlight } = mapTriplesToLegacyFormat(rawTriples)
  return {
    id: cardId,
    model: job.model,
    text: documentText,
    kgType: job.kg_type,
    promptType: job.prompt_type,
    embeddingModel: job.embedding_model,
    ontologyLanguage: job.ontology_language,
    status: mapJobStatusToCardStatus(job.status),
    jobStatus: job.status,
    jobId: job.id,
    documentId: job.document_id,
    requestId,
    triplets,
    highlight,
    rawTriples,
    errorMessage: job.status === 'failed' ? (job.error_message || '') : '',
    startedAt: job.created_at,
    completedAt: job.completed_at,
    durationMs: computeDurationMs(job.created_at, job.completed_at),
  }
}
