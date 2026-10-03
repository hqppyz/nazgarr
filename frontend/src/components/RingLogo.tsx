import { lazy, Suspense, useState, type Ref } from 'react'

import type { RingHandle } from '@/components/ring/types'
import { cn } from '@/lib/utils'

// L'anello del logo. Tre casi:
// - di norma l'anello 3D in WebGL (components/ring/WebGLRing.tsx), caricato a
//   parte perché porta con sé Three.js: fino al primo fotogramma si vede
//   l'immagine statica, che è lo stesso anello fotografato;
// - con "riduci movimento" o senza WebGL, solo l'immagine statica.
// L'immagine (public/ring.png) si rigenera con `npm run render:ring` quando
// cambia l'anello (scripts/render-ring.mjs).
const WebGLRing = lazy(() => import('@/components/ring/WebGLRing').then((m) => ({ default: m.WebGLRing })))

export const RING_STATIC_SRC = '/ring.png'

function canAnimate(): boolean {
  if (typeof window === 'undefined') return false
  if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return false
  try {
    const canvas = document.createElement('canvas')
    return !!(canvas.getContext('webgl2') ?? canvas.getContext('webgl'))
  } catch {
    return false
  }
}

let animated: boolean | null = null

export function RingLogo({
  size = 28,
  className,
  handleRef,
  hoverable = true,
  spinSeconds,
}: {
  size?: number
  className?: string
  handleRef?: Ref<RingHandle>
  hoverable?: boolean
  spinSeconds?: number
}) {
  animated ??= canAnimate()
  const [ready, setReady] = useState(false)
  const still = (
    <img
      src={RING_STATIC_SRC}
      width={size}
      height={size}
      alt=""
      draggable={false}
      className={cn('pointer-events-none select-none', animated && 'absolute inset-0')}
    />
  )
  if (!animated) {
    return (
      <span className={cn('inline-block shrink-0', className)} style={{ width: size, height: size }} role="img" aria-label="Nazgarr">
        {still}
      </span>
    )
  }
  return (
    <span className={cn('relative inline-block shrink-0', className)} style={{ width: size, height: size }}>
      {!ready && still}
      <Suspense fallback={null}>
        <WebGLRing size={size} handleRef={handleRef} hoverable={hoverable} spinSeconds={spinSeconds} onReady={() => setReady(true)} />
      </Suspense>
    </span>
  )
}
