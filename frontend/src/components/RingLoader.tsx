import { useEffect, useState } from 'react'

import { RingLogo } from '@/components/RingLogo'
import { t } from '@/lib/i18n'
import { cn } from '@/lib/utils'

// Caricamento di una pagina intera (libreria, torrent, dashboard…): l'anello
// che gira più veloce del solito, al centro, con una frase che cambia ogni
// pochi secondi al posto di "Caricamento…".
const LINES = 10
const EVERY_MS = 2600

export function RingLoader({ className }: { className?: string }) {
  const [line, setLine] = useState(() => Math.floor(Math.random() * LINES))
  useEffect(() => {
    const timer = window.setInterval(() => setLine((n) => (n + 1 + Math.floor(Math.random() * (LINES - 1))) % LINES), EVERY_MS)
    return () => window.clearInterval(timer)
  }, [])
  return (
    <div role="status" aria-live="polite"
         className={cn('flex min-h-[50vh] flex-col items-center justify-center gap-4 text-center', className)}>
      <RingLogo size={96} hoverable={false} spinSeconds={2.4} />
      <p key={line} className="animate-in text-sm text-muted-foreground duration-500 fade-in">
        {t(`common.loadingLine${line}`)}
      </p>
      <span className="sr-only">{t('common.loading')}</span>
    </div>
  )
}
