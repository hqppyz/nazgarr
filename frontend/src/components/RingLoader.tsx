import { RotateCcwIcon } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import type { RingHandle } from '@/components/ring/types'
import { RingLogo } from '@/components/RingLogo'
import { Button } from '@/components/ui/button'
import { t } from '@/lib/i18n'
import { cn } from '@/lib/utils'

// Caricamento di una pagina intera (libreria, torrent, dashboard…): l'anello
// al centro che ricade sul tavolo a ripetizione, con una frase che cambia
// ogni pochi secondi. Pronto: si raddrizza in una O e svanisce. Errore:
// cade piatto, si spegne, e resta col messaggio e "Riprova".
const LINES = 10
const EVERY_MS = 2600
const FADE_MS = 250

type Phase = 'loading' | 'done' | 'error'

export function RingLoader({
  phase = 'loading',
  error,
  onRetry,
  onExited,
  className,
}: {
  phase?: Phase
  error?: string | null
  onRetry?: () => void
  onExited?: () => void
  className?: string
}) {
  const ring = useRef<RingHandle>(null)
  const [line, setLine] = useState(() => Math.floor(Math.random() * LINES))
  const [fading, setFading] = useState(false)
  const exited = useRef(onExited)
  useEffect(() => {
    exited.current = onExited
  })

  useEffect(() => {
    if (phase !== 'loading') return
    const timer = window.setInterval(() => setLine((n) => (n + 1 + Math.floor(Math.random() * (LINES - 1))) % LINES), EVERY_MS)
    return () => window.clearInterval(timer)
  }, [phase])

  useEffect(() => {
    if (phase === 'error') ring.current?.fall()
    if (phase !== 'done') return
    let cancelled = false
    let timer = 0
    // Senza l'anello 3D (riduci movimento, niente WebGL) non c'è un movimento da aspettare.
    const settled = ring.current?.settle() ?? Promise.resolve()
    void settled.then(() => {
      if (cancelled) return
      setFading(true)
      timer = window.setTimeout(() => exited.current?.(), FADE_MS)
    })
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [phase])

  return (
    <div role="status" aria-live="polite"
         className={cn('flex min-h-[50vh] flex-col items-center justify-center gap-4 text-center', className)}>
      <div className={cn('transition-all ease-out', fading && 'scale-75 opacity-0')} style={{ transitionDuration: `${FADE_MS}ms` }}>
        <RingLogo size={96} hoverable={false} mode="loader" handleRef={ring} />
      </div>
      {phase === 'error' ? (
        <div className="grid max-w-md justify-items-center gap-3">
          <p className="text-sm text-muted-foreground">{t('common.loadFailed')}</p>
          {error && <p className="font-mono text-xs break-all text-muted-foreground/80">{error}</p>}
          {onRetry && (
            <Button variant="outline" size="sm" onClick={onRetry}>
              <RotateCcwIcon className="size-4" />
              {t('common.retry')}
            </Button>
          )}
        </div>
      ) : (
        <p key={line} className={cn('animate-in text-sm text-muted-foreground duration-500 fade-in', fading && 'opacity-0')}>
          {t(`common.loadingLine${line}`)}
        </p>
      )}
      <span className="sr-only">{t('common.loading')}</span>
    </div>
  )
}

// L'anello al posto di una pagina finché la sua query carica, poi il tempo
// della O; se fallisce senza dati, l'anello caduto con l'errore e Riprova.
// null = mostra la pagina. Da chiamare prima di ogni return della pagina.
export function useRingLoader(query: {
  data: unknown
  isPending: boolean
  isError: boolean
  isFetching: boolean
  error: Error | null
  refetch: () => unknown
}) {
  const [shown, setShown] = useState(query.isPending)
  const [retries, setRetries] = useState(0) // un anello nuovo, che ricade, a ogni Riprova
  if (query.isPending && !shown) setShown(true)
  const failed = query.isError && query.data === undefined
  if (!shown && !failed) return null
  const phase: Phase = query.isPending || (failed && query.isFetching) ? 'loading' : failed ? 'error' : 'done'
  return (
    <RingLoader
      key={retries}
      phase={phase}
      error={query.error?.message}
      onRetry={() => {
        setRetries((n) => n + 1)
        void query.refetch()
      }}
      onExited={() => setShown(false)}
    />
  )
}
