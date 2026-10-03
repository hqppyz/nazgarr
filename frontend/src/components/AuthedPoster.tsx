import { ImageOffIcon } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'

import { getToken } from '@/lib/authToken'
import { instancePath } from '@/lib/instance'
import { cn } from '@/lib/utils'

// Il poster è protetto dal login come ogni altra API, e un <img src> non
// manda l'header Authorization: lo si scarica con fetch + token e lo si
// mostra da un object URL — solo quando la card entra nella parte visibile
// della pagina, mai centinaia di richieste al caricamento.
function useAuthedImage(url: string, enabled: boolean) {
  const ref = useRef<HTMLDivElement | null>(null)
  const [visible, setVisible] = useState(false)
  const [src, setSrc] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    const node = ref.current
    if (!enabled || !node || visible) return
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) setVisible(true)
    }, { rootMargin: '300px' })
    observer.observe(node)
    return () => observer.disconnect()
  }, [enabled, visible])

  useEffect(() => {
    if (!visible) return
    let objectUrl: string | null = null
    let cancelled = false
    const token = getToken()
    fetch(instancePath(url), { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then((response) => (response.ok ? response.blob() : Promise.reject(new Error(String(response.status)))))
      .then((blob) => {
        if (cancelled) return
        objectUrl = URL.createObjectURL(blob)
        setSrc(objectUrl)
      })
      .catch(() => !cancelled && setFailed(true))
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [url, visible])

  return { ref, src, failed }
}

export function AuthedPoster({
  contentType,
  tmdbId,
  hasPoster,
  className,
  url,
}: {
  contentType: string
  tmdbId: number
  hasPoster: boolean
  className?: string
  // Un altro endpoint al posto della cache della libreria: i candidati di un
  // upload passano da /api/metadata/posters, che li scarica se mancano.
  url?: string
}) {
  const { ref, src, failed } = useAuthedImage(
    url ?? `/api/library/posters/${contentType === 'tv' ? 'tv' : 'movie'}/${tmdbId}.jpg`,
    hasPoster,
  )
  return (
    <div ref={ref} className={cn('bg-muted', className)}>
      {src && !failed ? (
        <img src={src} alt="" className="h-full w-full object-cover" />
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
      {src && !failed ? <img src={src} alt="" className="size-full object-contain" /> : fallback}
    </div>
  )
}
