import { useState, useEffect, useMemo, useRef } from 'react'
import './App.css'
import GraphCanvas from './GraphCanvas'
import ResultCard  from './ResultCard'
import TripleComparisonTable from './TripleComparisonTable'
import SourceProvenanceGraph from './SourceProvenanceGraph'
import { downloadJson, downloadText, parseImportedTriples } from './utils/triplesIO'
import {
  LANGUAGE_OPTIONS,
  getInitialLanguage,
  getOptionLabel,
  getSlotLabel,
  getUiText,
  saveLanguage,
} from './i18n'

const GROUPS = [
  {
    id: 'veri',
    cx: 0.1, cy: 0.28,
    nodes: [
      { id: 'wikipedia',      labelKey: 'wikipedia',      type: 'step' },
      { id: 'wikidata',       labelKey: 'wikidata',       type: 'step' },
      { id: 'academic',       labelKey: 'academic',       type: 'step' },
      { id: 'dataCollection', labelKey: 'dataCollection', type: 'step' },
    ],
    links: [
      { source: 'wikipedia', target: 'dataCollection' },
      { source: 'wikidata',  target: 'dataCollection' },
      { source: 'academic',  target: 'dataCollection' },
    ],
  },
  {
    id: 'llm',
    cx: 0.9, cy: 0.22,
    nodes: [
      { id: 'llm',              labelKey: 'llm',              type: 'step' },
      { id: 'tripleExtraction', labelKey: 'tripleExtraction', type: 'step' },
      { id: 'apeDspy',          labelKey: 'apeDspy',          type: 'step' },
    ],
    links: [
      { source: 'apeDspy', target: 'llm' },
      { source: 'llm',     target: 'tripleExtraction' },
    ],
  },
  {
    id: 'dogrulama',
    cx: 0.1, cy: 0.75,
    nodes: [
      { id: 'wikontic',             labelKey: 'wikontic',             type: 'step' },
      { id: 'ontologyValidation',   labelKey: 'ontologyValidation',   type: 'step' },
      { id: 'costOptimization',     labelKey: 'costOptimization',     type: 'step' },
    ],
    links: [
      { source: 'wikontic',           target: 'ontologyValidation' },
      { source: 'ontologyValidation', target: 'costOptimization' },
    ],
  },
  {
    id: 'sonuc',
    cx: 0.9, cy: 0.78,
    nodes: [
      { id: 'entityDeduplication', labelKey: 'entityDeduplication', type: 'step' },
      { id: 'knowledgeGraph',      labelKey: 'knowledgeGraph',      type: 'person' },
      { id: 'triples22m',          labelKey: 'triples22m',          type: 'person' },
    ],
    links: [
      { source: 'entityDeduplication', target: 'knowledgeGraph' },
      { source: 'knowledgeGraph',      target: 'triples22m' },
    ],
  },
]

const MAX = 300

const KG_OPTIONS = [
  { id: 'kggen', label: 'KG-GEN' },
  { id: 'wicontic', label: 'Wicontic' },
  { id: 'wikipedia', label: 'Wikipedia' },
]

const PROMPT_OPTIONS = [
  { id: 'temel', labelKey: 'basicPrompt' },
  { id: 'ape', label: 'APE' },
  { id: 'dspy', label: 'DSPy' },
  { id: 'textgrad', label: 'TextGrad' },
]

const EMBEDDING_OPTIONS = [
  { id: 'contriever', label: 'Contriever' },
  { id: 'bge_m3', label: 'BGE-M3' },
  { id: 'turkish_e5_large', label: 'Turkish E5' },
  { id: 'turkish_sbert_mean_nli_stsb', label: 'Turkish SBERT' },
  { id: 'mft_random', label: 'MFT Random' },
]

const ONTOLOGY_LANGUAGE_OPTIONS = [
  { id: 'en', labelKey: 'englishOntology' },
  { id: 'tr', labelKey: 'turkishOntology' },
]

const SCIENTIFIC_FORMATS = [
  { id: 'json', label: 'JSON', extension: 'json', mime: 'application/json;charset=utf-8' },
  { id: 'csv', label: 'CSV', extension: 'csv', mime: 'text/csv;charset=utf-8' },
]

function getLocalizedGroups(t) {
  return GROUPS.map(group => ({
    ...group,
    nodes: group.nodes.map(node => ({
      ...node,
      label: t.graphGroups[node.labelKey] || node.id,
    })),
  }))
}

function getCardStats(cards) {
  const completedCards = cards.filter(card => card.status === 'done')
  const entitySet = new Set()
  const relationSet = new Set()
  let tripleCount = 0

  completedCards.forEach(card => {
    const triplets = card.triplets ?? []
    tripleCount += triplets.length
    triplets.forEach(triplet => {
      if (triplet.baş) entitySet.add(triplet.baş)
      if (triplet.uç) entitySet.add(triplet.uç)
      if (triplet.ilişki) relationSet.add(triplet.ilişki)
    })
  })

  return {
    completedCount: completedCards.length,
    tripleCount,
    entityCount: entitySet.size,
    relationCount: relationSet.size,
  }
}

