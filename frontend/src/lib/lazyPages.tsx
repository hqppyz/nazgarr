import { lazy, Suspense, useState, type ComponentType } from 'react'

import { RingLoader } from '@/components/RingLoader'

// Le pagine sono chunk a parte (App.tsx): il caricamento iniziale porta solo
// la pagina aperta. Le altre si scaricano in background quando quella ha
// finito (preloadPages), così aprirle dopo è immediato.

const preloaders: Array<() => Promise<unknown>> = []

export function lazyPage<M>(
  load: () => Promise<M>,
  pick: (module: M) => ComponentType,
  { preload = true }: { preload?: boolean } = {},
): ComponentType {
  let loaded: ComponentType | null = null
  let pending: Promise<ComponentType> | null = null
  const fetchPage = () =>
    (pending ??= load().then(
      (module) => (loaded = pick(module)),
      (error: unknown) => {
        pending = null // rete caduta: al prossimo tentativo si riscarica
        throw error
      },
    ))
  // lazy() una volta sola, qui: creato a ogni render rimonterebbe la pagina.
  const Page = lazy(() => fetchPage().then((component) => ({ default: component })))
  if (preload) preloaders.push(fetchPage)

  return function LazyPage() {
    // Già scaricata (precaricata o già vista): la pagina subito, senza
    // passare da Suspense, che mostrerebbe l'anello per un istante. Deciso
    // una volta per montaggio: cambiare tipo di componente la rimonterebbe.
    const [Ready] = useState(() => loaded)
    if (Ready) return <Ready />
    return (
      <Suspense fallback={<RingLoader />}>
        <Page />
      </Suspense>
    )
  }
}

// Scarica le pagine non ancora caricate, una alla volta e solo quando il
// browser è libero: aspetta che `busy()` (le richieste della pagina aperta)
// sia falso, per non rallentarne il caricamento. Restituisce lo stop.
export function preloadPages(busy: () => boolean): () => void {
  const connection = (navigator as Navigator & { connection?: { saveData?: boolean } }).connection
  if (connection?.saveData) return () => {}
  let stopped = false
  const queue = [...preloaders]
  const idle = (run: () => void) =>
    'requestIdleCallback' in window ? window.requestIdleCallback(run, { timeout: 5000 }) : window.setTimeout(run, 200)
  const next = () => {
    if (stopped || queue.length === 0) return
    if (busy()) {
      timer = window.setTimeout(next, 500)
      return
    }
    idle(() => {
      if (stopped) return
      void queue.shift()!().catch(() => undefined).finally(next)
    })
  }
  let timer = window.setTimeout(next, 1000)
  return () => {
    stopped = true
    window.clearTimeout(timer)
  }
}
