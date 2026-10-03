import { LayoutGridIcon, SettingsIcon } from 'lucide-react'
import { Link } from 'react-router-dom'

import { useInstances, type Instance } from '@/api/hooks/instances'
import { Select, SelectContent, SelectItem, SelectSeparator, SelectTrigger, SelectValue } from '@/components/ui/select'
import { t } from '@/lib/i18n'
import { activeInstanceId, switchInstance } from '@/lib/instance'
import { cn } from '@/lib/utils'

// Il pallino di stato di un'istanza: verde connessa e compatibile, giallo
// connessa con un avviso, rosso non raggiungibile o bloccata.
export function instanceDot(instance: Instance | null): string {
  const status = instance?.status
  if (!instance) return 'bg-emerald-500'
  if (!status) return 'bg-muted-foreground'
  if (status.status !== 'ok' || status.compatibility.startsWith('block')) return 'bg-red-500'
  if (status.compatibility !== 'ok') return 'bg-amber-500'
  return 'bg-emerald-500'
}

// In cima alla sidebar, solo se ci sono altre istanze (Configurazione › Istanze).
export function InstanceSwitcher() {
  const { data } = useInstances(true)
  const remotes = data?.instances ?? []
  if (remotes.length === 0) return null
  const current = activeInstanceId()
  const active = remotes.find((i) => i.id === current) ?? null
  return (
    <div className="px-2 pb-2 group-data-[collapsible=icon]:hidden">
      <Select
        value={String(current ?? 'local')}
        onValueChange={(value) => {
          if (value == null) return
          const next = value === 'local' ? null : Number(value)
          if (next !== current) switchInstance(next)
        }}
      >
        <SelectTrigger size="sm" className="w-full" aria-label={t('instances.title')}>
          <SelectValue>
            {() => (
              <span className="flex min-w-0 items-center gap-2">
                <span className={cn('size-2 shrink-0 rounded-full', instanceDot(active))} />
                <span className="truncate">{active ? active.label : t('instances.thisInstance')}</span>
              </span>
            )}
          </SelectValue>
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="local">
            <span className={cn('size-2 rounded-full', instanceDot(null))} />
            {t('instances.thisInstance')}
          </SelectItem>
          {remotes.map((instance) => (
            <SelectItem key={instance.id} value={String(instance.id)}>
              <span className={cn('size-2 rounded-full', instanceDot(instance))} />
              {instance.label}
            </SelectItem>
          ))}
          <SelectSeparator />
          <Link to="/instances" className="flex items-center gap-2 px-2 py-1.5 text-sm hover:bg-muted">
            <LayoutGridIcon className="size-4" />
            {t('instances.overview')}
          </Link>
          <Link to="/config?tab=instances" className="flex items-center gap-2 px-2 py-1.5 text-sm hover:bg-muted">
            <SettingsIcon className="size-4" />
            {t('instances.manage')}
          </Link>
        </SelectContent>
      </Select>
    </div>
  )
}