function getTripleKey(triplet) {
  return [
    String(triplet?.baş || '').trim().toLocaleLowerCase('tr-TR'),
    String(triplet?.ilişki || '').trim().toLocaleLowerCase('tr-TR'),
    String(triplet?.uç || '').trim().toLocaleLowerCase('tr-TR'),
  ].join('||')
}

function getReferenceMetrics(cards, referenceCard) {
  if (referenceCard?.status !== 'done') return null

  const referenceKeys = new Set(
    (referenceCard.triplets ?? [])
      .map(getTripleKey)
      .filter(key => key && key !== '||||')
  )
  const slotKeys = cards
    .filter(card => card.status === 'done')
    .flatMap(card => (card.triplets ?? []).map(getTripleKey))
    .filter(key => key && key !== '||||')

  if (referenceKeys.size === 0) {
    return {
      precision: null,
      recall: null,
      matchedCount: 0,
      slotTripleCount: slotKeys.length,
      referenceTripleCount: 0,
    }
  }

  const matchedKeys = new Set(slotKeys.filter(key => referenceKeys.has(key)))
  const matchedSlotCount = slotKeys.filter(key => referenceKeys.has(key)).length

  return {
    precision: slotKeys.length > 0 ? matchedSlotCount / slotKeys.length : null,
    recall: matchedKeys.size / referenceKeys.size,
    matchedCount: matchedKeys.size,
    slotTripleCount: slotKeys.length,
    referenceTripleCount: referenceKeys.size,
  }
}

function formatPercent(value) {
  if (value === null || value === undefined) return '-'
  return `${Math.round(value * 100)}%`
}

function formatDuration(ms) {
  if (!Number.isFinite(ms) || ms <= 0) return '-'
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)}s`
}

function getAverageDuration(cards) {
  const durations = cards
    .filter(card => card.status === 'done' && Number.isFinite(card.durationMs))
    .map(card => card.durationMs)

  if (durations.length === 0) return null
  return durations.reduce((sum, value) => sum + value, 0) / durations.length
}

function getExperimentFingerprint(text) {
  const normalized = String(text || '').trim()
  if (!normalized) return 'sha:pending'

  let hash = 0
  for (let i = 0; i < normalized.length; i += 1) {
    hash = ((hash << 5) - hash + normalized.charCodeAt(i)) | 0
  }

  return `sha:${Math.abs(hash).toString(16).padStart(8, '0').slice(0, 8)}`
}

function getAuditEvents(cards, referenceCard, hasText, t) {
  const events = []

  events.push({
    id: 'input',
    label: t.app.auditInputReceived,
    detail: hasText ? t.app.auditInputReady : t.app.auditInputPending,
    status: hasText ? 'done' : 'pending',
  })

  events.push({
    id: 'reference',
    label: t.app.auditReference,
    detail: referenceCard ? referenceCard.fileName : t.app.auditReferencePending,
    status: referenceCard ? 'done' : 'pending',
  })

  cards.forEach((card, index) => {
    events.push({
      id: card.id,
      label: `${getSlotLabel(index, t)} · ${card.kgLabel || card.kgType}`,
      detail: card.status === 'done'
        ? `${card.triplets?.length ?? 0} ${t.app.tripleUnit} · ${formatDuration(card.durationMs)}`
        : card.status === 'error'
          ? (card.errorMessage || t.app.llmRequestFailed)
          : t.app.auditSlotRunning,
      status: card.status,
    })
  })

  return events
}

function safeFilePart(value) {
  return String(value || 'triples')
    .trim()
    .replace(/\.json$/i, '')
    .replace(/[^a-z0-9-_]+/gi, '-')
    .replace(/^-+|-+$/g, '')
    .toLowerCase() || 'triples'
}

function escapeCsv(value) {
  const text = String(value ?? '')
  if (!/[",\n\r]/.test(text)) return text
  return `"${text.replace(/"/g, '""')}"`
}

