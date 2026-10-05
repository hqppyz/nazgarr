import { CheckIcon, ChevronsUpDownIcon, LayoutGridIcon, SettingsIcon } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { useInstances, type Instance } from '@/api/hooks/instances'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
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

export function useLocalName(): string {
  const { data } = useInstances(true)
  return data?.local_name || t('instances.thisInstance')
}

function Row({ dot, label, detail, active, onSelect }: {
  dot: string
  label: string
  detail?: string
  active: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn('flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-muted', active && 'bg-muted/60')}
    >
      <span className={cn('size-2 shrink-0 rounded-full', dot)} />
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {detail && <span className="shrink-0 text-xs text-muted-foreground">{detail}</span>}
      <CheckIcon className={cn('size-4 shrink-0', !active && 'invisible')} />
    </button>
  )
}

// Sotto il nome dell'app, solo se ci sono altre istanze (Configurazione ›
// Istanze): l'istanza che si sta guardando, e un menu per cambiarla.
export function InstanceSwitcher() {
  const { data } = useInstances(true)
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const remotes = data?.instances ?? []
  if (remotes.length === 0) return null
  const current = activeInstanceId()
  const active = remotes.find((i) => i.id === current) ?? null
  const localName = data?.local_name || t('instances.thisInstance')
  const choose = (id: number | null) => {
    setOpen(false)
    if (id !== current) switchInstance(id)
  }
  const go = (to: string) => {
    setOpen(false)
    navigate(to)
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        data-tour="instances.switcher"
        className="-mx-1 flex min-w-0 items-center gap-1.5 rounded px-1 py-1 text-xs text-muted-foreground hover:text-foreground pointer-coarse:py-2"
        aria-label={t('instances.title')}
      >
        <span className={cn('size-1.5 shrink-0 rounded-full', instanceDot(active))} />
        <span className="truncate">{active ? active.label : localName}</span>
        <ChevronsUpDownIcon className="size-3 shrink-0" />
      </PopoverTrigger>
      <PopoverContent align="start" className="w-64 gap-1 p-1.5">
        <Row dot={instanceDot(null)} label={localName} detail={data?.local_version} active={current === null}
             onSelect={() => choose(null)} />
        {remotes.map((instance) => (
          <Row key={instance.id} dot={instanceDot(instance)} label={instance.label}
               detail={instance.status?.version ?? undefined} active={current === instance.id}
               onSelect={() => choose(instance.id)} />
        ))}
        <div className="my-1 h-px bg-border" />
        <button type="button" onClick={() => go('/instances')}
                className="flex items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted">
          <LayoutGridIcon className="size-4" />
          {t('instances.overview')}
        </button>
        <button type="button" onClick={() => go('/config?tab=instances')}
                className="flex items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted">
          <SettingsIcon className="size-4" />
          {t('instances.manage')}
        </button>
      </PopoverContent>
    </Popover>
  )
}
