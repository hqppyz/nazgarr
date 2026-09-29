import gsap from 'gsap'
import { useEffect, useImperativeHandle, useRef, type Ref } from 'react'
import * as THREE from 'three'
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js'

import type { RingHandle } from '@/components/ring/types'
import { RING_INSCRIPTION, transliterate } from '@/lib/ringScript'
import { cn } from '@/lib/utils'

// Variante 1: vero 3D in WebGL (Three.js). Una fede d'oro bombata (profilo
// ruotato con LatheGeometry), riflessi da una mappa d'ambiente, l'iscrizione
// incisa e luminosa sulla faccia esterna e su quella interna. All'hover il
// bagliore si accende e l'anello si inclina appena verso il cursore; di fondo
// una rotazione lentissima. Si ridisegna solo quando qualcosa si muove.

const TEX_W = 4096
const TEX_H = 1024
const BASE_GLOW = 0.04
const HOVER_GLOW = 5
// Glifi più stretti che alti, come la scrittura dell'anello: a parità di giro
// la frase viene più alta sulla fascia.
const NARROW = 0.78

// Profilo della fascia: una sola curva morbida (super-ellisse) da un bordo
// all'altro, piena davanti e più piatta dentro, come una fede "comoda". Le
// zone con la scritta (al centro di faccia esterna e interna) sono campionate
// uniformi in altezza, così le lettere non si deformano; LatheGeometry dà a
// ogni punto v = indice / ultimo indice.
const R_IN = 1.1 // raggio interno al centro della fascia
const R_OUT = 1.36 // raggio esterno al centro della fascia
const HALF = 0.36 // mezza altezza della fascia
const SHAPE = 3 // esponente della super-ellisse: 2 = mezzo tondo, più alto = più squadrato
const INNER_FLAT = 0.35 // quanto è bombata la faccia interna rispetto all'esterna
const TEXT_ZONE = 0.62 // parte centrale della faccia (in altezza) che porta la scritta
const ZONE_STEPS = 32
const CURVE_STEPS = 18

interface Profile {
  points: THREE.Vector2[]
  outer: [number, number] // indici del profilo della zona scritta esterna (dal basso in alto)
  inner: [number, number] // e di quella interna (dall'alto in basso)
  textHeight: number // altezza nel mondo di ciascuna zona scritta
}

function bandProfile(): Profile {
  const pts: THREE.Vector2[] = []
  const center = (R_IN + R_OUT) / 2
  const aOut = R_OUT - center
  const aIn = center - R_IN
  const pow = (v: number, e: number) => Math.sign(v) * Math.abs(v) ** e
  // x sulla curva per una data y, lato esterno (+1) o interno (-1)
  const xAt = (y: number, side: 1 | -1) => {
    const a = side === 1 ? aOut : aIn
    const k = side === 1 ? 1 : INNER_FLAT
    const bulge = (1 - Math.abs(y / HALF) ** SHAPE) ** (1 / SHAPE)
    return center + side * a * (side === 1 ? bulge : 1 - k + k * bulge)
  }
  const yf = TEXT_ZONE * HALF
  // curva per angolo, dove la pendenza cambia in fretta (vicino ai bordi)
  const curve = (side: 1 | -1, fromY: number, toY: number) => {
    const t0 = Math.asin(pow(fromY / HALF, SHAPE / 2))
    const t1 = Math.asin(pow(toY / HALF, SHAPE / 2))
    for (let i = 1; i < CURVE_STEPS; i++) {
      const t = t0 + ((t1 - t0) * i) / CURVE_STEPS
      const y = HALF * pow(Math.sin(t), 2 / SHAPE)
      pts.push(new THREE.Vector2(xAt(y, side), y))
    }
  }
  const zone = (side: 1 | -1, fromY: number, toY: number) => {
    for (let i = 0; i <= ZONE_STEPS; i++) {
      const y = fromY + ((toY - fromY) * i) / ZONE_STEPS
      pts.push(new THREE.Vector2(xAt(y, side), y))
    }
  }
  pts.push(new THREE.Vector2(center, -HALF))
  curve(1, -HALF, -yf)
  const outerFrom = pts.length
  zone(1, -yf, yf)
  const outerTo = pts.length - 1
  curve(1, yf, HALF)
  pts.push(new THREE.Vector2(center, HALF))
  curve(-1, HALF, yf)
  const innerFrom = pts.length
  zone(-1, yf, -yf)
  const innerTo = pts.length - 1
  curve(-1, -yf, -HALF)
  pts.push(new THREE.Vector2(center, -HALF)) // chiude il profilo
  return { points: pts, outer: [outerFrom, outerTo], inner: [innerFrom, innerTo], textHeight: 2 * yf }
}

