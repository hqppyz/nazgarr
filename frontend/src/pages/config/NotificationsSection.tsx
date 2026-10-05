import { PlusIcon, SendIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import type { Schemas } from '@/api/client'
import {
  useCreateNotificationService,
  useDeleteNotificationService,
  useNotificationDeliveries,
  useNotificationServices,
  useTestNotificationService,
  useTestUnsavedNotification,
  useUpdateNotificationService,
  type NotificationService,
} from '@/api/hooks/notifications'
import { usePlugins } from '@/api/hooks/plugins'
import { useDeleteWebhook, useWebhookDeliveries, useWebhooks, type Webhook } from '@/api/hooks/webhooks'
import {
  AdapterConfigFields,
  configPayload,
  initialConfigValues,
  missingRequired,
  type ConfigValues,
} from '@/components/AdapterConfigFields'
import { OneTimeSecretDialog } from '@/components/OneTimeSecretDialog'
import { SettingsHeader } from '@/components/SettingsHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { autosaveFeedback } from '@/lib/autosave'
import { t } from '@/lib/i18n'
import { NotificationLogo } from '@/pages/config/ServiceIcons'
import { DeliveriesDialog, DestinationCard, EventsPicker, WebhookCard, WebhookDialog } from '@/pages/config/WebhookParts'

type Adapter = Schemas['AdapterResponse']
const ALL = '*'

// Il nome proposto per un servizio nuovo: il tipo, poi "Tipo 2", "Tipo 3"...
function suggestedName(label: string, taken: string[]) {
  if (!taken.includes(label)) return label
  let n = 2
  while (taken.includes(`${label} ${n}`)) n += 1
  return `${label} ${n}`
}

// Crea o modifica un servizio: nome, i campi del suo tipo, gli eventi; la
// prova parte con i valori del form, prima di salvare.
function ServiceDialog({ adapter, service, defaultName, onClose }: {
  adapter: Adapter
  service: NotificationService | null
  defaultName: string
  onClose: () => void
}) {
  const create = useCreateNotificationService()
  const update = useUpdateNotificationService()
  const test = useTestUnsavedNotification()
  const fields = adapter.config_fields
  const [name, setName] = useState(service?.name ?? defaultName)
  const [values, setValues] = useState<ConfigValues>(() => initialConfigValues(fields, service?.values))
  const [events, setEvents] = useState<string[]>(service?.events ?? [ALL])
  const secretsSet = service?.secrets_set ?? []
  const incomplete = missingRequired(fields, values, secretsSet)

  function submit() {
    const body = { name, config: configPayload(fields, values), events }
    const onError = (error: Error) => toast.error(t('common.saveFailed', { message: error.message }))
    if (service) update.mutate({ id: service.id, body }, { onSuccess: onClose, onError })
    else create.mutate({ ...body, adapter_type: adapter.adapter_type }, { onSuccess: onClose, onError })
  }

  function sendTest() {
    test.mutate(
      { adapter_type: adapter.adapter_type, config: configPayload(fields, values), service_id: service?.id ?? null },
      {
        onSuccess: (r) =>
          r.status === 'delivered'
            ? toast.success(t('webhooks.testDelivered'))
            : toast.error(t('webhooks.testFailed', { error: r.error ?? '' })),
        onError: (error) => toast.error(t('webhooks.testFailed', { error: error.message })),
      },
    )
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <NotificationLogo type={adapter.adapter_type} icon={adapter.icon} />
            {service ? t('notifications.editTitle', { name: service.name }) : t('notifications.addTitle', { type: adapter.label })}
          </DialogTitle>
          <DialogDescription>
            {adapter.description ?? t('notifications.dialogHelp')}
            {adapter.plugin ? ` (${adapter.plugin})` : ''}
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor="notification-name">{t('webhooks.name')}</Label>
            <Input id="notification-name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <AdapterConfigFields
            idPrefix={`notification-${adapter.adapter_type}`}
            fields={fields}
            values={values}
            secretsSet={secretsSet}
            onChange={setValues}
          />
          <EventsPicker idPrefix="notification" events={events} onChange={setEvents} />
        </div>
        <DialogFooter className="sm:justify-between">
          <Button variant="outline" disabled={incomplete || test.isPending} onClick={sendTest}>
            <SendIcon className="size-4" />
            {t('webhooks.test')}
          </Button>
          <div className="flex flex-col-reverse gap-2 sm:flex-row">
            <Button variant="ghost" onClick={onClose}>{t('common.cancel')}</Button>
            <Button
              disabled={!name.trim() || incomplete || events.length === 0 || create.isPending || update.isPending}
              onClick={submit}
            >
              {service ? t('common.save') : t('webhooks.create')}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// Il riepilogo della configurazione: i campi non segreti con un valore, e i
// segreti solo come "impostato".
function ConfigRecap({ adapter, service }: { adapter: Adapter | undefined; service: NotificationService }) {
  const rows = (adapter?.config_fields ?? []).flatMap((field) => {
    if (field.type === 'secret')
      return service.secrets_set.includes(field.key) ? [[field.label, t('notifications.secretSet')] as const] : []
    const value = service.values[field.key]
    if (value === null || value === undefined || value === '') return []
    return [[field.label, typeof value === 'boolean' ? (value ? '✓' : '✗') : String(value)] as const]
  })
  if (rows.length === 0) return null
  return (
    <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-xs">
      {rows.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-muted-foreground">{label}</dt>
          <dd className="truncate font-mono" title={value}>{value}</dd>
        </div>
      ))}
    </dl>
  )
}

function ServiceCard({ service, adapter, onEdit, onDelete, onDeliveries }: {
  service: NotificationService
  adapter: Adapter | undefined
  onEdit: () => void
  onDelete: () => void
  onDeliveries: () => void
}) {
  const update = useUpdateNotificationService()
  const test = useTestNotificationService()
  const type = adapter ? adapter.label + (adapter.plugin ? ` · ${adapter.plugin}` : '') : service.adapter_type
  return (
    <DestinationCard
      logo={<NotificationLogo type={service.adapter_type} icon={adapter?.icon} />}
      name={service.name}
      subtitle={
        service.available ? type : (
          <Badge variant="outline" className="border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300">
            {t('notifications.unavailable', { type: service.adapter_type })}
          </Badge>
        )
      }
      lastStatus={service.last_status}
      lastError={service.last_error}
      enabled={service.enabled}
      onToggle={(enabled) => update.mutate({ id: service.id, body: { enabled } }, autosaveFeedback(service.name))}
      events={service.events}
      testing={test.isPending}
      testDisabled={!service.available}
      onTest={() =>
        test.mutate(service.id, {
          onSuccess: (r) =>
            r.status === 'delivered'
              ? toast.success(t('webhooks.testDelivered'))
              : toast.error(t('webhooks.testFailed', { error: r.error ?? '' })),
        })
      }
      onDeliveries={onDeliveries}
      onEdit={onEdit}
      onDelete={onDelete}
    >
      <ConfigRecap adapter={adapter} service={service} />
    </DestinationCard>
  )
}

// Il pulsante "Aggiungi": si sceglie il tipo, poi si apre la modale.
function AddMenu({ adapters, onPick }: { adapters: Adapter[]; onPick: (type: Adapter | 'webhook') => void }) {
  const [open, setOpen] = useState(false)
  const pick = (type: Adapter | 'webhook') => {
    setOpen(false)
    onPick(type)
  }
  const item = 'flex items-center gap-3 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted'
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger render={<Button data-tour="notifications.add"><PlusIcon className="size-4" />{t('notifications.add')}</Button>} />
      <PopoverContent align="end" className="w-72 gap-0.5 p-1.5">
        {adapters.map((adapter) => (
          <button key={adapter.adapter_type} type="button" className={item} onClick={() => pick(adapter)}>
            <NotificationLogo type={adapter.adapter_type} icon={adapter.icon} />
            <span className="grid min-w-0">
              <span className="truncate">{adapter.label}</span>
              {adapter.plugin && <span className="truncate text-xs text-muted-foreground">{adapter.plugin}</span>}
            </span>
          </button>
        ))}
        <div className="my-1 h-px bg-border" />
        <button type="button" className={item} onClick={() => pick('webhook')}>
          <NotificationLogo type="webhook" />
          <span className="grid min-w-0">
            <span>{t('notifications.typeWebhook')}</span>
            <span className="text-xs text-muted-foreground">{t('notifications.typeWebhookHelp')}</span>
          </span>
        </button>
      </PopoverContent>
    </Popover>
  )
}

