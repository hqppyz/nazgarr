import { ExternalLinkIcon, ServerIcon, TriangleAlertIcon } from 'lucide-react'
import { useEffect } from 'react'

import { useInstances } from '@/api/hooks/instances'
import { Button } from '@/components/ui/button'
import { t } from '@/lib/i18n'
import { activeInstanceId, switchInstance } from '@/lib/instance'
import { safeHref } from '@/lib/safeUrl'

// Quando si guarda un'altra istanza: una striscia che lo ricorda sempre, un
// avviso se è più vecchia di una minor, e niente viste se è bloccata (major
// diversa, o più nuova di questa: decisione dell'utente, 2026-10-03).
export function RemoteGate({ children }: { children: React.ReactNode }) {
  const id = activeInstanceId()
  const { data, isPending } = useInstances(true)
  const instance = data?.instances.find((i) => i.id === id) ?? null

  useEffect(() => {
    // Tolta da un'altra scheda o da un altro browser: si torna a questa.
    if (id !== null && data && !instance) switchInstance(null)
  }, [id, data, instance])

  if (id === null) return <>{children}</>
  if (isPending || !instance) return null
  const status = instance.status
  const compat = status?.compatibility ?? 'unknown'
  const blocked = compat.startsWith('block')
  const back = (
    <Button variant="outline" size="sm" onClick={() => switchInstance(null)}>
      {t('instances.backToThis')}
    </Button>
  )
  const openUi = (
    <Button variant="ghost" size="sm" render={<a href={safeHref(instance.base_url)} target="_blank" rel="noreferrer" />}>
      {t('instances.openItsUi')}
      <ExternalLinkIcon className="size-3.5" />
    </Button>
  )

  if (blocked) {
    return (
      <div className="mx-auto mt-10 grid max-w-xl gap-3 rounded-lg border border-red-500/40 bg-red-500/10 p-6">
        <p className="flex items-center gap-2 font-medium">
          <TriangleAlertIcon className="size-5 text-red-600 dark:text-red-400" />
          {t('instances.blockedTitle', { label: instance.label })}
        </p>
        <p className="text-sm text-muted-foreground">
          {t(`instances.compat.${compat}`)} · {t('instances.version', { version: status?.version ?? '?' })} ·{' '}
          {t('instances.thisInstance')} {data?.local_version}
        </p>
        <div className="flex flex-wrap gap-2">
          {back}
          {openUi}
        </div>
      </div>
    )
  }

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-sky-500/40 bg-sky-500/10 px-3 py-2 text-sm">
        <ServerIcon className="size-4 shrink-0 text-sky-600 dark:text-sky-400" />
        <span className="font-medium">{t('instances.viewing', { label: instance.label })}</span>
        <span className="text-xs text-muted-foreground">
          {status?.version ? t('instances.version', { version: status.version }) : ''}
          {status?.level === 'read' ? ` · ${t('instances.level.read')}` : ''}
        </span>
        <span className="flex-1" />
        {openUi}
        {back}
      </div>
      {compat === 'warn' && (
        <p className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm">
          {t('instances.warnOlder', { label: instance.label, version: status?.version ?? '?', local: data?.local_version ?? '?' })}
        </p>
      )}
      {status && status.status !== 'ok' && (
        <p className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm">
          {t(`instances.status.${status.status}`)}{status.error ? `: ${status.error}` : ''}
        </p>
      )}
      {children}
    </div>
  )
}
