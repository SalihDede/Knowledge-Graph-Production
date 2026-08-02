import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import KGGraph from './visualization/KGGraph'
import { getUiText } from './i18n'

function useStats(triplets = []) {
  const tripleCount   = triplets.length
  const entityCount   = new Set(triplets.flatMap(t => [t.baş, t.uç].filter(Boolean))).size
  const relationCount = new Set(triplets.map(t => t.ilişki).filter(Boolean)).size
  return { tripleCount, entityCount, relationCount }
}

function getTopRelations(triplets = []) {
  const counts = new Map()
  triplets.forEach(triplet => {
    if (!triplet.ilişki) return
    counts.set(triplet.ilişki, (counts.get(triplet.ilişki) || 0) + 1)
  })
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4)
}

function formatDuration(ms) {
  if (!Number.isFinite(ms) || ms <= 0) return ''
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)}s`
}

function ExpandIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
      <path d="M1 4.5V1H4.5M7.5 1H11V4.5M11 7.5V11H7.5M4.5 11H1V7.5"
        stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  )
}

function DownloadIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 13 13" fill="none">
      <path d="M6.5 1V8M6.5 8L3.75 5.25M6.5 8L9.25 5.25M2 10.75H11"
        stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  )
}


const OPTIMIZED_PROMPT_TYPES = new Set(['ape', 'dspy', 'textgrad'])

export default function ResultCard({
  variant = 'generated',
  slotLabel,
  slotIndex = 0,
  model,
  text,
  kgLabel,
  promptLabel,
  promptType,
  embeddingLabel,
  ontologyLabel,
  status,
  triplets,
  highlight,
  durationMs,
  errorMessage,
  fileName,
  onDelete,
  onExport,
  t,
}) {
  const [expanded, setExpanded] = useState(false)
  const fallbackText = getUiText('tr')
  const copy = t?.resultCard ?? fallbackText.resultCard
  const kgGraphLabels = t?.kgGraph ?? fallbackText.kgGraph
  const isReference = variant === 'reference'
  const { tripleCount, entityCount, relationCount } = useStats(status === 'done' ? triplets : [])
  const statusLabel = copy.statuses[status] || copy.statuses.queued
  const topRelations = getTopRelations(status === 'done' ? triplets : [])
  const highlightedEntities = Array.isArray(highlight) ? highlight.filter(Boolean).slice(0, 6) : []
  const title = isReference ? copy.referenceTitle : kgLabel
  const kicker = isReference ? copy.referenceKicker : slotLabel
  const cardText = isReference ? (text || copy.importedGroundTruth) : text

  useEffect(() => {
    if (!expanded) return

    function handleKeyDown(event) {
      if (event.key === 'Escape') setExpanded(false)
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [expanded])

  return (
    <div className={`result-card ${isReference ? 'result-card--reference' : `result-card--slot-${slotIndex}`}`}>
      <div className="result-card-header">
        <div>
          <span className="slot-kicker">{kicker}</span>
          <h3 className="result-card-title">{title}</h3>
        </div>
        <div className="result-card-actions">
          {onExport && status === 'done' && (
            <button className="result-card-icon-button" onClick={onExport} aria-label={copy.downloadJsonAria}>
              <DownloadIcon />
            </button>
          )}
          {onDelete && (
            <button className="result-card-icon-button" onClick={onDelete} aria-label={copy.deleteCardAria}>
              <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                <path d="M1 1L9 9M9 1L1 9" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
              </svg>
            </button>
          )}
        </div>
      </div>

      <div className="result-chips">
        {isReference ? (
          <span className="result-chip result-chip--reference">
            <span className="result-chip-dot result-chip-dot--reference" />
            {copy.importedChip} · {fileName}
          </span>
        ) : (
          <>
            <span className="result-chip">
              <span className="result-chip-dot" />
              {promptLabel}
            </span>
            <span className="result-chip">
              <span className="result-chip-dot result-chip-dot--prompt" />
              {model}
            </span>

            {embeddingLabel && (
              <span className="result-chip">
                <span className="result-chip-dot result-chip-dot--embedding" />
                {embeddingLabel}
              </span>
            )}

            {ontologyLabel && (
              <span className="result-chip">
                <span className="result-chip-dot result-chip-dot--embedding" />
                {ontologyLabel}
              </span>
            )}
          </>
        )}

        {status === 'done' && (
          <div className="result-card-stats">
            <div className="result-card-stat">
              <span className="result-card-stat-value">{tripleCount}</span>
              <span className="result-card-stat-label">{copy.tripleStat}</span>
            </div>
            <span className="result-card-stat-sep" />
            <div className="result-card-stat">
              <span className="result-card-stat-value">{entityCount}</span>
              <span className="result-card-stat-label">{copy.uniqueEntityStat}</span>
            </div>
            <span className="result-card-stat-sep" />
            <div className="result-card-stat">
              <span className="result-card-stat-value">{relationCount}</span>
              <span className="result-card-stat-label">{copy.uniqueRelationStat}</span>
            </div>
          </div>
        )}
      </div>

      <p className="result-card-text">{cardText}</p>

      <div className="result-card-body">
        {status === 'loading' && (
          <div className="result-card-state">
            <div className="result-card-loading">
              <span /><span /><span />
            </div>
            <p className="result-card-hint">{copy.extractingTriples}</p>
            {OPTIMIZED_PROMPT_TYPES.has(promptType) && (
              <p className="result-card-hint result-card-hint--note">
                {copy.optimizedPromptNote}
              </p>
            )}
          </div>
        )}

        {status === 'error' && (
          <div className="result-card-state">
            <p className="result-card-hint result-card-hint--error">
              {errorMessage || 'LLM isteği başarısız.'}
            </p>
          </div>
        )}

        {status === 'done' && (
          <>
            <button
              className="result-card-expand"
              onClick={() => setExpanded(true)}
              aria-label={copy.expandGraphAria}
            >
              <ExpandIcon />
            </button>
            <KGGraph triplets={triplets ?? []} highlight={highlight ?? []} labels={kgGraphLabels} />
          </>
        )}
      </div>

      <div className={`slot-status slot-status--${status}`}>
        {copy.statusPrefix}: {statusLabel}{durationMs ? ` · ${formatDuration(durationMs)}` : ''}
      </div>

      {expanded && createPortal(
        <div className="kg-modal-overlay">
          <button
            className="kg-modal-backdrop"
            type="button"
            aria-label={copy.closeAria}
            onClick={() => setExpanded(false)}
          />
          <div className="kg-modal" role="dialog" aria-modal="true" aria-labelledby="kg-modal-title">
            <div className="kg-modal-header">
              <div>
                <span className="kg-modal-kicker">{copy.graphExplorer}</span>
                <h2 className="kg-modal-title" id="kg-modal-title">{isReference ? title : `${slotLabel} / ${kgLabel}`}</h2>
              </div>
              <div className="kg-modal-chips" aria-label={copy.configurationAria}>
                {isReference ? (
                  <span className="result-chip result-chip--reference">
                    <span className="result-chip-dot result-chip-dot--reference" />{copy.importedChip} · {fileName}
                  </span>
                ) : (
                  <>
                    <span className="result-chip"><span className="result-chip-dot" />{promptLabel}</span>
                    <span className="result-chip"><span className="result-chip-dot result-chip-dot--prompt" />{model}</span>
                    {embeddingLabel ? (
                      <span className="result-chip">
                        <span className="result-chip-dot result-chip-dot--embedding" />{embeddingLabel}
                      </span>
                    ) : (
                      <span className="result-chip">{copy.noEmbeddingRequired}</span>
                    )}
                    {ontologyLabel && (
                      <span className="result-chip">
                        <span className="result-chip-dot result-chip-dot--embedding" />{ontologyLabel}
                      </span>
                    )}
                  </>
                )}
              </div>
              <button
                className="kg-modal-close"
                onClick={() => setExpanded(false)}
                aria-label={copy.closeAria}
              >
                <svg width="11" height="11" viewBox="0 0 10 10" fill="none">
                  <path d="M1 1L9 9M9 1L1 9" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/>
                </svg>
              </button>
            </div>
            <div className="kg-modal-body">
              <div className="graph-explorer-stage">
                <div className="graph-toolbar">
                  <span>{copy.standardView}</span>
                  <strong>{tripleCount} {copy.triples.toLowerCase()}</strong>
                </div>
                <KGGraph triplets={triplets ?? []} highlight={highlight ?? []} labels={kgGraphLabels} />
              </div>
              <aside className="graph-side-panel" aria-label={copy.graphDetailsAria}>
                <section className="graph-panel-section">
                  <span className="graph-panel-kicker">{copy.configuration}</span>
                  <h3>{title}</h3>
                  <div className="graph-stat-grid">
                    <div>
                      <span>{copy.entities}</span>
                      <strong>{entityCount}</strong>
                    </div>
                    <div>
                      <span>{copy.relations}</span>
                      <strong>{relationCount}</strong>
                    </div>
                    <div>
                      <span>{copy.triples}</span>
                      <strong>{tripleCount}</strong>
                    </div>
                  </div>
                </section>

                <section className="graph-panel-section">
                  <span className="graph-panel-kicker">{copy.highlightedEntities}</span>
                  {highlightedEntities.length > 0 ? (
                    <div className="entity-chip-list">
                      {highlightedEntities.map(entity => (
                        <span className="entity-chip" key={entity}>{entity}</span>
                      ))}
                    </div>
                  ) : (
                    <p className="graph-panel-note">{copy.noHighlightedEntities}</p>
                  )}
                </section>

                <section className="graph-panel-section">
                  <span className="graph-panel-kicker">{copy.topRelations}</span>
                  {topRelations.length > 0 ? (
                    <div className="relation-list">
                      {topRelations.map(([relation, count]) => (
                        <div className="relation-row" key={relation}>
                          <span>{relation}</span>
                          <strong>{count}</strong>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="graph-panel-note">{copy.noRelationData}</p>
                  )}
                </section>
              </aside>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  )
}
