import { useEffect, useRef } from 'react'
import { forceSimulation, forceLink, forceManyBody, forceCollide } from 'd3-force'
import { getUiText } from './i18n'

function getNodesDef(labels) {
  return [
    // level 0 — center
    { id: 'center',   level: 0 },
    // level 1 — main branches
    { id: 'kg',        level: 1, label: labels.kgTechnique },
    { id: 'prompt',    level: 1, label: labels.promptTechnique },
    { id: 'embedding', level: 1, label: labels.embeddingModel },
    // level 2 — under kg
    { id: 'kggen',    level: 2, parent: 'kg',     label: 'KG-GEN' },
    { id: 'wicontic', level: 2, parent: 'kg',     label: 'Wicontic' },
    { id: 'wikipedia',level: 2, parent: 'kg',     label: 'Wikipedia' },
    // level 2 — under prompt
    { id: 'temel',    level: 2, parent: 'prompt', label: labels.basicPrompt },
    { id: 'dspy',     level: 2, parent: 'prompt', label: 'DSPy' },
    { id: 'textgrad', level: 2, parent: 'prompt', label: 'TextGrad' },
    // level 2 — under embedding (only visible when wicontic is selected)
    { id: 'contriever',       level: 2, parent: 'embedding', label: 'Contriever' },
    { id: 'bge_m3',           level: 2, parent: 'embedding', label: 'BGE-M3' },
    { id: 'turkish_e5_large', level: 2, parent: 'embedding', label: 'Turkish E5' },
    { id: 'turkish_sbert_mean_nli_stsb', level: 2, parent: 'embedding', label: 'Turkish SBERT' },
    { id: 'mft_random',       level: 2, parent: 'embedding', label: 'MFT Random' },
  ]
}

const LINKS_DEF = [
  { source: 'center',    target: 'kg' },
  { source: 'center',    target: 'prompt' },
  { source: 'center',    target: 'embedding' },
  { source: 'kg',        target: 'kggen' },
  { source: 'kg',        target: 'wicontic' },
  { source: 'kg',        target: 'wikipedia' },
  { source: 'prompt',    target: 'temel' },
  { source: 'prompt',    target: 'dspy' },
  { source: 'prompt',    target: 'textgrad' },
  { source: 'embedding', target: 'contriever' },
  { source: 'embedding', target: 'bge_m3' },
  { source: 'embedding', target: 'turkish_e5_large' },
  { source: 'embedding', target: 'turkish_sbert_mean_nli_stsb' },
  { source: 'embedding', target: 'mft_random' },
]

const R = { 0: 56, 1: 36, 2: 20 }

const isEmbNode = n => n.id === 'embedding' || n.parent === 'embedding'