// Tratto a pennino a punta larga: lo stesso tracciato ripetuto lungo la
// diagonale del pennino dà il contrasto pieno/filo della calligrafia.
function strokeNib(ctx: CanvasRenderingContext2D, path: Path2D, nib: number, line: number) {
  const steps = 7
  ctx.lineWidth = line
  for (let i = 0; i < steps; i++) {
    const t = (i / (steps - 1) - 0.5) * nib
    ctx.save()
    ctx.translate(t * 0.7, -t * 0.7)
    ctx.stroke(path)
    ctx.restore()
  }
}

// Una riga dell'iscrizione nella striscia di texture di una faccia. La
// texture ha pixel per unità diversi in orizzontale (giro) e in verticale
// (sezione): la scala separata li riporta alle proporzioni giuste sulla
// superficie. `flip`: la faccia interna è percorsa al contrario (dall'alto e
// vista da dentro), il testo va ruotato di 180° per leggersi dritto.
function drawBand(
  ctx: CanvasRenderingContext2D, profile: Profile, face: [number, number], radius: number, flip: boolean,
) {
  const last = profile.points.length - 1
  const [from, to] = face
  const top = Math.min((1 - to / last) * TEX_H, (1 - from / last) * TEX_H)
  const bottom = Math.max((1 - to / last) * TEX_H, (1 - from / last) * TEX_H)
  const bandPx = bottom - top
  const faceHeight = profile.textHeight
  const { glyphs, width } = transliterate(RING_INSCRIPTION)
  const unit = (2 * Math.PI * radius * 0.985) / (width * NARROW) // unità glifo -> mondo: la frase fa tutto il giro
  const sx = unit * NARROW * (TEX_W / (2 * Math.PI * radius))
  const sy = unit * (bandPx / faceHeight)
  const glyphHeight = 1.5 * sy
  const baseY = top + (bandPx - glyphHeight) / 2 + 0.04 * sy
  ctx.save()
  if (flip) {
    ctx.translate(TEX_W, top + bottom)
    ctx.scale(-1, -1)
  }
  for (const g of glyphs) {
    ctx.save()
    ctx.translate(g.x * sx + 0.006 * TEX_W, baseY)
    ctx.scale(sx, sy)
    ctx.transform(1, 0, -0.24, 1, 0.3, 0) // corsivo, inclinato a destra
    strokeNib(ctx, new Path2D(g.d), 0.12, 0.034)
    ctx.restore()
  }
  ctx.restore()
}

function inscriptionCanvas(profile: Profile, color: string, background: string): HTMLCanvasElement {
  const canvas = document.createElement('canvas')
  canvas.width = TEX_W
  canvas.height = TEX_H
  const ctx = canvas.getContext('2d')!
  ctx.fillStyle = background
  ctx.fillRect(0, 0, TEX_W, TEX_H)
  ctx.strokeStyle = color
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  drawBand(ctx, profile, profile.outer, R_OUT, false)
  drawBand(ctx, profile, profile.inner, R_IN, true)
  return canvas
}

// Luce della scritta con alone: la versione nitida sopra una copia sfumata.
// La sfumatura si fa su una tela ridotta a 1/4 e poi ingrandita: stesso
// effetto morbido a una frazione del costo.
function glowCanvas(sharp: HTMLCanvasElement): HTMLCanvasElement {
  const small = document.createElement('canvas')
  small.width = TEX_W / 4
  small.height = TEX_H / 4
  const sctx = small.getContext('2d')!
  sctx.filter = 'blur(3px)'
  sctx.drawImage(sharp, 0, 0, small.width, small.height)
  const canvas = document.createElement('canvas')
  canvas.width = TEX_W
  canvas.height = TEX_H
  const ctx = canvas.getContext('2d')!
  ctx.globalAlpha = 0.7
  ctx.drawImage(small, 0, 0, TEX_W, TEX_H)
  ctx.globalAlpha = 1
  ctx.globalCompositeOperation = 'lighter'
  ctx.drawImage(sharp, 0, 0)
  return canvas
}

