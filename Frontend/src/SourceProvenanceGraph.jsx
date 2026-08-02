import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { getUiText } from './i18n'

const SINGLE_SOURCE_COLORS = ['var(--secondary)', 'var(--blue)', '#8a6500']
const SHARED_SOURCE_COLORS = ['#6b4bd6', '#0f7f8f', '#9b4a8a', '#547025', '#9a4f12']

function normalizeValue(value) {
  return String(value || '').trim()
}

function getTripleKey(triplet) {
  return [
    normalizeValue(triplet.baş).toLocaleLowerCase('tr-TR'),
    normalizeValue(triplet.ilişki).toLocaleLowerCase('tr-TR'),
    normalizeValue(triplet.uç).toLocaleLowerCase('tr-TR'),
  ].join('||')
}

function getSourceDetail(source, copy) {
  return [
    `${source.graphLabel} / ${source.slotLabel}`,
    `${copy.kgSource}: ${source.kgLabel || '-'}`,
    `${copy.prompt}: ${source.promptLabel || '-'}`,
    `${copy.embedding}: ${source.embeddingLabel || copy.notApplicable}`,
    `${copy.ontology}: ${source.ontologyLabel || copy.notApplicable}`,
    `${copy.model}: ${source.model || '-'}`,
  ].join('\n')
}

function getComboLabel(sourceIds, sourceMap, copy) {
  const letters = sourceIds
    .map(id => sourceMap.get(id)?.sourceLetter)
    .filter(Boolean)
    .join('+')

  if (!letters) return copy.source
  if (sourceIds.length === 1) return `${copy.source} ${letters}`
  return `${copy.source} ${letters} ${copy.sharedSuffix}`
}

function buildGraphModel(cards, copy) {
  const completedCards = cards.filter(card => card.status === 'done')
  const sources = completedCards.map((card, index) => ({
    id: String(card.id),
    slotLabel: card.slotLabel,
    sourceLetter: card.sourceLetter,
    graphLabel: `${copy.source} ${card.sourceLetter}`,
    kgLabel: card.kgLabel,
    promptLabel: card.promptLabel,
    embeddingLabel: card.embeddingLabel,
    ontologyLabel: card.ontologyLabel,
    model: card.model,
    tripleCount: card.triplets?.length ?? 0,
    color: SINGLE_SOURCE_COLORS[index % SINGLE_SOURCE_COLORS.length],
    triplets: card.triplets ?? [],
  }))
  const sourceMap = new Map(sources.map(source => [source.id, source]))
  const edgeMap = new Map()

  completedCards.forEach(card => {
    const sourceId = String(card.id)
    const seenInSource = new Set()

    ;(card.triplets ?? []).forEach(triplet => {
      const subject = normalizeValue(triplet.baş)
      const object = normalizeValue(triplet.uç)
      if (!subject || !object) return

      const key = getTripleKey(triplet)
      if (!key || key === '||||') return

      const sourceTripleKey = `${sourceId}:${key}`
      if (seenInSource.has(sourceTripleKey)) return
      seenInSource.add(sourceTripleKey)

      if (!edgeMap.has(key)) {
        edgeMap.set(key, {
          sourceIds: new Set(),
          sources: [],
        })
      }

      const edge = edgeMap.get(key)
      if (!edge.sourceIds.has(sourceId)) {
        edge.sourceIds.add(sourceId)
        edge.sources.push(sourceMap.get(sourceId))
      }
    })
  })

  const comboMap = new Map()
  const sourceOrder = new Map(sources.map((source, index) => [source.id, index]))
  ;[...edgeMap.values()].forEach(edge => {
    const sourceIds = [...edge.sourceIds].sort((a, b) => sourceOrder.get(a) - sourceOrder.get(b))
    const comboKey = sourceIds.join('+')

    if (!comboMap.has(comboKey)) {
      const sourceCount = sourceIds.length
      const sharedIndex = comboMap.size - sources.length
      comboMap.set(comboKey, {
        id: comboKey || 'unknown',
        sourceIds,
        sources: sourceIds.map(id => sourceMap.get(id)).filter(Boolean),
        label: getComboLabel(sourceIds, sourceMap, copy),
        count: 0,
        color: sourceCount === 1
          ? (sourceMap.get(sourceIds[0])?.color ?? SINGLE_SOURCE_COLORS[0])
          : SHARED_SOURCE_COLORS[Math.max(0, sharedIndex) % SHARED_SOURCE_COLORS.length],
      })
    }

    comboMap.get(comboKey).count += 1
  })

  const uniqueEntities = new Set()
  const uniqueRelations = new Set()
  sources.forEach(source => {
    source.triplets.forEach(triplet => {
      if (triplet.baş) uniqueEntities.add(triplet.baş)
      if (triplet.uç) uniqueEntities.add(triplet.uç)
      if (triplet.ilişki) uniqueRelations.add(triplet.ilişki)
    })
  })

  return {
    sources,
    combos: [...comboMap.values()].sort((a, b) => a.label.localeCompare(b.label, 'tr')),
    edgeCount: edgeMap.size,
    entityCount: uniqueEntities.size,
    relationCount: uniqueRelations.size,
  }
}