function getExportRows(cards, referenceCard, t) {
  const rows = []

  cards
    .forEach((card, index) => {
      if (card.status !== 'done') return

      ;(card.triplets ?? []).forEach((triplet, tripletIndex) => {
        rows.push({
          id: `${card.id}-${tripletIndex}`,
          slot: getSlotLabel(index, t),
          source: card.kgType ?? '',
          prompt: card.promptType ?? '',
          model: card.model ?? '',
          embedding: card.embeddingModel ?? '',
          ontology_language: card.ontologyLanguage ?? '',
          subject: triplet.baş ?? '',
          subject_type: triplet.baş_tipi ?? '',
          relation: triplet.ilişki ?? '',
          object: triplet.uç ?? '',
          object_type: triplet.uç_tipi ?? '',
          evidence: triplet.kaynak_cumle ?? '',
          reference: false,
        })
      })
    })

  if (referenceCard?.status === 'done') {
    ;(referenceCard.triplets ?? []).forEach((triplet, tripletIndex) => {
      rows.push({
        id: `reference-${tripletIndex}`,
        slot: t.app.referenceSlot,
        source: referenceCard.fileName ?? 'reference',
        prompt: 'ground-truth',
        model: '',
        embedding: '',
        ontology_language: '',
        subject: triplet.baş ?? '',
        subject_type: triplet.baş_tipi ?? '',
        relation: triplet.ilişki ?? '',
        object: triplet.uç ?? '',
        object_type: triplet.uç_tipi ?? '',
        evidence: triplet.kaynak_cumle ?? '',
        reference: true,
      })
    })
  }

  return rows
}

function rowsToCsv(rows) {
  const headers = [
    'slot',
    'source',
    'prompt',
    'model',
    'embedding',
    'ontology_language',
    'subject',
    'subject_type',
    'relation',
    'object',
    'object_type',
    'evidence',
    'reference',
  ]

  return [
    headers.join(','),
    ...rows.map(row => headers.map(header => escapeCsv(row[header])).join(',')),
  ].join('\n')
}

function getSourceGraphCards(cards, t) {
  return cards.map((card, index) => ({
    ...card,
    slotLabel: getSlotLabel(index, t),
    sourceLetter: String.fromCharCode(65 + index),
    kgLabel: getOptionLabel(KG_OPTIONS, card.kgType, t),
    promptLabel: getOptionLabel(PROMPT_OPTIONS, card.promptType || 'temel', t),
    embeddingLabel: card.embeddingModel
      ? getOptionLabel(EMBEDDING_OPTIONS, card.embeddingModel, t)
      : t.sourceGraph.notApplicable,
    ontologyLabel: card.ontologyLanguage
      ? getOptionLabel(ONTOLOGY_LANGUAGE_OPTIONS, card.ontologyLanguage, t)
      : t.app.ontologyNotUsed,
  }))
}