export default function PlusGraph({ expanded, onToggle, onSend, language = 'tr' }) {
  const labels = getUiText(language).plusGraph
  const anchorRef    = useRef(null)
  const canvasRef    = useRef(null)
  const simRef       = useRef(null)
  const nodesRef     = useRef(null)
  const expandedRef  = useRef(expanded)
  const toggleRef    = useRef(onToggle)
  const sendRef      = useRef(onSend)
  const selectionRef = useRef({ kg: null, prompt: null, embedding: null })

  useEffect(() => { expandedRef.current = expanded }, [expanded])
  useEffect(() => { toggleRef.current   = onToggle  }, [onToggle])
  useEffect(() => { sendRef.current     = onSend    }, [onSend])

  useEffect(() => {
    const canvas = canvasRef.current
    const W = window.innerWidth
    const H = window.innerHeight
    canvas.width  = W
    canvas.height = H
    const ctx = canvas.getContext('2d')

    const rect = anchorRef.current.getBoundingClientRect()
    const CX = rect.left + rect.width  / 2
    const CY = rect.top  + rect.height / 2

    const nodes = getNodesDef(labels).map(n => ({
      ...n, x: CX + (Math.random() - 0.5) * 2, y: CY + (Math.random() - 0.5) * 2,
    }))
    nodes[0].fx = CX
    nodes[0].fy = CY

    // All non-center nodes start pinned to center
    nodes.filter(n => n.level > 0).forEach(n => { n.fx = CX; n.fy = CY })

    const links = LINKS_DEF.map(l => ({ ...l }))
    nodesRef.current = nodes

    const sim = forceSimulation(nodes)
      .force('link', forceLink(links).id(d => d.id)
        .distance(l => {
          const s = typeof l.source === 'object' ? l.source : nodes.find(n => n.id === l.source)
          return s?.level === 0 ? 185 : 100
        })
        .strength(0.55))
      .force('charge',  forceManyBody().strength(-80))
      .force('collide', forceCollide(d => R[d.level] + 12))
      .force('drift', () => {
        nodes.filter(n => n.level > 0).forEach(n => {
          if (n.fx !== undefined && n.fx !== null) return
          n.vx += (Math.random() - 0.5) * 0.04
          n.vy += (Math.random() - 0.5) * 0.04
          if (n.x < 60)      n.vx += 0.4
          if (n.x > W - 60)  n.vx -= 0.4
          if (n.y < 40)      n.vy += 0.4
          if (n.y > H - 40)  n.vy -= 0.4
        })
      })
      .alphaDecay(0)
      .velocityDecay(0.72)
      .on('tick', render)

    simRef.current = sim

    function drawCheckmark(x, y, r) {
      ctx.save()
      ctx.beginPath()
      ctx.moveTo(x - r * 0.38, y + r * 0.02)
      ctx.lineTo(x - r * 0.08, y + r * 0.36)
      ctx.lineTo(x + r * 0.42, y - r * 0.28)
      ctx.strokeStyle = '#1B44D8'
      ctx.lineWidth   = 2.2
      ctx.lineCap     = 'round'
      ctx.lineJoin    = 'round'
      ctx.stroke()
      ctx.restore()
    }

    function drawSendArrow(cx, cy) {
      const s = 2.6
      ctx.save()
      ctx.beginPath()
      ctx.moveTo(cx + (2  - 8) * s, cy + (14 - 8) * s)
      ctx.lineTo(cx + (14 - 8) * s, cy + (2  - 8) * s)
      ctx.moveTo(cx + (14 - 8) * s, cy + (2  - 8) * s)
      ctx.lineTo(cx + (5  - 8) * s, cy + (2  - 8) * s)
      ctx.moveTo(cx + (14 - 8) * s, cy + (2  - 8) * s)
      ctx.lineTo(cx + (14 - 8) * s, cy + (11 - 8) * s)
      ctx.strokeStyle = '#E8E5DF'
      ctx.lineWidth   = 2.4
      ctx.lineCap     = 'round'
      ctx.lineJoin    = 'round'
      ctx.stroke()
      ctx.restore()
    }

    function render() {
      ctx.clearRect(0, 0, W, H)
      const exp = expandedRef.current
      const sel = selectionRef.current
      const showEmbedding = exp && sel.kg === 'wicontic'

      // ── 1. Edges ──
      if (exp) {
        links.forEach(({ source: s, target: t }) => {
          if (typeof s !== 'object' || typeof t !== 'object') return
          if (!showEmbedding && (isEmbNode(s) || isEmbNode(t))) return
          const isMain = s.level === 0
          ctx.beginPath()
          ctx.moveTo(s.x, s.y)
          ctx.lineTo(t.x, t.y)
          ctx.strokeStyle = isMain
            ? 'rgba(27, 68, 216, 0.28)'
            : 'rgba(27, 68, 216, 0.18)'
          ctx.lineWidth = isMain ? 2.2 : 1.5
          ctx.stroke()
        })
      }

      // ── 2. Level-2 nodes ──
      if (exp) {
        nodes.filter(n => n.level === 2).forEach(n => {
          if (!showEmbedding && n.parent === 'embedding') return
          const isSelected = sel[n.parent] === n.id

          ctx.beginPath()
          ctx.arc(n.x, n.y, R[2], 0, Math.PI * 2)
          ctx.fillStyle = '#E8E5DF'
          ctx.fill()
          ctx.fillStyle = 'rgba(136, 136, 136, 0.38)'
          ctx.fill()

          if (isSelected) {
            ctx.strokeStyle = '#1B44D8'
            ctx.lineWidth   = 2.8
          } else {
            ctx.strokeStyle = 'rgba(27, 68, 216, 0.22)'
            ctx.lineWidth   = 1.2
          }
          ctx.stroke()

          if (isSelected) drawCheckmark(n.x, n.y, R[2])

          ctx.font      = '10px Inter, sans-serif'
          ctx.fillStyle = isSelected ? '#1B44D8' : 'rgba(17, 17, 17, 0.58)'
          ctx.textAlign = 'center'
          ctx.fillText(n.label, n.x, n.y + R[2] + 13)
        })
      }

      // ── 3. Level-1 nodes ──
      if (exp) {
        nodes.filter(n => n.level === 1).forEach(n => {
          if (!showEmbedding && n.id === 'embedding') return
          ctx.beginPath()
          ctx.arc(n.x, n.y, R[1], 0, Math.PI * 2)
          ctx.fillStyle = '#E8E5DF'
          ctx.fill()
          ctx.fillStyle   = 'rgba(136, 136, 136, 0.45)'
          ctx.fill()
          ctx.strokeStyle = 'rgba(27, 68, 216, 0.32)'
          ctx.lineWidth   = 1.5
          ctx.stroke()
          ctx.font      = '11px Inter, sans-serif'
          ctx.fillStyle = 'rgba(17, 17, 17, 0.62)'
          ctx.textAlign = 'center'
          ctx.fillText(n.label, n.x, n.y + R[1] + 14)
        })
      }

      // ── 4. Center node ──
      const c = nodes[0]
      const needsEmbedding = sel.kg === 'wicontic'
      const bothSelected   = !!(sel.kg && sel.prompt && (!needsEmbedding || sel.embedding))

      if (bothSelected) {
        const pulse = Math.sin(Date.now() * 0.0028)
        const r     = R[0] * (1 + pulse * 0.10)

        ctx.beginPath()
        ctx.arc(c.x, c.y, r + 18, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(27, 68, 216, ${(0.07 + pulse * 0.06).toFixed(3)})`
        ctx.fill()

        ctx.beginPath()
        ctx.arc(c.x, c.y, r, 0, Math.PI * 2)
        ctx.fillStyle = '#E8E5DF'
        ctx.fill()
        ctx.fillStyle = `rgba(27, 68, 216, ${(0.82 + pulse * 0.08).toFixed(3)})`
        ctx.fill()

        drawSendArrow(c.x, c.y)

        const labelAlpha = (0.45 + pulse * 0.42).toFixed(3)
        ctx.font         = '500 11px Inter, sans-serif'
        ctx.fillStyle    = `rgba(27, 68, 216, ${labelAlpha})`
        ctx.textAlign    = 'center'
        ctx.textBaseline = 'alphabetic'
        ctx.fillText(labels.createGraph, c.x, c.y - r - 14)
      } else {
        ctx.beginPath()
        ctx.arc(c.x, c.y, R[0], 0, Math.PI * 2)
        ctx.fillStyle = '#E8E5DF'
        ctx.fill()
        ctx.fillStyle = 'rgba(27, 68, 216, 0.65)'
        ctx.fill()
        ctx.font         = '300 58px Inter, sans-serif'
        ctx.fillStyle    = '#E8E5DF'
        ctx.textAlign    = 'center'
        ctx.textBaseline = 'middle'
        ctx.fillText(exp ? '−' : '+', c.x, c.y + 3)
        ctx.textBaseline = 'alphabetic'
      }
    }

    function hitLevel2(x, y) {
      if (!expandedRef.current) return null
      const sel = selectionRef.current
      return nodes.find(n => {
        if (n.level !== 2) return false
        if (n.parent === 'embedding' && sel.kg !== 'wicontic') return false
        return Math.hypot(x - n.x, y - n.y) <= R[2]
      }) || null
    }

    function setEmbeddingPinned(pinned) {
      const center = nodes[0]
      nodes.filter(isEmbNode).forEach(n => {
        if (pinned) { n.fx = center.x; n.fy = center.y }
        else        { n.fx = null;     n.fy = null }
      })
      sim.alpha(0.6).restart()
    }

    function onWindowClick(e) {
      const c = nodes[0]
      if (Math.hypot(e.clientX - c.x, e.clientY - c.y) <= R[0]) {
        const sel            = selectionRef.current
        const needsEmbedding = sel.kg === 'wicontic'
        const bothSelected   = !!(sel.kg && sel.prompt && (!needsEmbedding || sel.embedding))
        if (bothSelected) {
          const kgNode  = nodes.find(n => n.id === sel.kg)
          const prNode  = nodes.find(n => n.id === sel.prompt)
          const embNode = nodes.find(n => n.id === sel.embedding)
          sendRef.current?.({
            kg:             sel.kg,
            kgLabel:        kgNode?.label  || sel.kg,
            prompt:         sel.prompt,
            promptLabel:    prNode?.label  || sel.prompt,
            embedding:      sel.embedding  || null,
            embeddingLabel: embNode?.label || sel.embedding || null,
          })
        } else {
          toggleRef.current()
        }
        return
      }

      const hit = hitLevel2(e.clientX, e.clientY)
      if (hit) {
        const sel    = selectionRef.current
        const prevKg = sel.kg

        sel[hit.parent] = sel[hit.parent] === hit.id ? null : hit.id

        if (hit.parent === 'kg') {
          if (prevKg === 'wicontic' && sel.kg !== 'wicontic') {
            // Wicontic deselected → reset embedding, pin embedding nodes
            sel.embedding = null
            setEmbeddingPinned(true)
          } else if (sel.kg === 'wicontic' && expandedRef.current) {
            // Wicontic selected → free embedding nodes
            setEmbeddingPinned(false)
          }
        }
      }
    }

    function onWindowMove(e) {
      const c        = nodes[0]
      const overCenter = Math.hypot(e.clientX - c.x, e.clientY - c.y) <= R[0]
      const overLeaf   = !!hitLevel2(e.clientX, e.clientY)
      document.body.style.cursor = (overCenter || overLeaf) ? 'pointer' : ''
    }

    function onResize() {
      canvas.width  = window.innerWidth
      canvas.height = window.innerHeight
    }

    window.addEventListener('click',     onWindowClick)
    window.addEventListener('mousemove', onWindowMove)
    window.addEventListener('resize',    onResize)

    return () => {
      sim.stop()
      document.body.style.cursor = ''
      window.removeEventListener('click',     onWindowClick)
      window.removeEventListener('mousemove', onWindowMove)
      window.removeEventListener('resize',    onResize)
    }
  }, [labels])

  useEffect(() => {
    const nodes = nodesRef.current
    const sim   = simRef.current
    if (!nodes || !sim) return
    const center = nodes[0]
    const sel    = selectionRef.current

    nodes.filter(n => n.level > 0).forEach(n => {
      if (expanded) {
        // Embedding branch only freed when wicontic is already selected
        if (isEmbNode(n) && sel.kg !== 'wicontic') {
          n.fx = center.fx; n.fy = center.fy
        } else {
          n.fx = null; n.fy = null
        }
      } else {
        n.fx = center.fx; n.fy = center.fy
      }
    })
    sim.alpha(0.9).restart()
  }, [expanded])

  return (
    <>
      <div ref={anchorRef} style={{ width: '100%', height: '100%' }} />
      <canvas ref={canvasRef} style={{
        position: 'fixed', top: 0, left: 0,
        width: '100vw', height: '100vh',
        pointerEvents: 'none', zIndex: 10,
      }} />
    </>
  )
}
