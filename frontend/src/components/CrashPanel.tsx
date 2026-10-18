import { RotateCcwIcon, TriangleAlertIcon } from 'lucide-react'
import { useEffect } from 'react'

import { Button } from '@/components/ui/button'
import { isChunkLoadError, reloadOnce } from '@/lib/chunkReload'
import { t } from '@/lib/i18n'
import { isRemote, switchInstance } from '@/lib/instance'
import { cn } from '@/lib/utils'

// Il posto di una vista che si è rotta (ErrorBoundary): cosa è successo e le
// uscite. Un chunk che non si scarica è quasi sempre un aggiornamento fatto
// con la pagina aperta: la pagina si ricarica da sola, una volta (reloadOnce),
// e se non basta resta il messaggio che lo dice. Guardando un'altra istanza c'è
// anche il ritorno a questa: la scelta resta nel browser, e un errore dovuto
// ai dati di quella si ripeterebbe a ogni ricarica.
export function CrashPanel({ error, onRetry, fullPage = false }: { error: Error; onRetry?: () => void; fullPage?: boolean }) {
  const newVersion = isChunkLoadError(error)
  useEffect(() => {
    if (newVersion) reloadOnce()
  }, [newVersion, error])
  const panel = (
    <div role="alert" className={cn('mx-auto grid w-full max-w-xl gap-3 rounded-lg border border-red-500/40 bg-red-500/10 p-6', !fullPage && 'mt-10')}>
      <p className="flex items-center gap-2 font-medium">
        <TriangleAlertIcon className="size-5 shrink-0 text-red-600 dark:text-red-400" />
        {newVersion ? t('common.newVersionTitle') : t('common.crashTitle')}
      </p>
      <p className="text-sm text-muted-foreground">{newVersion ? t('common.newVersionHint') : t('common.crashHint')}</p>
      {!newVersion && error.message && <p className="font-mono text-xs break-all text-muted-foreground/80">{error.message}</p>}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" onClick={() => window.location.reload()}>
          <RotateCcwIcon className="size-4" />
          {t('common.reload')}
        </Button>
        {onRetry && (
          <Button variant="outline" size="sm" onClick={onRetry}>
            {t('common.retry')}
          </Button>
        )}
        {isRemote() && (
          <Button variant="ghost" size="sm" onClick={() => switchInstance(null)}>
            {t('instances.backToThis')}
          </Button>
        )}
      </div>
    </div>
  )
  return fullPage ? <div className="flex min-h-svh items-center justify-center p-6">{panel}</div> : panel
}
