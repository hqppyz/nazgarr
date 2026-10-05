import { ExternalLinkIcon, TriangleAlertIcon, Undo2Icon } from 'lucide-react'
import { useEffect } from 'react'

import { useInstances, type Instance } from '@/api/hooks/instances'
import { instanceDot } from '@/components/instances/InstanceSwitcher'
import { Button } from '@/components/ui/button'
import { t } from '@/lib/i18n'
import { activeInstanceId, switchInstance } from '@/lib/instance'
import { safeHref } from '@/lib/safeUrl'
import { cn } from '@/lib/utils'
import { InfoPopover } from '@/components/InfoPopover'

function useActiveInstance(): { instance: Instance | null; localVersion: string | undefined; loading: boolean } {
  const id = activeInstanceId()
  const { data, isPending } = useInstances(true)
  return {
    instance: data?.instances.find((i) => i.id === id) ?? null,
    localVersion: data?.local_version,
    loading: id !== null && isPending,
  }
}

// Sotto l'intestazione, fuori dallo scorrimento: una sola striscia, la stessa
// su ogni pagina, finché si guarda un'altra istanza. Chi è, la versione (con
// l'avviso se è più vecchia o non risponde), la sua interfaccia, il ritorno.
export function RemoteBar() {
  const { instance, localVersion } = useActiveInstance()
  if (!instance) return null
  const status = instance.status
  const compat = status?.compatibility ?? 'unknown'
  const problem = status && status.status !== 'ok'
    ? `${t(`instances.status.${status.status}`)}${status.error ? `: ${status.error}` : ''}`
    : compat === 'warn'
      ? t('instances.warnOlder', { label: instance.label, version: status?.version ?? '?', local: localVersion ?? '?' })
      : null
  return (
    <div role="status"
         className="flex min-h-10 shrink-0 items-center gap-2 border-b border-sky-500/40 bg-sky-500/15 px-3 text-sm md:px-6">
      <span className={cn('size-2.5 shrink-0 rounded-full', instanceDot(instance))} />
      <span className="min-w-0 truncate" title={t('instances.viewingHelp', { label: instance.label })}>
        {t('instances.viewing', { label: instance.label })}
      </span>
      {status?.version && <span className="hidden shrink-0 text-muted-foreground sm:inline">· {status.version}</span>}
      {status?.level === 'read' && (
        <span className="hidden shrink-0 text-muted-foreground sm:inline">· {t('instances.level.read')}</span>
      )}
      {problem && (
        // Un popover e non un tooltip: sul telefono il testo è nascosto, e un
        // tooltip al tocco non si apre.
        <InfoPopover content={problem} className="flex min-w-0 items-center gap-1 p-1 text-amber-700 dark:text-amber-400">
          <TriangleAlertIcon className="size-4 shrink-0" />
          <span className="hidden truncate lg:inline">{problem}</span>
        </InfoPopover>
      )}
      <span className="ml-auto flex shrink-0 items-center gap-1">
        <Button variant="ghost" size="sm" title={t('instances.openItsUi')}
                render={<a href={safeHref(instance.base_url)} target="_blank" rel="noreferrer" />}>
          <ExternalLinkIcon className="size-4" />
          <span className="hidden md:inline">{t('instances.openItsUi')}</span>
        </Button>
        <Button variant="outline" size="sm" title={t('instances.backToThis')} onClick={() => switchInstance(null)}>
          <Undo2Icon className="size-4" />
          <span className="hidden sm:inline">{t('instances.backToThis')}</span>
        </Button>
      </span>
    </div>
  )
}

// Le viste di un'altra istanza: niente se è bloccata (major diversa, o più
// nuova di questa: decisione dell'utente, 2026-10-03), altrimenti le viste.
export function RemoteGate({ children }: { children: React.ReactNode }) {
  const id = activeInstanceId()
  const { data } = useInstances(true)
  const { instance, localVersion, loading } = useActiveInstance()

  useEffect(() => {
    // Tolta da un'altra scheda o da un altro browser: si torna a questa.
    if (id !== null && data && !instance) switchInstance(null)
  }, [id, data, instance])

  if (id === null) return <>{children}</>
  if (loading || !instance) return null
  const status = instance.status
  const compat = status?.compatibility ?? 'unknown'
  if (!compat.startsWith('block')) return <>{children}</>
  return (
    <div className="mx-auto mt-10 grid max-w-xl gap-3 rounded-lg border border-red-500/40 bg-red-500/10 p-6">
      <p className="flex items-center gap-2 font-medium">
        <TriangleAlertIcon className="size-5 text-red-600 dark:text-red-400" />
        {t('instances.blockedTitle', { label: instance.label })}
      </p>
      <p className="text-sm text-muted-foreground">
        {t(`instances.compat.${compat}`)} · {t('instances.version', { version: status?.version ?? '?' })} ·{' '}
        {t('instances.thisInstance')} {localVersion}
      </p>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" onClick={() => switchInstance(null)}>
          {t('instances.backToThis')}
        </Button>
        <Button variant="ghost" size="sm" render={<a href={safeHref(instance.base_url)} target="_blank" rel="noreferrer" />}>
          {t('instances.openItsUi')}
          <ExternalLinkIcon className="size-3.5" />
        </Button>
      </div>
    </div>
  )
}
