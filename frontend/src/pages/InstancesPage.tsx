import { ServerIcon } from 'lucide-react'
import { Link } from 'react-router-dom'

import { useInstances, useInstanceSnapshot, type Instance } from '@/api/hooks/instances'
import { instanceDot, useLocalName } from '@/components/instances/InstanceSwitcher'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { t } from '@/lib/i18n'
import { activeInstanceId, switchInstance } from '@/lib/instance'
import { formatBytes } from '@/lib/library-filters'
import { relativeFromNow } from '@/lib/time'
import { cn } from '@/lib/utils'

const ACTIVE_UPLOADS = ['identifying', 'awaiting_match', 'analyzing', 'awaiting_decision', 'queued', 'running']

// Una scheda per istanza: lo stato in breve, letto con la sua API key
// attraverso questa (anche mentre se ne guarda un'altra).
function InstanceCard({ instance }: { instance: Instance | null }) {
  const id = instance?.id ?? null
  const status = instance?.status
  const reachable = !instance || (status?.status === 'ok' && !status.compatibility.startsWith('block'))
  const { data, isPending, isError } = useInstanceSnapshot(id, reachable)
  const current = activeInstanceId() === id
  const localName = useLocalName()
  const dash = data?.dashboard
  return (
    <Card className={cn('min-w-0', current && 'ring-2 ring-primary/50')}>
      <CardHeader className="flex flex-row items-center gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-muted">
          <ServerIcon className="size-4.5 text-muted-foreground" />
        </span>
        <div className="grid min-w-0 flex-1 gap-0.5">
          {/* truncate su un flex non tronca il testo: va sullo span del nome. */}
          <CardTitle className="flex min-w-0 items-center gap-2 text-base">
            <span className={cn('size-2 shrink-0 rounded-full', instanceDot(instance))} />
            <span className="truncate">{instance?.label ?? localName}</span>
          </CardTitle>
          <span className="text-xs text-muted-foreground">
            {data?.version ? t('instances.version', { version: data.version }) : status?.version ?? ''}
            {status && status.status === 'ok' && status.compatibility !== 'ok'
              ? ` · ${t(`instances.compat.${status.compatibility}`)}` : ''}
          </span>
        </div>
        <Button variant="outline" size="sm" disabled={current || !reachable} onClick={() => switchInstance(id)}>
          {t('instances.open')}
        </Button>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        {!reachable || isError ? (
          <p className="col-span-2 text-muted-foreground">
            {status && status.status !== 'ok' ? t(`instances.status.${status.status}`) : t('instances.unavailable')}
          </p>
        ) : isPending || !dash ? (
          <p className="col-span-2 text-muted-foreground">{t('instances.loading')}</p>
        ) : (
          <>
            <span className="text-muted-foreground">{t('instances.seeding')}</span>
            <span className="tabular-nums">
              {dash.total_media_size ? `${Math.round(dash.health_pct)}% · ${formatBytes(dash.total_media_size)}` : '—'}
            </span>
            <span className="text-muted-foreground">{t('instances.reviews')}</span>
            <span className="tabular-nums">{dash.pending_review}</span>
            <span className="text-muted-foreground">{t('instances.uploads')}</span>
            <span className="tabular-nums">{data.uploads.filter((u) => ACTIVE_UPLOADS.includes(u.status)).length}</span>
            <span className="text-muted-foreground">{t('instances.lastScan')}</span>
            <span>{dash.last_run?.finished_at ? relativeFromNow(dash.last_run.finished_at) : t('instances.never')}</span>
          </>
        )}
      </CardContent>
    </Card>
  )
}

export function InstancesPage() {
  const { data } = useInstances(true)
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-3xl text-sm text-muted-foreground">{t('instances.description')}</p>
        <Button variant="outline" size="sm" render={<Link to="/config?tab=instances" />}>
          {t('instances.manage')}
        </Button>
      </div>
      <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
        <InstanceCard instance={null} />
        {data?.instances.map((instance) => <InstanceCard key={instance.id} instance={instance} />)}
      </div>
    </div>
  )
}
