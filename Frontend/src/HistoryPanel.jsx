import { getUiText } from './i18n'

function formatTimestamp(iso) {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString()
}

function getUrlHost(url) {
  try {
    return new URL(url).host
  } catch {
    return url
  }
}

function getSourceBadge(job, copy) {
  if (job.document_source_type === 'pdf') {
    return job.document_page_count
      ? `${copy.sourcePdf} · ${job.document_page_count} ${copy.pageUnit}`
      : copy.sourcePdf
  }
  if (job.document_source_type === 'url') {
    return job.document_source_url
      ? `${copy.sourceUrl} · ${getUrlHost(job.document_source_url)}`
      : copy.sourceUrl
  }
  return null
}

export default function HistoryPanel({ jobs, loading, error, onSelectJob, onRefresh, t }) {
  const fallbackText = getUiText('tr')
  const copy = t?.historyPanel ?? fallbackText.historyPanel

  return (
    <section className="history-panel" aria-labelledby="history-panel-title">
      <div className="history-panel-header">
        <div>
          <span className="section-kicker">{copy.kicker}</span>
          <h2 id="history-panel-title">{copy.title}</h2>
        </div>
        <button
          type="button"
          className="history-panel-refresh"
          onClick={onRefresh}
          disabled={loading}
          aria-label={copy.refreshAria}
        >
          {copy.refresh}
        </button>
      </div>

      {loading && <p className="history-panel-hint">{copy.loading}</p>}

      {!loading && error && (
        <div className="history-panel-error" role="alert">
          <p>{error.message}</p>
          {error.requestId && (
            <p className="history-panel-request-id">{copy.requestIdLabel}: {error.requestId}</p>
          )}
        </div>
      )}

      {!loading && !error && jobs.length === 0 && (
        <p className="history-panel-hint">{copy.empty}</p>
      )}

      {!loading && !error && jobs.length > 0 && (
        <ul className="history-panel-list">
          {jobs.map(job => (
            <li key={job.id}>
              <button
                type="button"
                className={`history-panel-item history-panel-item--${job.status}`}
                onClick={() => onSelectJob(job)}
              >
                <div className="history-panel-item-main">
                  <strong>{job.document_title || copy.untitledDocument}</strong>
                  <span className={`history-panel-status history-panel-status--${job.status}`}>
                    {copy.statuses[job.status] || job.status}
                  </span>
                </div>
                <p className="history-panel-preview">{job.document_preview}</p>
                <div className="history-panel-meta">
                  {getSourceBadge(job, copy) && (
                    <span className="history-panel-source-badge">{getSourceBadge(job, copy)}</span>
                  )}
                  <span>{job.model}</span>
                  <span>{job.triple_count} {copy.tripleUnit}</span>
                  <span>{formatTimestamp(job.completed_at || job.created_at)}</span>
                </div>
                {job.status === 'failed' && job.error_message && (
                  <p className="history-panel-item-error">{job.error_message}</p>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