type Editing =
  | { kind: 'service'; adapter: Adapter; service: NotificationService | null }
  | { kind: 'webhook'; webhook: Webhook | null }
type Target = { kind: 'service'; item: NotificationService } | { kind: 'webhook'; item: Webhook }

// Dove vanno gli eventi di Nazgarr: servizi di notifica (Discord, Telegram,
// quelli dei plugin), quanti se ne vuole per tipo, e webhook firmati.
export function NotificationsSection() {
  const { data: plugins } = usePlugins()
  const { data: services, isPending } = useNotificationServices()
  const { data: webhooks } = useWebhooks()
  const removeService = useDeleteNotificationService()
  const removeWebhook = useDeleteWebhook()
  const [editing, setEditing] = useState<Editing | null>(null)
  const [deleting, setDeleting] = useState<Target | null>(null)
  const [history, setHistory] = useState<Target | null>(null)
  const [secret, setSecret] = useState<string | null>(null)
  const serviceDeliveries = useNotificationDeliveries(history?.kind === 'service' ? history.item.id : null)
  const webhookDeliveries = useWebhookDeliveries(history?.kind === 'webhook' ? history.item.id : null)

  const adapters = plugins?.adapters.filter((a) => a.kind === 'notification') ?? []
  const adapterOf = (type: string) => adapters.find((a) => a.adapter_type === type)
  const names = [...(services ?? []).map((s) => s.name), ...(webhooks ?? []).map((w) => w.name)]
  const empty = !isPending && (services ?? []).length === 0 && (webhooks ?? []).length === 0

  function confirmDelete() {
    if (!deleting) return
    const done = { onSuccess: () => setDeleting(null) }
    if (deleting.kind === 'service') removeService.mutate(deleting.item.id, done)
    else removeWebhook.mutate(deleting.item.id, done)
  }

  return (
    <div className="grid content-start gap-4">
      <SettingsHeader
        title={t('config.tabNotifications')}
        description={t('config.descNotifications')}
        action={
          <AddMenu
            adapters={adapters}
            onPick={(type) =>
              setEditing(type === 'webhook' ? { kind: 'webhook', webhook: null } : { kind: 'service', adapter: type, service: null })
            }
          />
        }
      />
      {isPending && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}
      {empty && (
        <Card>
          <CardContent className="py-6 text-center text-sm text-muted-foreground">{t('notifications.none')}</CardContent>
        </Card>
      )}
      <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
        {services?.map((service) => {
          const adapter = adapterOf(service.adapter_type)
          return (
            <ServiceCard
              key={`s${service.id}`}
              service={service}
              adapter={adapter}
              onEdit={() => adapter && setEditing({ kind: 'service', adapter, service })}
              onDelete={() => setDeleting({ kind: 'service', item: service })}
              onDeliveries={() => setHistory({ kind: 'service', item: service })}
            />
          )
        })}
        {webhooks?.map((webhook) => (
          <WebhookCard
            key={`w${webhook.id}`}
            webhook={webhook}
            onEdit={() => setEditing({ kind: 'webhook', webhook })}
            onDelete={() => setDeleting({ kind: 'webhook', item: webhook })}
            onDeliveries={() => setHistory({ kind: 'webhook', item: webhook })}
            onSecret={setSecret}
          />
        ))}
      </div>

      {editing?.kind === 'service' && (
        <ServiceDialog
          key={editing.service?.id ?? `new-${editing.adapter.adapter_type}`}
          adapter={editing.adapter}
          service={editing.service}
          defaultName={suggestedName(editing.adapter.label, names)}
          onClose={() => setEditing(null)}
        />
      )}
      {editing?.kind === 'webhook' && (
        <WebhookDialog
          key={editing.webhook?.id ?? 'new'}
          webhook={editing.webhook}
          onClose={() => setEditing(null)}
          onCreated={setSecret}
        />
      )}
      <DeliveriesDialog
        name={history?.item.name ?? null}
        deliveries={history?.kind === 'service' ? serviceDeliveries.data : webhookDeliveries.data}
        onClose={() => setHistory(null)}
      />
      <OneTimeSecretDialog
        secret={secret}
        title={t('webhooks.secretTitle')}
        description={t('webhooks.secretDescription')}
        onClose={() => setSecret(null)}
      >
        <p className="text-xs text-muted-foreground">{t('webhooks.signatureHelp')}</p>
      </OneTimeSecretDialog>
      <Dialog open={deleting !== null} onOpenChange={(o) => !o && setDeleting(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('webhooks.deleteTitle', { name: deleting?.item.name ?? '' })}</DialogTitle>
            <DialogDescription>{t('webhooks.deleteDescription')}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDeleting(null)}>{t('common.cancel')}</Button>
            <Button className="bg-destructive text-white hover:bg-destructive/90" onClick={confirmDelete}>
              {t('common.delete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
