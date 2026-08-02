import { useEffect, useRef } from 'react'
import {
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCollide,
} from 'd3-force'

export default function GraphCanvas({ groups, hidden }) {
  const canvasRef = useRef(null)

  useEffect(() => {
    const canvas = canvasRef.current
    let W = window.innerWidth
    let H = window.innerHeight
    canvas.width = W
    canvas.height = H
    const ctx = canvas.getContext('2d')

    // --- Düz node/link listeleri ---
    const allNodes = []
    const allLinks = []

    groups.forEach((g, gi) => {
      g.nodes.forEach((n, i) => {
        const angle = (i / g.nodes.length) * Math.PI * 2
        const r = 55 + Math.random() * 25
        allNodes.push({
          ...n,
          groupIdx: gi,
          x: g.cx * W + Math.cos(angle) * r,
          y: g.cy * H + Math.sin(angle) * r,
        })
      })
      g.links.forEach(l => {
        const srcOk = g.nodes.find(n => n.id === l.source)
        const tgtOk = g.nodes.find(n => n.id === l.target)
        if (srcOk && tgtOk) allLinks.push({ ...l })
      })
    })

    // --- Her grubun sabit hızlı anchor'ı ---
    const anchors = groups.map(g => {
      const speed = 0.35 + Math.random() * 0.35   // her grup farklı hız
      const angle = Math.random() * Math.PI * 2
      return {
        x: g.cx * W,
        y: g.cy * H,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        speed,
      }
    })

    let uiRects = []
    function updateRects() {
      const el = document.querySelector('.container')
      uiRects = el ? [el.getBoundingClientRect()] : []
    }
    updateRects()
    const rectInterval = setInterval(updateRects, 500)

    // --- Anchor hareketi (her tick'te çalışır) ---
    function moveAnchors() {
      const PAD = 70

      anchors.forEach(a => {
        // Sabıt hızla hareket
        a.x += a.vx
        a.y += a.vy

        // Canvas duvarlarından saf yansıma
        if (a.x < PAD)     { a.x = PAD;     a.vx =  Math.abs(a.vx) }
        if (a.x > W - PAD) { a.x = W - PAD; a.vx = -Math.abs(a.vx) }
        if (a.y < PAD)     { a.y = PAD;     a.vy =  Math.abs(a.vy) }
        if (a.y > H - PAD) { a.y = H - PAD; a.vy = -Math.abs(a.vy) }

        // UI dikdörtgeninden yansıma
        uiRects.forEach(r => {
          const M = 90
          const inX = a.x > r.left - M && a.x < r.right  + M
          const inY = a.y > r.top  - M && a.y < r.bottom + M
          if (!inX || !inY) return

          const dL = a.x - (r.left   - M)
          const dR = (r.right  + M) - a.x
          const dT = a.y - (r.top    - M)
          const dB = (r.bottom + M) - a.y
          const min = Math.min(dL, dR, dT, dB)

          if (min === dL) { a.vx = -Math.abs(a.vx); a.x = r.left   - M }
          else if (min === dR) { a.vx =  Math.abs(a.vx); a.x = r.right  + M }
          else if (min === dT) { a.vy = -Math.abs(a.vy); a.y = r.top    - M }
          else                 { a.vy =  Math.abs(a.vy); a.y = r.bottom + M }
        })

        // Hızı sabitle (yansıma sonrası kayma olmasın)
        const spd = Math.hypot(a.vx, a.vy)
        if (spd > 0) { a.vx = (a.vx / spd) * a.speed; a.vy = (a.vy / spd) * a.speed }
      })
    }

    // --- Simülasyon ---
    const sim = forceSimulation(allNodes)
      .force('link', forceLink(allLinks).id(d => d.id).distance(75).strength(0.5))
      .force('charge', forceManyBody().strength(-60))
      .force('collide', forceCollide(32))
      // Anchor hareketi her tick'te güncellenir
      .force('anchorDrift', () => moveAnchors())
      // Node'lar kendi grubunun anchor'ına hafifçe çekilir
      .force('groupAttract', () => {
        allNodes.forEach(n => {
          const a = anchors[n.groupIdx]
          if (!a) return
          n.vx += (a.x - n.x) * 0.04
          n.vy += (a.y - n.y) * 0.04
        })
      })
      .alphaDecay(0)
      .velocityDecay(0.5)
      .on('tick', render)

    // --- Sürükleme ---
    let dragging = null

    function findNode(x, y) {
      let best = null, bestDist = 30
      allNodes.forEach(n => {
        const d = Math.hypot(n.x - x, n.y - y)
        if (d < bestDist) { best = n; bestDist = d }
      })
      return best
    }

    function isOverUI(x, y) {
      return uiRects.some(r =>
        x >= r.left - 10 && x <= r.right + 10 &&
        y >= r.top - 10  && y <= r.bottom + 10
      )
    }

    function onMouseDown(e) {
      if (isOverUI(e.clientX, e.clientY)) return
      const node = findNode(e.clientX, e.clientY)
      if (node) {
        dragging = node
        node.fx = node.x
        node.fy = node.y
        sim.alphaTarget(0.3).restart()
        document.body.style.cursor = 'grabbing'
        e.preventDefault()
      }
    }

    function onMouseMove(e) {
      if (dragging) {
        dragging.fx = e.clientX
        dragging.fy = e.clientY
        return
      }
      const node = findNode(e.clientX, e.clientY)
      document.body.style.cursor =
        (!isOverUI(e.clientX, e.clientY) && node) ? 'grab' : ''
    }

    function onMouseUp() {
      if (!dragging) return
      dragging.fx = null
      dragging.fy = null
      sim.alphaTarget(0)
      dragging = null
      document.body.style.cursor = ''
    }

    window.addEventListener('mousedown', onMouseDown)
    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)

    // --- Render ---
    function render() {
      ctx.clearRect(0, 0, W, H)

      allLinks.forEach(({ source: s, target: t }) => {
        if (typeof s !== 'object' || typeof t !== 'object') return
        ctx.beginPath()
        ctx.moveTo(s.x, s.y)
        ctx.lineTo(t.x, t.y)
        ctx.strokeStyle = 'rgba(27, 68, 216, 0.22)'
        ctx.lineWidth = 1.2
        ctx.stroke()
      })

      allNodes.forEach(n => {
        const r = n.type === 'person' ? 14 : 10
        ctx.beginPath()
        ctx.arc(n.x, n.y, r, 0, Math.PI * 2)
        ctx.fillStyle = n.type === 'person'
          ? 'rgba(27, 68, 216, 0.65)'
          : 'rgba(136, 136, 136, 0.45)'
        ctx.fill()
        ctx.font = '12px Inter, sans-serif'
        ctx.fillStyle = 'rgba(17, 17, 17, 0.62)'
        ctx.textAlign = 'center'
        ctx.fillText(n.label || n.id, n.x, n.y + r + 14)
      })
    }

    function onResize() {
      W = window.innerWidth
      H = window.innerHeight
      canvas.width = W
      canvas.height = H
      updateRects()
    }
    window.addEventListener('resize', onResize)

    return () => {
      sim.stop()
      clearInterval(rectInterval)
      window.removeEventListener('mousedown', onMouseDown)
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onMouseUp)
      window.removeEventListener('resize', onResize)
    }
  }, [groups])

  return <canvas ref={canvasRef} className={`graph-canvas ${hidden ? 'graph-hidden' : ''}`} />
}