function getSourceGraphPayload(graph) {
  return {
    sources: graph.sources.map(source => ({
      id: source.id,
      slot_label: source.slotLabel,
      source_letter: source.sourceLetter,
      graph_label: source.graphLabel,
      kg_label: source.kgLabel,
      prompt_label: source.promptLabel,
      embedding_label: source.embeddingLabel,
      ontology_label: source.ontologyLabel,
      model: source.model,
      triplets: source.triplets,
    })),
  }
}

function normalizeFocusTarget(target) {
  if (!target || !target.mode || !target.id) return null
  if (target.mode !== 'source' && target.mode !== 'combo') return null
  return { mode: target.mode, id: String(target.id) }
}

function isSameTarget(left, right) {
  return Boolean(left && right && left.mode === right.mode && left.id === right.id)
}

function getGraphFocusMessage(target) {
  const normalizedTarget = normalizeFocusTarget(target)
  if (!normalizedTarget) return { type: 'sourceGraphFocus', mode: 'reset' }
  return { type: 'sourceGraphFocus', ...normalizedTarget }
}

function ExpandIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 12 12" fill="none" aria-hidden="true">
      <path
        d="M1 4.5V1H4.5M7.5 1H11V4.5M11 7.5V11H7.5M4.5 11H1V7.5"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function CloseIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 10 10" fill="none" aria-hidden="true">
      <path d="M1 1L9 9M9 1L1 9" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  )
}

function SourceGraphStage({
  copy,
  graph,
  result,
  isCurrentResult,
  frameRef,
  onFrameLoad,
  onFullscreen,
  fullscreen = false,
}) {
  const isLoading = !isCurrentResult || (!result.html && !result.error)

  return (
    <div
      className={`source-graph-stage${fullscreen ? ' source-graph-stage--fullscreen' : ''}`}
      aria-label={copy.canvasAria}
      aria-busy={isLoading}
    >
      <div className="source-graph-toolbar" aria-label={copy.graphStats}>
        <span>{graph.edgeCount} {copy.triples}</span>
        <span>{graph.entityCount} {copy.entities}</span>
        <span>{graph.relationCount} {copy.relations}</span>
      </div>

      {onFullscreen && isCurrentResult && result.html && (
        <button
          className="source-graph-fullscreen-button"
          type="button"
          onClick={onFullscreen}
          aria-label={copy.fullscreenGraph}
        >
          <ExpandIcon />
          <span>{copy.fullscreenGraph}</span>
        </button>
      )}

      {isLoading && (
        <div className="source-graph-state">
          <div className="kg-loading">
            <span /><span /><span />
          </div>
          <p>{copy.generating}</p>
        </div>
      )}

      {isCurrentResult && result.error && (
        <div className="source-graph-state">
          <p className="source-graph-error">{copy.loadError}</p>
        </div>
      )}

      {isCurrentResult && result.html && (
        <iframe
          ref={frameRef}
          className="source-graph-frame"
          srcDoc={result.html}
          title={fullscreen ? copy.fullscreenGraph : copy.graphTitle}
          sandbox="allow-scripts"
          onLoad={onFrameLoad}
        />
      )}
    </div>
  )
}