function App() {
  const [language, setLanguage] = useState(getInitialLanguage)
  const [text, setText]           = useState('')
  const [models, setModels]       = useState([])
  const [model, setModel]         = useState('')
  const [submitted, setSubmitted] = useState(false)
  const [cards, setCards]         = useState([])
  const [referenceCard, setReferenceCard] = useState(null)
  const [referenceImportError, setReferenceImportError] = useState('')
  const [isReferenceDragActive, setIsReferenceDragActive] = useState(false)
  const [selectedKg, setSelectedKg] = useState('wikipedia')
  const [selectedPrompt, setSelectedPrompt] = useState('temel')
  const [selectedEmbedding, setSelectedEmbedding] = useState('contriever')
  const [selectedOntologyLanguage, setSelectedOntologyLanguage] = useState('en')
  const referenceInputRef = useRef(null)
  const wiconticSettingsRef = useRef(null)
  const previousKgRef = useRef(selectedKg)
  const t = getUiText(language)
  const graphGroups = useMemo(() => getLocalizedGroups(t), [t])

  useEffect(() => {
    fetch('/api/models')
      .then(r => r.json())
      .then(data => {
        setModels(data)
        if (data.length > 0) setModel(data[0].id)
      })
  }, [])

  useEffect(() => {
    saveLanguage(language)
    document.documentElement.lang = language
  }, [language])

  useEffect(() => {
    const previousKg = previousKgRef.current
    previousKgRef.current = selectedKg

    if (selectedKg !== 'wicontic' || previousKg === 'wicontic') return

    const prefersReducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    requestAnimationFrame(() => {
      wiconticSettingsRef.current?.scrollIntoView({
        behavior: prefersReducedMotion ? 'auto' : 'smooth',
        block: 'center',
      })
    })
  }, [selectedKg])

  const isActive = text.length > 0
  const summaryStats = getCardStats(cards)
  const referenceMetrics = getReferenceMetrics(cards, referenceCard)
  const availableEmbeddingOptions = EMBEDDING_OPTIONS
  const completedCards = cards.filter(card => card.status === 'done')
  const runningCards = cards.filter(card => card.status === 'loading')
  const hasExportableRows = completedCards.length > 0 || Boolean(referenceCard)
  const averageDuration = getAverageDuration(cards)
  const inputFingerprint = getExperimentFingerprint(text)
  const currentSourceLabel = getOptionLabel(KG_OPTIONS, selectedKg, t)
  const currentPromptLabel = getOptionLabel(PROMPT_OPTIONS, selectedPrompt, t)
  const auditEvents = getAuditEvents(
    cards.map(card => ({
      ...card,
      kgLabel: getOptionLabel(KG_OPTIONS, card.kgType, t),
    })),
    referenceCard,
    Boolean(text.trim()),
    t
  )
  const sourceGraphCards = useMemo(() => getSourceGraphCards(cards, t), [cards, t])
  const workflowSteps = [
    { id: 'setup', label: t.app.workflowSetup, active: !submitted },
    { id: 'run', label: t.app.workflowRun, active: submitted && runningCards.length > 0 },
    { id: 'compare', label: t.app.workflowCompare, active: submitted && runningCards.length === 0 },
    { id: 'inspect', label: t.app.workflowInspect, active: completedCards.length > 0 },
    { id: 'export', label: t.app.workflowExport, active: completedCards.length > 0 || Boolean(referenceCard) },
  ]

  function handleSend() {
    if (!text.trim()) return
    setSubmitted(true)
  }

  function handleReferenceFile(file) {
    if (!file) return
    const reader = new FileReader()

    reader.onload = () => {
      try {
        const parsed = parseImportedTriples(reader.result, t.importErrors)
        setReferenceCard({
          id: `reference-${Date.now()}`,
          fileName: file.name,
          status: 'done',
          triplets: parsed.triplets,
          highlight: parsed.highlight,
          skipped: parsed.skipped,
          total: parsed.total,
        })
        setReferenceImportError('')
      } catch (error) {
        setReferenceImportError(error.message || t.app.referenceReadError)
      }
    }

    reader.onerror = () => {
      setReferenceImportError(t.app.fileReadError)
    }

    reader.readAsText(file)
  }

  function handleReferenceDrop(event) {
    event.preventDefault()
    setIsReferenceDragActive(false)
    handleReferenceFile(event.dataTransfer.files?.[0])
  }

  function handleClearReference() {
    setReferenceCard(null)
    setReferenceImportError('')
    if (referenceInputRef.current) {
      referenceInputRef.current.value = ''
    }
  }

  function handleExportCard(card, slotLabel, type = 'generated') {
    const exportedAt = new Date().toISOString()
    const isReference = type === 'reference'
    const fileStem = isReference
      ? `reference-${safeFilePart(card.fileName)}`
      : `${safeFilePart(slotLabel)}-${safeFilePart(getOptionLabel(KG_OPTIONS, card.kgType, t))}`

    downloadJson({
      schema_version: 1,
      exported_at: exportedAt,
      type,
      metadata: isReference
        ? {
            file_name: card.fileName,
            input_text: text,
            skipped: card.skipped ?? 0,
            total: card.total ?? card.triplets?.length ?? 0,
          }
        : {
            slot: slotLabel,
            model: card.model,
            kg_type: card.kgType ?? null,
            prompt_type: card.promptType ?? null,
            embedding_model: card.embeddingModel ?? null,
            ontology_language: card.ontologyLanguage ?? null,
            started_at: card.startedAt ?? null,
            completed_at: card.completedAt ?? null,
            duration_ms: card.durationMs ?? null,
            input_text: card.text ?? text,
          },
      triplets: card.triplets ?? [],
      highlight: card.highlight ?? [],
    }, `${fileStem}-${exportedAt.slice(0, 10)}.json`)
  }

  function getGeneratedSlotExport(card, slotLabel) {
    return {
      slot: slotLabel,
      metadata: {
        model: card.model,
        kg_type: card.kgType ?? null,
        prompt_type: card.promptType ?? null,
        embedding_model: card.embeddingModel ?? null,
        ontology_language: card.ontologyLanguage ?? null,
        started_at: card.startedAt ?? null,
        completed_at: card.completedAt ?? null,
        duration_ms: card.durationMs ?? null,
      },
      triplets: card.triplets ?? [],
      highlight: card.highlight ?? [],
    }
  }

  function getReferenceExport(card) {
    if (!card) return null

    return {
      metadata: {
        file_name: card.fileName,
        skipped: card.skipped ?? 0,
        total: card.total ?? card.triplets?.length ?? 0,
      },
      triplets: card.triplets ?? [],
      highlight: card.highlight ?? [],
    }
  }

  function handleExportAll() {
    const exportedAt = new Date().toISOString()

    downloadJson({
      schema_version: 1,
      exported_at: exportedAt,
      input_text: text,
      reference: getReferenceExport(referenceCard),
      slots: cards
        .filter(card => card.status === 'done')
        .map(card => getGeneratedSlotExport(
          card,
          getSlotLabel(cards.findIndex(item => item.id === card.id), t)
        )),
    }, `comparison-bundle-${exportedAt.slice(0, 10)}.json`)
  }

  function handleExportScientificFormat(formatId) {
    const format = SCIENTIFIC_FORMATS.find(item => item.id === formatId)
    if (!format) return

    const exportedAt = new Date().toISOString()
    const rows = getExportRows(cards, referenceCard, t)
    const fileStem = `sdp-${safeFilePart(inputFingerprint)}-${exportedAt.slice(0, 10)}`

    if (formatId === 'json') {
      downloadJson({
        schema_version: 1,
        exported_at: exportedAt,
        input_hash: inputFingerprint,
        rows,
      }, `${fileStem}.json`)
      return
    }

    if (formatId === 'csv') {
      downloadText(rowsToCsv(rows), `${fileStem}.${format.extension}`, format.mime)
    }
  }

  function handleOntologyLanguageChange(language) {
    setSelectedOntologyLanguage(language)
  }

  function handleAddSlot() {
    const embedding = selectedKg === 'wicontic'
      ? selectedEmbedding
      : null

    handleGraphSend({
      kg: selectedKg,
      prompt: selectedPrompt,
      embedding,
      ontologyLanguage: selectedKg === 'wicontic' ? selectedOntologyLanguage : null,
    })
  }

  async function handleGraphSend(sel) {
    if (cards.length >= 3) return
    const cardId = Date.now()
    const startedAt = Date.now()

    setCards(prev => [...prev, {
      id:             cardId,
      model,
      text,
      kgType:         sel.kg,
      promptType:     sel.prompt,
      embeddingModel: sel.embedding || null,
      ontologyLanguage: sel.ontologyLanguage || null,
      status:         'loading',
      triplets:       [],
      highlight:      [],
      errorMessage:   '',
      startedAt:      new Date(startedAt).toISOString(),
      completedAt:    null,
      durationMs:     null,
    }])

    try {
      const res = await fetch('/api/extract', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({
          text,
          model,
          prompt_type:     sel.prompt || 'temel',
          kg_type:         sel.kg,
          embedding_model: sel.embedding || 'contriever',
          ontology_language: sel.ontologyLanguage || 'en',
        }),
      })
      if (!res.ok) {
        let message = res.statusText
        try {
          const err = await res.json()
          message = err.detail || message
        } catch {
          // Keep the HTTP status text when the backend does not return JSON.
        }
        throw new Error(message)
      }
      const data = await res.json()
      const completedAt = Date.now()
      setCards(prev => prev.map(c => c.id === cardId
        ? {
            ...c,
            status: 'done',
            triplets: data.triplets,
            highlight: data.highlight ?? [],
            errorMessage: '',
            completedAt: new Date(completedAt).toISOString(),
            durationMs: completedAt - startedAt,
          }
        : c
      ))
    } catch (error) {
      const completedAt = Date.now()
      setCards(prev => prev.map(c => c.id === cardId
        ? {
            ...c,
            status: 'error',
            errorMessage: error.message || t.app.llmRequestFailed,
            completedAt: new Date(completedAt).toISOString(),
            durationMs: completedAt - startedAt,
          }
        : c
      ))
    }
  }

  return (
    <div className="app-shell">
      <GraphCanvas groups={graphGroups} hidden={isActive} />

      <aside className="studio-sidebar" aria-label={t.app.sidebarAria}>
        <div className="brand-lockup">
          <span>{t.app.brandResearch}</span>
          <strong>{t.app.brandStudio}</strong>
        </div>

        <section className="setup-card">
          <div className="setup-icon" aria-hidden="true">E</div>
          <div>
            <h2>{t.app.experimentSetup}</h2>
            <p>{t.app.version}</p>
          </div>
        </section>

        <section className="api-health-panel" aria-label={t.app.systemHealth}>
          <div className="health-row">
            <span>{t.app.wikonticApi}</span>
            <strong>{selectedKg === 'wicontic' ? t.app.selected : t.app.onDemand}</strong>
          </div>
          <div className="health-row">
            <span>{t.app.modelCatalog}</span>
            <strong>{models.length || '-'}</strong>
          </div>
          <div className="health-row">
            <span>{t.app.reproducibility}</span>
            <strong>{inputFingerprint}</strong>
          </div>
        </section>

        <section className="reference-import" aria-labelledby="reference-import-title">
          <div className="reference-import-header">
            <div>
              <span className="reference-import-kicker">{t.app.referenceTriples}</span>
              <h2 id="reference-import-title">{t.app.groundTruth}</h2>
            </div>
            {referenceCard && (
              <button
                className="reference-clear-button"
                type="button"
                onClick={handleClearReference}
                aria-label={t.app.clearReferenceAria}
              >
                ×
              </button>
            )}
          </div>

          <input
            ref={referenceInputRef}
            className="reference-file-input"
            type="file"
            accept=".json,application/json"
            onClick={event => {
              event.currentTarget.value = ''
            }}
            onChange={event => handleReferenceFile(event.target.files?.[0])}
          />

          {referenceCard ? (
            <div className="reference-loaded">
              <span className="reference-file-name">{referenceCard.fileName}</span>
              <strong>{referenceCard.triplets.length} {t.app.tripleUnit}</strong>
              {referenceCard.skipped > 0 && (
                <small>{referenceCard.skipped} {t.app.skippedRows}</small>
              )}
            </div>
          ) : (
            <div
              className={`reference-dropzone ${isReferenceDragActive ? 'drag-active' : ''}`}
              onDragEnter={event => {
                event.preventDefault()
                setIsReferenceDragActive(true)
              }}
              onDragOver={event => event.preventDefault()}
              onDragLeave={() => setIsReferenceDragActive(false)}
              onDrop={handleReferenceDrop}
            >
              <button
                className="reference-import-button"
                type="button"
                onClick={() => referenceInputRef.current?.click()}
              >
                {t.app.importJson}
              </button>
              <span>{t.app.dropJson}</span>
            </div>
          )}

          {referenceImportError && (
            <p className="reference-import-error">{referenceImportError}</p>
          )}
        </section>

        <div className="studio-controls">
          <section className="control-group" aria-labelledby="prompt-tech-title">
            <div className="control-title" id="prompt-tech-title">
              <span className="nav-icon" aria-hidden="true">P</span>
              {t.app.promptTech}
            </div>
            <div className="segmented-options">
              {PROMPT_OPTIONS.map(option => (
                <button
                  key={option.id}
                  className={`segmented-option ${selectedPrompt === option.id ? 'active' : ''}`}
                  type="button"
                  onClick={() => setSelectedPrompt(option.id)}
                >
                  {getOptionLabel(PROMPT_OPTIONS, option.id, t)}
                </button>
              ))}
            </div>
          </section>

          <section className="control-group" aria-labelledby="source-title">
            <div className="control-title" id="source-title">
              <span className="nav-icon" aria-hidden="true">S</span>
              {t.app.source}
            </div>
            <div className="segmented-options">
              {KG_OPTIONS.map(option => (
                <button
                  key={option.id}
                  className={`segmented-option ${selectedKg === option.id ? 'active' : ''}`}
                  type="button"
                  onClick={() => setSelectedKg(option.id)}
                >
                  {getOptionLabel(KG_OPTIONS, option.id, t)}
                </button>
              ))}
            </div>
          </section>

          {selectedKg === 'wicontic' && (
            <div className="wicontic-settings" ref={wiconticSettingsRef}>
              <section className="control-group" aria-labelledby="ontology-language-title">
                <div className="control-title" id="ontology-language-title">
                  <span className="nav-icon" aria-hidden="true">O</span>
                  {t.app.ontology}
                </div>
                <div className="segmented-options">
                  {ONTOLOGY_LANGUAGE_OPTIONS.map(option => (
                    <button
                      key={option.id}
                      className={`segmented-option ${selectedOntologyLanguage === option.id ? 'active' : ''}`}
                      type="button"
                      onClick={() => handleOntologyLanguageChange(option.id)}
                    >
                      {getOptionLabel(ONTOLOGY_LANGUAGE_OPTIONS, option.id, t)}
                    </button>
                  ))}
                </div>
              </section>

              <section className="control-group" aria-labelledby="embedding-title">
                <div className="control-title" id="embedding-title">
                  <span className="nav-icon" aria-hidden="true">M</span>
                  {t.app.embeddingModel}
                </div>
                <select
                  className="model-select"
                  value={selectedEmbedding}
                  onChange={e => setSelectedEmbedding(e.target.value)}
                >
                  {availableEmbeddingOptions.map(option => (
                    <option key={option.id} value={option.id}>{option.label}</option>
                  ))}
                </select>
              </section>
            </div>
          )}
        </div>

        <nav className="studio-nav" aria-label={t.app.selectedWorkflowAria}>
          <div className="studio-nav-item">
            <span className="nav-icon" aria-hidden="true">P</span>
            {currentPromptLabel}
          </div>
          <div className="studio-nav-item">
            <span className="nav-icon" aria-hidden="true">S</span>
            {getOptionLabel(KG_OPTIONS, selectedKg, t)}
          </div>
          <div className={`studio-nav-item ${selectedKg === 'wicontic' ? '' : 'muted'}`}>
            <span className="nav-icon" aria-hidden="true">M</span>
            {selectedKg === 'wicontic'
              ? `${getOptionLabel(ONTOLOGY_LANGUAGE_OPTIONS, selectedOntologyLanguage, t)} / ${getOptionLabel(EMBEDDING_OPTIONS, selectedEmbedding, t)}`
              : t.app.embeddingNotRequired}
          </div>
        </nav>

        <div className="sidebar-field">
          <label className="model-label" htmlFor="model-select">{t.app.modelSelection}</label>
          <select
            id="model-select"
            className="model-select"
            value={model}
            onChange={e => setModel(e.target.value)}
          >
            {models.map(m => (
              <option key={m.id} value={m.id}>{m.label}</option>
            ))}
          </select>
        </div>

      </aside>

      <main className={`page ${submitted ? 'submitted' : ''}`}>
        <header className="topbar">
          <nav className="workflow-steps" aria-label={t.app.workflowAria}>
            {workflowSteps.map((step, index) => (
              <span
                key={step.id}
                className={`workflow-step ${step.active ? 'active' : ''}`}
                aria-current={step.active ? 'step' : undefined}
              >
                <span className="workflow-step-index">{index + 1}</span>
                {step.label}
              </span>
            ))}
          </nav>
          <div className="topbar-actions">
            <div className="language-toggle" role="group" aria-label={t.language.ariaLabel}>
              {LANGUAGE_OPTIONS.map(option => (
                <button
                  key={option.id}
                  className={`language-toggle-button ${language === option.id ? 'active' : ''}`}
                  type="button"
                  aria-pressed={language === option.id}
                  aria-label={`${t.language.selectLanguage}: ${t.language[option.id]}`}
                  onClick={() => setLanguage(option.id)}
                >
                  <span>{option.shortLabel}</span>
                  <strong>{t.language[option.id]}</strong>
                </button>
              ))}
            </div>
            <button className="run-button" type="button" disabled={!text.trim()} onClick={handleSend}>
              {t.app.runComparison}
            </button>
          </div>
        </header>

        <div className={`container ${submitted ? 'submitted' : ''}`}>
          <section className="hero-copy">
            <div>
              <span className="hero-kicker">{t.app.empiricalKicker}</span>
              <h1 className="title">{t.app.title}</h1>
              <p className="subtitle">{t.app.subtitle}</p>
              <div className="experiment-fingerprint" aria-label={t.app.experimentFingerprint}>
                <span>{t.app.experimentFingerprint}</span>
                <strong>{inputFingerprint}</strong>
              </div>
            </div>
            <div className="summary-pills" aria-label={t.app.summaryAria}>
              <div className="summary-pill">
                <span>{t.app.activeSlots}</span>
                <strong>{String(cards.length).padStart(2, '0')}</strong>
              </div>
              <div className="summary-pill">
                <span>{t.app.avgLatency}</span>
                <strong>{formatDuration(averageDuration)}</strong>
              </div>
              <div className="summary-pill">
                <span>{t.app.groundTruth}</span>
                <strong>{referenceCard ? t.app.set : t.app.missing}</strong>
              </div>
            </div>
          </section>

          <section className={`input-wrapper ${submitted ? 'submitted' : ''}`}>
            <div className="input-header">
              <div>
                <span className="input-kicker">{t.app.inputParagraph}</span>
                <h2 id="research-text-label">{t.app.researchText}</h2>
              </div>
              <div className="input-mode-strip" aria-label={t.app.inputModesAria}>
                <span className="input-mode active">{t.app.singleText}</span>
                <span className="input-mode">{currentPromptLabel}</span>
                <span className="input-mode">{currentSourceLabel}</span>
              </div>
            </div>
            <div className="textarea-wrapper">
              <label className="sr-only" htmlFor="research-text">{t.app.researchText}</label>
              <textarea
                id="research-text"
                className="text-input"
                value={text}
                onChange={(e) => setText(e.target.value.slice(0, MAX))}
                placeholder={t.app.textPlaceholder}
                rows={6}
                aria-describedby="research-text-help"
              />
            </div>
            <div className="input-metrics">
              <span className={`char-count ${text.length === MAX ? 'limit' : ''}`}>
                {t.app.characters} <strong>{text.length}</strong> / {MAX}
              </span>
              <span>{t.app.tokens} <strong>{Math.ceil(text.trim().length / 4) || 0}</strong></span>
              <span id="research-text-help">{t.app.readyForBenchmark}</span>
            </div>
          </section>
        </div>

        {submitted && (
          <section className="comparison-section">
            <div className="analysis-grid">
              <section className={`performance-summary ${referenceMetrics ? 'performance-summary--with-reference' : ''}`} aria-label={t.app.performanceSummaryAria}>
                <div className="summary-metric">
                  <span>{t.app.totalConfigs}</span>
                  <strong>{cards.length}</strong>
                </div>
                <div className="summary-metric">
                  <span>{t.app.completed}</span>
                  <strong>{summaryStats.completedCount}</strong>
                </div>
                <div className="summary-metric">
                  <span>{t.app.avgLatency}</span>
                  <strong>{formatDuration(averageDuration)}</strong>
                </div>
                <div className="summary-metric">
                  <span>{t.app.triples}</span>
                  <strong>{summaryStats.tripleCount}</strong>
                </div>
                <div className="summary-metric">
                  <span>{t.app.entities}</span>
                  <strong>{summaryStats.entityCount}</strong>
                </div>
                <div className="summary-metric">
                  <span>{t.app.relations}</span>
                  <strong>{summaryStats.relationCount}</strong>
                </div>
                {referenceMetrics && (
                  <>
                    <div className="summary-metric summary-metric--reference">
                      <span>{t.app.precision}</span>
                      <strong>{formatPercent(referenceMetrics.precision)}</strong>
                    </div>
                    <div className="summary-metric summary-metric--reference">
                      <span>{t.app.recall}</span>
                      <strong>{formatPercent(referenceMetrics.recall)}</strong>
                    </div>
                  </>
                )}
              </section>

            </div>

            <div className="comparison-header">
              <div>
                <h2>{t.app.comparisonSlots}</h2>
                <span>{t.app.liveBenchmark}</span>
              </div>
              <div className="comparison-actions">
                <strong>{cards.length}/3</strong>
                <button
                  className="secondary-action-button"
                  type="button"
                  disabled={!hasExportableRows}
                  onClick={handleExportAll}
                >
                  {t.app.exportAll}
                </button>
                <button
                  className="add-slot-button"
                  type="button"
                  disabled={cards.length >= 3}
                  onClick={handleAddSlot}
                >
                  {t.app.addSlot}
                </button>
              </div>
            </div>
            <div className="results-row">
              {referenceCard && (
                <ResultCard
                  variant="reference"
                  slotLabel={t.app.referenceSlot}
                  text={text}
                  {...referenceCard}
                  onDelete={handleClearReference}
                  onExport={() => handleExportCard(referenceCard, t.app.referenceSlot, 'reference')}
                  t={t}
                />
              )}
              {cards.map(card => (
                <ResultCard
                  key={card.id}
                  slotLabel={getSlotLabel(cards.findIndex(item => item.id === card.id), t)}
                  slotIndex={cards.findIndex(item => item.id === card.id)}
                  {...card}
                  kgLabel={getOptionLabel(KG_OPTIONS, card.kgType, t)}
                  promptLabel={getOptionLabel(PROMPT_OPTIONS, card.promptType || 'temel', t)}
                  embeddingLabel={card.embeddingModel ? getOptionLabel(EMBEDDING_OPTIONS, card.embeddingModel, t) : null}
                  ontologyLabel={card.ontologyLanguage ? getOptionLabel(ONTOLOGY_LANGUAGE_OPTIONS, card.ontologyLanguage, t) : null}
                  promptType={card.promptType}
                  onDelete={() => setCards(prev => prev.filter(c => c.id !== card.id))}
                  onExport={() => handleExportCard(
                    card,
                    getSlotLabel(cards.findIndex(item => item.id === card.id), t),
                    'generated'
                  )}
                  t={t}
                />
              ))}
              {cards.length < 3 && (
                <div className="plus-slot">
                  <button className="plus-slot-button" type="button" onClick={handleAddSlot}>
                    <span>+</span>
                    {t.app.addConfiguredSlot}
                  </button>
                </div>
              )}
            </div>

            <TripleComparisonTable cards={cards} referenceCard={referenceCard} t={t} />

            <SourceProvenanceGraph cards={sourceGraphCards} t={t} />

            <section className="methodology-section" aria-labelledby="methodology-title">
              <div className="methodology-intro">
                <span className="section-kicker">{t.app.auditKicker}</span>
                <h2 id="methodology-title">{t.app.methodologyTitle}</h2>
                <p>{t.app.methodologyDescription}</p>
              </div>

              <div className="methodology-grid">
                <article className="audit-card">
                  <div className="section-heading-row">
                    <h3>{t.app.auditTrail}</h3>
                    <span>{auditEvents.length} {t.app.events}</span>
                  </div>
                  <ol className="audit-timeline">
                    {auditEvents.map(event => (
                      <li className={`audit-event audit-event--${event.status}`} key={event.id}>
                        <span className="audit-marker" aria-hidden="true" />
                        <div>
                          <strong>{event.label}</strong>
                          <p>{event.detail}</p>
                        </div>
                      </li>
                    ))}
                  </ol>
                </article>

                <article className="export-panel">
                  <div className="section-heading-row">
                    <h3>{t.app.exportCenter}</h3>
                    <span>{t.app.scientificFormats}</span>
                  </div>
                  <div className="format-grid" aria-label={t.app.scientificFormats}>
                    {SCIENTIFIC_FORMATS.map(format => (
                      <button
                        className="format-chip"
                        type="button"
                        key={format.id}
                        disabled={!hasExportableRows}
                        onClick={() => handleExportScientificFormat(format.id)}
                      >
                        {format.label}
                      </button>
                    ))}
                  </div>
                </article>
              </div>
            </section>
          </section>
        )}
      </main>
    </div>
  )
}

export default App
