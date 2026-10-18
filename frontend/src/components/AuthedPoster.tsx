import { ImageOffIcon } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'

import { getToken } from '@/lib/authToken'
import { instancePath } from '@/lib/instance'
import { scrollRoot } from '@/lib/scrollRoot'
import { cn } from '@/lib/utils'
import { demoResponse } from '@/lib/uploadDemo'

// Un IntersectionObserver per radice e margine, condiviso da tutte le
// immagini: una griglia di migliaia di poster ne usa due, non uno o due per
// card. La radice è l'area che scorre (lib/scrollRoot): con la finestra i
// margini valevano 0, e un poster si liberava appena uscito dalla vista.
type Shared = { observer: IntersectionObserver; callbacks: Map<Element, (intersecting: boolean) => void> }
const byRoot = new WeakMap<Element, Map<string, Shared>>()
const viewport = new Map<string, Shared>()

function observersOf(root: Element | null): Map<string, Shared> {
  if (!root) return viewport
  let observers = byRoot.get(root)
  if (!observers) {
    observers = new Map()
    byRoot.set(root, observers)
  }
  return observers
}

function watch(node: Element, rootMargin: string, callback: (intersecting: boolean) => void): () => void {
  const root = scrollRoot(node)
  const observers = observersOf(root)
  let shared = observers.get(rootMargin)
  if (!shared) {
    const callbacks = new Map<Element, (intersecting: boolean) => void>()
    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) callbacks.get(entry.target)?.(entry.isIntersecting)
    }, { root, rootMargin })
    shared = { observer, callbacks }
    observers.set(rootMargin, shared)
  }
  const { observer, callbacks } = shared
  callbacks.set(node, callback)
  observer.observe(node)
  return () => {
    observer.unobserve(node)
    callbacks.delete(node)
    if (callbacks.size === 0) {
      observer.disconnect()
      observers.delete(rootMargin)
    }
  }
}

// Si scarica a LOAD_MARGIN dalla parte visibile; con `release` il blob si
// libera quando l'immagine ne è più lontana di KEEP_MARGIN, e tornando vicino
// si richiede (dalla cache HTTP del browser: Cache-Control private, un giorno).
// Senza, una griglia di migliaia di titoli scorsa fino in fondo teneva vivo
// il blob di ogni card montata (audit 2026-10-18). Solo le liste lunghe lo
// chiedono (la griglia, la coda degli upload): il poster di una scheda resta.
const LOAD_MARGIN = '300px'
const KEEP_MARGIN = '1500px'

// Il poster è protetto dal login come ogni altra API, e un <img src> non
// manda l'header Authorization: lo si scarica con fetch + token e lo si
// mostra da un object URL — solo quando la card entra nella parte visibile
// della pagina, mai centinaia di richieste al caricamento.
function useAuthedImage(url: string, enabled: boolean, release = false) {
  const ref = useRef<HTMLDivElement | null>(null)
  const [near, setNear] = useState(false)
  const [src, setSrc] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)
  // Senza `release`, una volta vicina l'immagine resta: niente più da guardare.
  const settled = near && !release

  useEffect(() => {
    const node = ref.current
    if (!enabled || !node || settled) return
    const stopLoad = watch(node, LOAD_MARGIN, (intersecting) => intersecting && setNear(true))
    const stopKeep = release ? watch(node, KEEP_MARGIN, (intersecting) => !intersecting && setNear(false)) : null
    return () => {
      stopLoad()
      stopKeep?.()
    }
  }, [enabled, release, settled])

  useEffect(() => {
    if (!near || failed) return
    let objectUrl: string | null = null
    // La card smontata (un filtro, un'altra pagina) prima che il poster
    // arrivi: la richiesta si interrompe invece di finire per niente.
    const controller = new AbortController()
    const token = getToken()
    // L'upload di esempio del tour: il suo poster non si chiede mai al server.
    const demo = demoResponse(new Request(new URL(url, window.location.origin)))
    ;(demo
      ? Promise.resolve(demo)
      : fetch(instancePath(url), { headers: token ? { Authorization: `Bearer ${token}` } : {}, signal: controller.signal }))
      .then((response) => (response.ok ? response.blob() : Promise.reject(new Error(String(response.status)))))
      .then((blob) => {
        if (controller.signal.aborted) return
        objectUrl = URL.createObjectURL(blob)
        setSrc(objectUrl)
      })
      .catch(() => !controller.signal.aborted && setFailed(true))
    return () => {
      controller.abort()
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl)
        setSrc(null)
      }
    }
  }, [url, near, failed])

  return { ref, src, failed }
}

export function AuthedPoster({
  contentType,
  tmdbId,
  hasPoster,
  className,
  url,
  release = false,
}: {
  contentType: string
  tmdbId: number
  hasPoster: boolean
  className?: string
  // Un altro endpoint al posto della cache della libreria: i candidati di un
  // upload passano da /api/metadata/posters, che li scarica se mancano.
  url?: string
  // Libera il blob quando la card è lontana dalla vista (una lista lunga).
  release?: boolean
}) {
  const { ref, src, failed } = useAuthedImage(
    url ?? `/api/library/posters/${contentType === 'tv' ? 'tv' : 'movie'}/${tmdbId}.jpg`,
    hasPoster,
    release,
  )
  return (
    <div ref={ref} className={cn('bg-muted', className)}>
      {src && !failed ? (
        // Decodificata fuori dal thread principale: una griglia di poster non
        // blocca lo scorrimento mentre arrivano.
        <img src={src} alt="" decoding="async" className="h-full w-full object-cover" />
      ) : (
        <div className="flex h-full w-full items-center justify-center text-muted-foreground">
          <ImageOffIcon className="size-6" />
        </div>
      )}
    </div>
  )
}

// Un'immagine qualunque dalle API (protette dal login), con un segnaposto
// finché non c'è o se manca: es. l'icona di un tracker.
export function AuthedImage({ url, className, fallback }: { url: string; className?: string; fallback: ReactNode }) {
  const { ref, src, failed } = useAuthedImage(url, true)
  return (
    <div ref={ref} className={cn('flex shrink-0 items-center justify-center overflow-hidden', className)}>
      {src && !failed ? <img src={src} alt="" decoding="async" className="size-full object-contain" /> : fallback}
    </div>
  )
}
