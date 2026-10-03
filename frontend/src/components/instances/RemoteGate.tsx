import { ExternalLinkIcon, TriangleAlertIcon, Undo2Icon } from 'lucide-react'
import { useEffect } from 'react'

import { useInstances, type Instance } from '@/api/hooks/instances'
import { instanceDot } from '@/components/instances/InstanceSwitcher'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { t } from '@/lib/i18n'
import { activeInstanceId, switchInstance } from '@/lib/instance'
import { safeHref } from '@/lib/safeUrl'
import { cn } from '@/lib/utils'

function useActiveInstance(): { instance: Instance | null; localVersion: string | undefined; loading: boolean } {
  const id = activeInstanceId()
  const { data, isPending } = useInstances(true)
  return {
    instance: data?.instances.find((i) => i.id === id) ?? null,
    localVersion: data?.local_version,
    loading: id !== null && isPending,
  }
}

// Nella barra in alto, quando si guarda un'altra istanza: chi è, la versione
// (con l'avviso se è più vecchia), la sua interfaccia e il ritorno a questa.
export function RemotePill() {
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
    <span className="flex h-8 items-center gap-1.5 rounded-md border border-sky-500/40 bg-sky-500/10 pr-1 pl-2.5 text-xs">
      <span className={cn('size-2 shrink-0 rounded-full', instanceDot(instance))} />
      <span className="max-w-40 truncate font-medium" title={t('instances.viewingHelp', { label: instance.label })}>
        {instance.label}
      </span>
      {status?.version && <span className="hidden text-muted-foreground sm:inline">{status.version}</span>}
      {status?.level === 'read' && <span className="hidden text-muted-foreground sm:inline">· {t('instances.level.read')}</span>}
      {problem && (
        <Tooltip>
          <TooltipTrigger render={<span className="text-amber-600 dark:text-amber-400" aria-label={problem} />}>
            <TriangleAlertIcon className="size-3.5" />
          </TooltipTrigger>
          <TooltipContent className="max-w-xs">{problem}</TooltipContent>
        </Tooltip>
      )}
      <Button variant="ghost" size="icon-xs" title={t('instances.openItsUi')}
              render={<a href={safeHref(instance.base_url)} target="_blank" rel="noreferrer" />}>
        <ExternalLinkIcon className="size-3.5" />
      </Button>
      <Button variant="ghost" size="icon-xs" title={t('instances.backToThis')} onClick={() => switchInstance(null)}>
        <Undo2Icon className="size-3.5" />
      </Button>
    </span>
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
