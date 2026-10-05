import { DndContext, type DragEndEvent, KeyboardSensor, PointerSensor, useSensor, useSensors } from '@dnd-kit/core'
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useQueryClient } from '@tanstack/react-query'
import { ChevronDownIcon, GripVerticalIcon, TriangleAlertIcon } from 'lucide-react'
import { useState } from 'react'

import type { Schemas } from '@/api/client'
import { useAdapterConfig, usePlugins, useSaveAdapterConfig } from '@/api/hooks/plugins'
import { useSetSetting } from '@/api/hooks/settings'
import { useImageHostStatus } from '@/api/hooks/uploads'
import {
  AdapterConfigFields,
  configPayload,
  initialConfigValues,
  missingRequired,
  type ConfigValues,
} from '@/components/AdapterConfigFields'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { autosaveFeedback } from '@/lib/autosave'
import { t } from '@/lib/i18n'
import { cn } from '@/lib/utils'

type Adapter = Schemas['AdapterResponse']

// Gli host tolti nella 0.8 (nazgarr/core/db.py migrate_image_hosts_to_plugins),
// solo per dirne il nome nell'avviso.
const REMOVED_LABELS: Record<string, string> = {
  ptpimg: 'PTPImg', imgbox: 'Imgbox', pixhost: 'Pixhost', onlyimage: 'OnlyImage', dalexni: 'Dalexni',
  utppm: 'utp.pm', seedpool_cdn: 'Seedpool CDN',
}

function HostRow({ adapter }: { adapter: Adapter }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: adapter.adapter_type })
  const { data } = useAdapterConfig(adapter.kind, adapter.adapter_type)
  const save = useSaveAdapterConfig(adapter.kind, adapter.adapter_type)
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [values, setValues] = useState<ConfigValues | null>(null)
  const missing = data ? missingRequired(adapter.config_fields, initialConfigValues(adapter.config_fields, data.values), data.secrets_set) : false
  const current = values ?? initialConfigValues(adapter.config_fields, data?.values)
  const status = missing ? 'missing' : 'ready'
  // L'avviso prima di un upload segue subito.
  const saved = () => queryClient.invalidateQueries({ queryKey: ['uploads', 'image-hosts'] })

  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={cn('rounded-md border bg-background', isDragging && 'opacity-50')}
    >
      <div className="flex items-center gap-2 px-3 py-2 text-sm">
        <button
          {...attributes}
          {...listeners}
          className="flex shrink-0 cursor-grab touch-none items-center justify-center text-muted-foreground active:cursor-grabbing pointer-coarse:-my-1.5 pointer-coarse:-ml-2 pointer-coarse:size-9"
          aria-label={t('uploadSettings.dragToReorder', { label: adapter.label })}
        >
          <GripVerticalIcon className="size-4" />
        </button>
        <button type="button" className="flex min-w-0 flex-1 items-center gap-2 text-left" onClick={() => setOpen(!open)}
                aria-expanded={open}>
          <span className="truncate font-medium">{adapter.label}</span>
          {!adapter.bundled && adapter.plugin && <Badge variant="outline" className="shrink-0">{t('uploadSettings.hostPlugin')}</Badge>}
          <span
            className={cn(
              'shrink-0 text-xs',
              status === 'ready' && 'text-emerald-600 dark:text-emerald-400',
              status === 'missing' && 'text-amber-600 dark:text-amber-400',
            )}
          >
            {t(`uploadSettings.hostStatus.${status}`)}
          </span>
          <ChevronDownIcon className={cn('ml-auto size-4 shrink-0 text-muted-foreground transition-transform', open && 'rotate-180')} />
        </button>
      </div>
      {open && data && (
        <div className="grid gap-3 border-t px-3 py-3">
          {adapter.description && (
            <a href={adapter.description.split(' ')[0]} target="_blank" rel="noreferrer"
               className="w-fit text-xs text-muted-foreground underline-offset-4 hover:underline">
              {adapter.description}
            </a>
          )}
          <AdapterConfigFields
            idPrefix={`image-host-${adapter.adapter_type}`}
            fields={adapter.config_fields}
            values={current}
            secretsSet={data.secrets_set}
            onChange={setValues}
          />
          <div className="flex justify-end">
            <Button
              size="sm"
              disabled={save.isPending || values === null || missingRequired(adapter.config_fields, current, data.secrets_set)}
              onClick={() => {
                const feedback = autosaveFeedback(adapter.label)
                save.mutate({ config: configPayload(adapter.config_fields, current) }, {
                  onSuccess: () => {
                    setValues(null)
                    feedback.onSuccess()
                  },
                  onError: feedback.onError,
                  onSettled: saved,
                })
              }}
            >
              {t('common.save')}
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

// Gli host rimossi con un aggiornamento che l'utente usava: finché non lo chiude.
function RemovedNotice({ hosts }: { hosts: string[] }) {
  const dismiss = useSetSetting('image_hosts_removed')
  const queryClient = useQueryClient()
  if (hosts.length === 0) return null
  return (
    <div className="flex gap-3 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
      <TriangleAlertIcon className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400" />
      <p className="min-w-0 flex-1">
        {t('uploadSettings.hostsRemoved', { hosts: hosts.map((key) => REMOVED_LABELS[key] ?? key).join(', ') })}
      </p>
      <Button size="xs" variant="ghost" className="shrink-0"
              onClick={() => dismiss.mutate('', { onSuccess: () => queryClient.invalidateQueries({ queryKey: ['uploads', 'image-hosts'] }) })}>
        {t('common.close')}
      </Button>
    </div>
  )
}

// Settings › Upload › Immagini: ogni host registrato, incluso o da un
// plugin, con il suo ordine, acceso/spento e la sua configurazione.
export function ImageHostsCard() {
  const { data: plugins } = usePlugins()
  const { data: status } = useImageHostStatus()
  const setPriority = useSetSetting('image_host_priority')
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<string[] | null>(null)
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )
  const hosts = (plugins?.adapters ?? []).filter((adapter) => adapter.kind === 'image_host')
  const byType = new Map(hosts.map((adapter) => [adapter.adapter_type, adapter]))
  // L'ordine in cui il backend prova gli host (image_host_priority, con
  // quelli nuovi in coda), non quello in cui l'API elenca gli adapter.
  const order = draft ?? status?.order ?? []

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event
    if (!over || active.id === over.id) return
    const next = arrayMove(order, order.indexOf(String(active.id)), order.indexOf(String(over.id)))
    setDraft(next)
    const feedback = autosaveFeedback(t('uploadSettings.priorityOrderSaved'))
    setPriority.mutate(next.join(','), {
      onSuccess: () => {
        feedback.onSuccess()
        queryClient.invalidateQueries({ queryKey: ['uploads', 'image-hosts'] }).then(() => setDraft(null))
      },
      onError: (error) => {
        feedback.onError(error)
        setDraft(null)
      },
    })
  }

  return (
    <Card data-tour="upload.image-hosts">
      <CardHeader>
        <CardTitle>{t('uploadSettings.imageHostsTitle')}</CardTitle>
        <CardDescription>{t('uploadSettings.imageHostsDescription')}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        <RemovedNotice hosts={status?.removed ?? []} />
        <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
          <SortableContext items={order} strategy={verticalListSortingStrategy}>
            <div className="grid gap-1.5">
              {order.map((key) => {
                const adapter = byType.get(key)
                return adapter ? <HostRow key={key} adapter={adapter} /> : null
              })}
            </div>
          </SortableContext>
        </DndContext>
        <p className="text-xs text-muted-foreground">{t('uploadSettings.morePlugins')}</p>
      </CardContent>
    </Card>
  )
}