// Le tre tele (luce, rilievo, colore) si disegnano una volta sola e le
// condividono tutti gli anelli della pagina: ogni anello le carica solo come
// texture nel proprio contesto WebGL.
let canvases: { glow: HTMLCanvasElement; bump: HTMLCanvasElement; color: HTMLCanvasElement } | null = null

function sharedCanvases(profile: Profile) {
  if (!canvases) {
    const light = inscriptionCanvas(profile, '#ffffff', '#000000')
    canvases = {
      glow: glowCanvas(light),
      bump: inscriptionCanvas(profile, '#000000', '#ffffff'),
      color: inscriptionCanvas(profile, '#3b1d07', '#ffffff'), // incisione scura, quasi bruciata
    }
  }
  return canvases
}

function texture(canvas: HTMLCanvasElement, srgb = false): THREE.CanvasTexture {
  const tex = new THREE.CanvasTexture(canvas)
  tex.wrapS = THREE.RepeatWrapping
  tex.anisotropy = 8
  if (srgb) tex.colorSpace = THREE.SRGBColorSpace
  return tex
}

interface Props {
  size?: number
  className?: string
  handleRef?: Ref<RingHandle>
  hoverable?: boolean
  // Esportazione dell'immagine statica (scripts/render-ring.mjs): il canvas
  // conserva il fotogramma e viene passato qui dopo il primo disegno, fermo.
  onRendered?: (canvas: HTMLCanvasElement) => void
  // Primo fotogramma disegnato: chi usa l'anello può togliere l'immagine statica.
  onReady?: () => void
}

type RingApi = {
  hover: (on: boolean, x?: number, y?: number, instant?: boolean) => void
  flash: () => void
  collapse: (collapsed: boolean) => void
  drop: () => void
}

