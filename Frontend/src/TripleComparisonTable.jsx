import { useMemo, useState } from 'react'
import { getSlotLabel, getUiText } from './i18n'

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

function ensureRow(rowMap, triplet, key) {
  if (!rowMap.has(key)) {
    rowMap.set(key, {
      key,
      subject: normalizeValue(triplet.baş),
      relation: normalizeValue(triplet.ilişki),
      object: normalizeValue(triplet.uç),
      subjectType: normalizeValue(triplet.baş_tipi),
      objectType: normalizeValue(triplet.uç_tipi),
      cards: new Set(),
      inReference: false,
    })
  }

  return rowMap.get(key)
}

function buildComparisonRows(cards, referenceCard) {
  const completedCards = cards.filter(card => card.status === 'done')
  const rowMap = new Map()

  if (referenceCard?.status === 'done') {
    ;(referenceCard.triplets ?? []).forEach(triplet => {
      const key = getTripleKey(triplet)
      if (!key || key === '||||') return

      ensureRow(rowMap, triplet, key).inReference = true
    })
  }

  completedCards.forEach(card => {
    ;(card.triplets ?? []).forEach(triplet => {
      const key = getTripleKey(triplet)
      if (!key || key === '||||') return

      ensureRow(rowMap, triplet, key).cards.add(card.id)
    })
  })

  return [...rowMap.values()]
    .map(row => ({
      ...row,
      matchCount: row.cards.size,
      matchType: row.cards.size > 1 ? 'same' : 'different',
      referenceMatch: row.inReference && row.cards.size > 0,
    }))
    .sort((a, b) => {
      if (b.matchCount !== a.matchCount) return b.matchCount - a.matchCount
      return a.subject.localeCompare(b.subject, 'tr')
    })
}

export default function TripleComparisonTable({ cards, referenceCard, t }) {
  const copy = t?.tripleTable ?? getUiText('tr').tripleTable
  const [filter, setFilter] = useState('all')
  const completedCards = useMemo(() => cards.filter(card => card.status === 'done'), [cards])
  const rows = useMemo(() => buildComparisonRows(cards, referenceCard), [cards, referenceCard])
  const sameCount = rows.filter(row => row.matchType === 'same').length
  const differentCount = rows.filter(row => row.matchType === 'different').length
  const referenceMatchCount = rows.filter(row => row.referenceMatch).length
  const hasReference = referenceCard?.status === 'done'
  const visibleRows = rows.filter(row => {
    if (filter === 'all') return true
    if (filter === 'reference-match') return row.referenceMatch
    return row.matchType === filter
  })

  if (completedCards.length === 0 && !referenceCard) {
    return (
      <section className="triple-compare" aria-label={copy.aria}>
        <div className="triple-compare-empty">
          <span>{copy.emptyKicker}</span>
          <strong>{copy.emptyMessage}</strong>
        </div>
      </section>
    )
  }

  return (
    <section className="triple-compare" aria-label={copy.aria}>
      <div className="triple-compare-header">
        <div>
          <span>{copy.detailedComparison}</span>
          <h2>{copy.matrixTitle}</h2>
        </div>
        <div className="triple-filter-group" aria-label={copy.filtersAria}>
          <button
            type="button"
            className={`triple-filter ${filter === 'all' ? 'active' : ''}`}
            onClick={() => setFilter('all')}
          >
            {copy.all} <strong>{rows.length}</strong>
          </button>
          <button
            type="button"
            className={`triple-filter ${filter === 'same' ? 'active' : ''}`}
            onClick={() => setFilter('same')}
          >
            {copy.same} <strong>{sameCount}</strong>
          </button>
          <button
            type="button"
            className={`triple-filter ${filter === 'different' ? 'active' : ''}`}
            onClick={() => setFilter('different')}
          >
            {copy.different} <strong>{differentCount}</strong>
          </button>
          {hasReference && (
            <button
              type="button"
              className={`triple-filter ${filter === 'reference-match' ? 'active' : ''}`}
              onClick={() => setFilter('reference-match')}
            >
              {copy.referenceMatch} <strong>{referenceMatchCount}</strong>
            </button>
          )}
        </div>
      </div>

      <div className="triple-compare-scroll">
        <table className="triple-table">
          <thead>
            <tr>
              <th>{copy.match}</th>
              <th>{copy.reference}</th>
              <th>{copy.subject}</th>
              <th>{copy.relation}</th>
              <th>{copy.object}</th>
              <th>{copy.type}</th>
              {completedCards.map(card => {
                const originalIndex = cards.findIndex(item => item.id === card.id)
                return <th key={card.id}>{getSlotLabel(originalIndex, t ?? getUiText('tr'))}</th>
              })}
            </tr>
          </thead>
          <tbody>
            {visibleRows.map(row => (
              <tr key={row.key}>
                <td>
                  <div className="match-badge-stack">
                    {hasReference && (
                      <span className={`match-badge match-badge--reference ${row.inReference ? 'present' : 'missing'}`}>
                        {copy.refShort} {row.inReference ? '✓' : '-'}
                      </span>
                    )}
                    <span className={`match-badge match-badge--${row.matchType}`}>
                      {completedCards.length > 0 ? `${row.matchCount}/${completedCards.length}` : '-'}
                    </span>
                  </div>
                </td>
                <td>
                  <span className={`reference-presence ${row.inReference ? 'present' : 'missing'}`}>
                    {row.inReference ? copy.present : '-'}
                  </span>
                </td>
                <td>{row.subject || '-'}</td>
                <td>{row.relation || '-'}</td>
                <td>{row.object || '-'}</td>
                <td>
                  <span className="type-pair">
                    {row.subjectType || '-'} <span>/</span> {row.objectType || '-'}
                  </span>
                </td>
                {completedCards.map(card => (
                  <td key={card.id}>
                    <span className={`slot-presence ${row.cards.has(card.id) ? 'present' : 'missing'}`}>
                      {row.cards.has(card.id) ? copy.present : '-'}
                    </span>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>

        {visibleRows.length === 0 && (
          <div className="triple-compare-empty triple-compare-empty--inside">
            <strong>{copy.noRowsForFilter}</strong>
          </div>
        )}
      </div>
    </section>
  )
}
