import { useEffect, useMemo, useState } from 'react'
import './KGGraph.css'

/**
 * Bilgi grafı bileşeni.
 * Backend /api/visualize endpoint'ine tripletleri gönderir,
 * dönen Pyvis HTML'ini iframe içinde render eder.
 *
 * Props
 * -----
 * triplets  : [[subject, relation, object], ...]
 * highlight : vurgulanacak düğüm adları []
 */
const DEFAULT_LABELS = {
  generating: 'Graf oluşturuluyor...',
  loadError: 'Graf yüklenemedi.',
  waiting: 'Triplet bekleniyor...',
  title: 'Bilgi Grafı',
}

export default function KGGraph({ triplets = [], highlight = [], labels = DEFAULT_LABELS }) {
  const requestKey = useMemo(
    () => JSON.stringify({ triplets, highlight }),
    [triplets, highlight]
  )
  const [result, setResult] = useState({ key: '', html: '', error: false })

  useEffect(() => {
    if (!triplets.length) return

    let cancelled = false

    fetch('/api/visualize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ triplets, highlight }),
    })
      .then(r => {
        if (!r.ok) throw new Error(r.statusText)
        return r.text()
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
  }, [triplets, highlight, requestKey])

  const isCurrentResult = result.key === requestKey

  if (triplets.length > 0 && !isCurrentResult) {
    return (
      <div className="kg-wrapper">
        <div className="kg-state">
          <div className="kg-loading">
            <span /><span /><span />
          </div>
          <p className="kg-hint">{labels.generating}</p>
        </div>
      </div>
    )
  }

  if (isCurrentResult && result.error) {
    return (
      <div className="kg-wrapper">
        <div className="kg-state">
          <p className="kg-hint kg-hint--error">{labels.loadError}</p>
        </div>
      </div>
    )
  }

  if (!triplets.length || !result.html) {
    return (
      <div className="kg-wrapper">
        <div className="kg-state">
          <p className="kg-hint">{labels.waiting}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="kg-wrapper">
      <iframe
        className="kg-frame"
        srcDoc={result.html}
        title={labels.title}
        sandbox="allow-scripts"
      />
    </div>
  )
}
