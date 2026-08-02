import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { getUiText } from './i18n'

function renderHighlightedText(text, evidenceList, highlightClassName) {
  const spans = (evidenceList ?? [])
    .filter(
      evidence =>
        Number.isInteger(evidence.char_start) &&
        Number.isInteger(evidence.char_end) &&
        evidence.char_end > evidence.char_start
    )
    .sort((a, b) => a.char_start - b.char_start)

  if (spans.length === 0) {
    return <span>{text}</span>
  }

  const parts = []
  let cursor = 0
  spans.forEach((span, index) => {
    const start = Math.max(span.char_start, cursor)
    if (start > cursor) {
      parts.push(<span key={`plain-${index}`}>{text.slice(cursor, start)}</span>)
    }
    if (span.char_end > start) {
      parts.push(
        <mark key={`mark-${index}`} className={highlightClassName}>
          {text.slice(start, span.char_end)}
        </mark>
      )
    }
    cursor = Math.max(cursor, span.char_end)
  })
  if (cursor < text.length) {
    parts.push(<span key="plain-end">{text.slice(cursor)}</span>)
  }
  return <>{parts}</>
}

export default function TripleReviewModal({ card, onClose, onUpdateTripleStatus, t }) {
  const fallbackText = getUiText('tr')
  const copy = t?.tripleReview ?? fallbackText.tripleReview
  const triples = card?.rawTriples ?? []
  const [selectedTripleId, setSelectedTripleId] = useState(triples[0]?.id ?? null)
  const [pendingTripleId, setPendingTripleId] = useState(null)
  const [actionError, setActionError] = useState('')

  useEffect(() => {
    if (!triples.some(triple => triple.id === selectedTripleId)) {
      setSelectedTripleId(triples[0]?.id ?? null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [triples])

  useEffect(() => {
    function handleKeyDown(event) {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  if (!card) return null

  const selectedTriple = triples.find(triple => triple.id === selectedTripleId) ?? null

  async function handleStatusChange(tripleId, nextStatus) {
    setPendingTripleId(tripleId)
    setActionError('')
    try {
      await onUpdateTripleStatus(tripleId, nextStatus)
    } catch (error) {
      setActionError(error.message || copy.updateFailed)
    } finally {
      setPendingTripleId(null)
    }
  }

  return createPortal(
    <div className="kg-modal-overlay">
      <button
        className="kg-modal-backdrop"
        type="button"
        aria-label={copy.closeAria}
        onClick={onClose}
      />
      <div className="kg-modal triple-review-modal" role="dialog" aria-modal="true" aria-labelledby="triple-review-title">
        <div className="kg-modal-header">
          <div>
            <span className="kg-modal-kicker">{copy.kicker}</span>
            <h2 className="kg-modal-title" id="triple-review-title">{copy.title}</h2>
          </div>
          <button className="kg-modal-close" type="button" onClick={onClose} aria-label={copy.closeAria}>
            <svg width="11" height="11" viewBox="0 0 10 10" fill="none">
              <path d="M1 1L9 9M9 1L1 9" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        {actionError && <p className="triple-review-error" role="alert">{actionError}</p>}

        <div className="kg-modal-body triple-review-body">
          <ul className="triple-review-list" aria-label={copy.tripleListAria}>
            {triples.length === 0 && <li className="triple-review-empty">{copy.noTriples}</li>}
            {triples.map(triple => (
              <li key={triple.id}>
                <button
                  type="button"
                  className={`triple-review-row ${triple.id === selectedTripleId ? 'active' : ''}`}
                  onClick={() => setSelectedTripleId(triple.id)}
                >
                  <span className={`triple-review-status triple-review-status--${triple.status}`}>
                    {copy.statuses[triple.status] || triple.status}
                  </span>
                  <span className="triple-review-fact">
                    <strong>{triple.subject}</strong> {triple.predicate} <strong>{triple.object}</strong>
                  </span>
                </button>
                <div className="triple-review-actions">
                  <button
                    type="button"
                    disabled={pendingTripleId === triple.id || triple.status === 'verified'}
                    onClick={() => handleStatusChange(triple.id, 'verified')}
                  >
                    {copy.approve}
                  </button>
                  <button
                    type="button"
                    disabled={pendingTripleId === triple.id || triple.status === 'rejected'}
                    onClick={() => handleStatusChange(triple.id, 'rejected')}
                  >
                    {copy.reject}
                  </button>
                  <button
                    type="button"
                    disabled={pendingTripleId === triple.id || triple.status === 'candidate'}
                    onClick={() => handleStatusChange(triple.id, 'candidate')}
                  >
                    {copy.reset}
                  </button>
                </div>
              </li>
            ))}
          </ul>

          <aside className="graph-side-panel triple-review-detail" aria-label={copy.evidenceAria}>
            {selectedTriple ? (
              <>
                <section className="graph-panel-section">
                  <span className="graph-panel-kicker">{copy.factLabel}</span>
                  <h3>
                    {selectedTriple.subject} — {selectedTriple.predicate} — {selectedTriple.object}
                  </h3>
                </section>
                <section className="graph-panel-section">
                  <span className="graph-panel-kicker">{copy.evidenceLabel}</span>
                  {selectedTriple.evidence?.length > 0 ? (
                    <div className="triple-review-source-text">
                      {renderHighlightedText(card.text || '', selectedTriple.evidence, 'triple-review-highlight')}
                    </div>
                  ) : (
                    <p className="graph-panel-note">{copy.noEvidence}</p>
                  )}
                </section>
              </>
            ) : (
              <p className="graph-panel-note">{copy.noTriples}</p>
            )}
          </aside>
        </div>
      </div>
    </div>,
    document.body
  )
}