export function WebGLRing({ size = 120, className, handleRef, hoverable = true, onRendered, onReady }: Props) {
  const mountRef = useRef<HTMLDivElement>(null)
  const api = useRef<RingApi | null>(null)

  useEffect(() => {
    const mount = mountRef.current
    if (!mount) return
    const exporting = onRendered != null
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: exporting })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.setSize(size, size)
    renderer.toneMapping = THREE.ACESFilmicToneMapping
    renderer.outputColorSpace = THREE.SRGBColorSpace
    mount.appendChild(renderer.domElement)

    const scene = new THREE.Scene()
    const pmrem = new THREE.PMREMGenerator(renderer)
    scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture

    const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100)
    camera.position.set(0, 0, 5.8)

    const profile = bandProfile()
    // Luce della scritta (con alone), rilievo dell'incisione, e colore: oro
    // ovunque, bronzo scuro dentro le lettere (si leggono anche da spente).
    const shared = sharedCanvases(profile)
    const glowMap = texture(shared.glow, true)
    const bumpMap = texture(shared.bump)
    const colorMap = texture(shared.color, true)

    const material = new THREE.MeshStandardMaterial({
      color: new THREE.Color('#f3be48'),
      map: colorMap,
      metalness: 1,
      roughness: 0.16,
      bumpMap,
      bumpScale: 0.6,
      emissive: new THREE.Color('#ff5a0a'),
      emissiveMap: glowMap,
      emissiveIntensity: BASE_GLOW,
      side: THREE.DoubleSide,
    })
    const geometry = new THREE.LatheGeometry(profile.points, 320)
    const ring = new THREE.Mesh(geometry, material)
    const pivot = new THREE.Group()
    pivot.add(ring)
    scene.add(pivot)

    // Posa di base: di tre quarti dall'alto, appena ruotato; l'hover aggiunge
    // un'inclinazione verso il cursore.
    const state = { spin: 0, glow: BASE_GLOW, scale: 1, tiltX: 0.46, tiltZ: -0.18, wobbleX: 0, wobbleZ: 0 }
    let dirty = true
    let first = true
    const render = () => {
      ring.rotation.y = state.spin
      pivot.rotation.x = state.tiltX + state.wobbleX
      pivot.rotation.z = state.tiltZ + state.wobbleZ
      material.emissiveIntensity = state.glow
      pivot.scale.setScalar(state.scale)
      renderer.render(scene, camera)
      if (first) {
        first = false
        onReady?.()
      }
    }
    const tick = () => {
      if (document.hidden) return
      if (dirty || gsap.isTweening(state)) {
        render()
        dirty = false
      }
    }
    if (exporting) {
      render()
      onRendered(renderer.domElement)
    } else {
      gsap.ticker.add(tick)
    }

    const pulse = () =>
      gsap.to(state, { glow: HOVER_GLOW * 0.7, duration: 0.35, yoyo: true, repeat: 1, ease: 'sine.inOut' })
    // Il "rullare" di un anello caduto su un tavolo: l'inclinazione sale di
    // colpo all'urto e si smorza mentre il bordo gira sempre più in fretta,
    // poi si posa. Nessun cambio di dimensione né di posizione.
    const wobble = { p: 1 }
    const drop = () => {
      wobble.p = 0
      gsap.to(wobble, {
        p: 1,
        duration: 1.9,
        ease: 'none',
        overwrite: true,
        onUpdate: () => {
          const p = wobble.p
          const tilt = 0.6 * Math.min(1, p / 0.07) * (1 - p) ** 2.2
          const phase = 2 * Math.PI * (1.6 * p + 3.4 * p * p)
          state.wobbleX = tilt * Math.sin(phase)
          state.wobbleZ = tilt * Math.cos(phase)
          dirty = true
        },
        onComplete: () => {
          state.wobbleX = 0
          state.wobbleZ = 0
          dirty = true
        },
      })
    }

    const idle = exporting ? null : gsap.to(state, { spin: `-=${Math.PI * 2}`, duration: 60, ease: 'none', repeat: -1 })
    api.current = {
      hover: (on, x = 0, y = 0, instant = false) => {
        gsap.to(state, {
          glow: on ? HOVER_GLOW : BASE_GLOW,
          duration: instant ? 0 : on ? 0.6 : 1.2,
          ease: on ? 'power2.out' : 'power2.inOut',
          overwrite: 'auto',
        })
        gsap.to(state, {
          tiltX: 0.46 + (on ? y * 0.18 : 0),
          tiltZ: -0.18 + (on ? -x * 0.22 : 0),
          duration: on ? 0.5 : 1,
          ease: 'power2.out',
          overwrite: 'auto',
        })
      },
      flash: () => {
        gsap.to(state, { glow: HOVER_GLOW, duration: 0.4, yoyo: true, repeat: 1, repeatDelay: 0.6, ease: 'sine.inOut' })
      },
      // Apertura/chiusura della sidebar: un lampo; alla chiusura anche la caduta.
      collapse: (collapsed) => {
        pulse()
        if (collapsed) drop()
      },
      drop: () => {
        pulse()
        drop()
      },
    }

    return () => {
      idle?.kill()
      gsap.ticker.remove(tick)
      gsap.killTweensOf(state)
      geometry.dispose()
      material.dispose()
      glowMap.dispose()
      bumpMap.dispose()
      colorMap.dispose()
      pmrem.dispose()
      renderer.dispose()
      mount.removeChild(renderer.domElement)
    }
    // onRendered/onReady servono solo al primo fotogramma
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [size])

  useImperativeHandle(handleRef, () => ({
    flash: () => api.current?.flash(),
    collapse: (collapsed) => api.current?.collapse(collapsed),
    glow: (on, instant) => api.current?.hover(on, 0, 0, instant),
  }))

  // Posizione del cursore rispetto al centro, in [-1, 1]: verso dove inclinarsi.
  const pointer = (e: React.PointerEvent<HTMLDivElement>) => {
    const box = e.currentTarget.getBoundingClientRect()
    return [((e.clientX - box.left) / box.width) * 2 - 1, ((e.clientY - box.top) / box.height) * 2 - 1] as const
  }

  return (
    <div
      ref={mountRef}
      className={cn(hoverable && 'cursor-pointer', className)}
      style={{ width: size, height: size }}
      onPointerEnter={hoverable ? (e) => api.current?.hover(true, ...pointer(e)) : undefined}
      onPointerMove={hoverable ? (e) => api.current?.hover(true, ...pointer(e)) : undefined}
      onPointerLeave={hoverable ? () => api.current?.hover(false) : undefined}
      // Al click la stessa caduta della chiusura della sidebar.
      onClick={hoverable ? () => api.current?.drop() : undefined}
      role="img"
      aria-label="Nazgarr"
    />
  )
}