function SourceGraphSide({
  copy,
  graph,
  activeTarget,
  onPreviewTarget,
  onRestoreTarget,
  onSelectTarget,
}) {
  return (
    <aside className="source-graph-side" aria-label={copy.legendAria}>
      <section className="source-graph-side-section">
        <span className="graph-panel-kicker">{copy.sourceLegend}</span>
        <div className="source-card-list">
          {graph.sources.map(source => {
            const target = { mode: 'source', id: source.id }
            const isActive = isSameTarget(activeTarget, target)

            return (
              <button
                className={`source-card${isActive ? ' is-active' : ''}`}
                key={source.id}
                type="button"
                style={{ '--source-color': source.color }}
                title={getSourceDetail(source, copy)}
                aria-pressed={isActive}
                aria-label={`${copy.focusSource}: ${source.graphLabel}`}
                onClick={() => onSelectTarget(target)}
                onMouseEnter={() => onPreviewTarget(target)}
                onMouseLeave={onRestoreTarget}
                onFocus={() => onPreviewTarget(target)}
                onBlur={onRestoreTarget}
              >
                <span className="source-card-heading">
                  <span className="source-card-swatch" aria-hidden="true" />
                  <strong>{source.graphLabel}</strong>
                </span>
                <span className="source-card-meta">{source.kgLabel} / {source.promptLabel}</span>
                <span className="source-card-subtle">{source.embeddingLabel || copy.notApplicable}</span>
              </button>
            )
          })}
        </div>
      </section>

      <section className="source-graph-side-section">
        <span className="graph-panel-kicker">{copy.provenanceLegend}</span>
        <ul className="source-legend-list">
          {graph.combos.map(combo => {
            const target = { mode: 'combo', id: combo.id }
            const isActive = isSameTarget(activeTarget, target)

            return (
              <li key={combo.id}>
                <button
                  className={`source-legend-row${isActive ? ' is-active' : ''}`}
                  type="button"
                  style={{ '--combo-color': combo.color }}
                  title={combo.sources.map(source => getSourceDetail(source, copy)).join('\n\n')}
                  aria-pressed={isActive}
                  aria-label={`${copy.focusProvenance}: ${combo.label}`}
                  onClick={() => onSelectTarget(target)}
                  onMouseEnter={() => onPreviewTarget(target)}
                  onMouseLeave={onRestoreTarget}
                  onFocus={() => onPreviewTarget(target)}
                  onBlur={onRestoreTarget}
                >
                  <span className="source-legend-swatch" aria-hidden="true" />
                  <span className="source-legend-content">
                    <strong>{combo.label}</strong>
                    <span className="source-legend-detail">
                      {combo.count} {copy.triples} / {combo.sources.map(source => source.graphLabel).join(' + ')}
                    </span>
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      </section>
    </aside>
  )
}

function SourceGraphPanel({
  copy,
  graph,
  result,
  isCurrentResult,
  activeTarget,
  onActiveTargetChange,
  onFullscreen,
  fullscreen = false,
}) {
  const frameRef = useRef(null)

  const postGraphFocus = useCallback(target => {
    const frame = frameRef.current
    if (!frame?.contentWindow) return
    frame.contentWindow.postMessage(getGraphFocusMessage(target), '*')
  }, [])

  const handleFrameLoad = useCallback(() => {
    window.setTimeout(() => postGraphFocus(activeTarget), 70)
  }, [activeTarget, postGraphFocus])

  const handlePreviewTarget = useCallback(target => {
    postGraphFocus(target)
  }, [postGraphFocus])

  const handleRestoreTarget = useCallback(() => {
    postGraphFocus(activeTarget)
  }, [activeTarget, postGraphFocus])

  const handleSelectTarget = useCallback(target => {
    onActiveTargetChange(target)
    postGraphFocus(target)
  }, [onActiveTargetChange, postGraphFocus])

  useEffect(() => {
    if (!isCurrentResult || !result.html) return undefined

    const timeoutId = window.setTimeout(() => {
      postGraphFocus(activeTarget)
    }, 70)

    return () => window.clearTimeout(timeoutId)
  }, [activeTarget, isCurrentResult, postGraphFocus, result.html])

  return (
    <div className={`source-graph-panel${fullscreen ? ' source-graph-panel--fullscreen' : ''}`}>
      <SourceGraphStage
        copy={copy}
        graph={graph}
        result={result}
        isCurrentResult={isCurrentResult}
        frameRef={frameRef}
        onFrameLoad={handleFrameLoad}
        onFullscreen={onFullscreen}
        fullscreen={fullscreen}
      />
      <SourceGraphSide
        copy={copy}
        graph={graph}
        activeTarget={activeTarget}
        onPreviewTarget={handlePreviewTarget}
        onRestoreTarget={handleRestoreTarget}
        onSelectTarget={handleSelectTarget}
      />
    </div>
  )
}

export default function SourceProvenanceGraph({ cards, t }) {
  const copy = t?.sourceGraph ?? getUiText('tr').sourceGraph
  const [open, setOpen] = useState(false)
  const [fullscreenOpen, setFullscreenOpen] = useState(false)
  const [activeTargetState, setActiveTargetState] = useState({ key: '', target: null })
  const [result, setResult] = useState({ key: '', html: '', error: false })
  const graph = useMemo(() => buildGraphModel(cards, copy), [cards, copy])
  const requestKey = useMemo(() => JSON.stringify(getSourceGraphPayload(graph)), [graph])
  const completedCount = graph.sources.length
  const panelId = 'source-provenance-graph-panel'
  const activeTarget = activeTargetState.key === requestKey ? activeTargetState.target : null

  const setActiveTarget = useCallback(target => {
    setActiveTargetState({
      key: requestKey,
      target: normalizeFocusTarget(target),
    })
  }, [requestKey])

  useEffect(() => {
    function handleMessage(event) {
      const data = event.data || {}
      if (data.type !== 'sourceGraphFocusChanged') return
      setActiveTarget(data.target)
    }

    window.addEventListener('message', handleMessage)
    return () => window.removeEventListener('message', handleMessage)
  }, [setActiveTarget])

  useEffect(() => {
    if (!fullscreenOpen) return undefined

    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    function handleKeyDown(event) {
      if (event.key === 'Escape') setFullscreenOpen(false)
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [fullscreenOpen])

  useEffect(() => {
    if (!open || completedCount === 0) return undefined

    let cancelled = false

    fetch('/api/visualize/source', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: requestKey,
    })
      .then(response => {
        if (!response.ok) throw new Error(response.statusText)
        return response.text()
      })
      .then(html => {
        if (!cancelled) setResult({ key: requestKey, html, error: false })
      })
      .catch(() => {
        if (!cancelled) setResult({ key: requestKey, html: '', error: true })
      })

    return () => {
      cancelled = true
    }
  }, [completedCount, open, requestKey])

  const handleToggleGraph = useCallback(() => {
    setOpen(current => {
      const nextOpen = !current
      if (!nextOpen) setFullscreenOpen(false)
      return nextOpen
    })
  }, [])

  const isCurrentResult = result.key === requestKey

  return (
    <section className="source-graph-disclosure" aria-labelledby="source-graph-title">
      <div className="source-graph-disclosure-header">
        <div>
          <span className="section-kicker">{copy.kicker}</span>
          <h2 id="source-graph-title">{copy.title}</h2>
          <p>{copy.description}</p>
        </div>
        <button
          className="secondary-action-button source-graph-toggle"
          type="button"
          aria-expanded={open}
          aria-controls={panelId}
          disabled={completedCount === 0}
          onClick={handleToggleGraph}
        >
          {open ? copy.closeGraph : copy.openGraph}
        </button>
      </div>

      {completedCount === 0 && (
        <div className="source-graph-empty">
          <strong>{copy.emptyTitle}</strong>
          <span>{copy.emptyBody}</span>
        </div>
      )}

      {open && completedCount > 0 && (
        <div id={panelId}>
          <SourceGraphPanel
            copy={copy}
            graph={graph}
            result={result}
            isCurrentResult={isCurrentResult}
            activeTarget={activeTarget}
            onActiveTargetChange={setActiveTarget}
            onFullscreen={() => setFullscreenOpen(true)}
          />
        </div>
      )}

      {fullscreenOpen && open && completedCount > 0 && createPortal(
        <div className="source-graph-fullscreen-overlay">
          <button
            className="source-graph-fullscreen-backdrop"
            type="button"
            aria-label={copy.closeFullscreen}
            onClick={() => setFullscreenOpen(false)}
          />
          <div
            className="source-graph-fullscreen"
            role="dialog"
            aria-modal="true"
            aria-labelledby="source-graph-fullscreen-title"
          >
            <div className="source-graph-fullscreen-header">
              <div>
                <span className="kg-modal-kicker">{copy.kicker}</span>
                <h2 className="kg-modal-title" id="source-graph-fullscreen-title">{copy.title}</h2>
              </div>
              <button
                className="kg-modal-close source-graph-fullscreen-close"
                type="button"
                onClick={() => setFullscreenOpen(false)}
                aria-label={copy.closeFullscreen}
              >
                <CloseIcon />
              </button>
            </div>
            <SourceGraphPanel
              copy={copy}
              graph={graph}
              result={result}
              isCurrentResult={isCurrentResult}
              activeTarget={activeTarget}
              onActiveTargetChange={setActiveTarget}
              fullscreen
            />
          </div>
        </div>,
        document.body
      )}
    </section>
  )
}
