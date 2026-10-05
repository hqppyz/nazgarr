import { HistoryIcon, PencilIcon, RotateCwIcon, SendIcon, TrashIcon } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { toast } from 'sonner'

import type { Schemas } from '@/api/client'
import {
  useCreateWebhook,
  useRotateWebhookSecret,
  useTestWebhook,
  useUpdateWebhook,
  useWebhookEvents,
  type Webhook,
} from '@/api/hooks/webhooks'
import { Badge } from '@/components/ui/badge'
import { InfoPopover } from '@/components/InfoPopover'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
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
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { autosaveFeedback } from '@/lib/autosave'
import { t } from '@/lib/i18n'
import { relativeFromNow } from '@/lib/time'
import { cn } from '@/lib/utils'
import { NotificationLogo } from '@/pages/config/ServiceIcons'

// I pezzi condivisi da webhook e servizi di notifica (NotificationsSection):
// l'esito di una consegna, la scelta degli eventi, lo storico, la card.

const ALL = '*'
const STATUS_STYLE: Record<string, string> = {
  delivered: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
  failed: 'border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-300',
  pending: 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300',
}

export function StatusBadge({ status }: { status: string }) {
  return (
    <Badge variant="outline" className={cn(STATUS_STYLE[status])}>
      {t(`webhooks.status.${status}`)}
    </Badge>
  )
}

// Tutti gli eventi, o solo alcuni (almeno uno).
export function EventsPicker({ idPrefix, events, onChange }: {
  idPrefix: string
  events: string[]
  onChange: (events: string[]) => void
}) {
  const { data: catalog } = useWebhookEvents()
  const all = events.includes(ALL)
  const toggle = (event: string) =>
    onChange(events.includes(event) ? events.filter((e) => e !== event) : [...events.filter((e) => e !== ALL), event])
  return (
    <div className="grid gap-2">
      <Label>{t('webhooks.events')}</Label>
      <div className="flex items-center gap-2">
        <Switch id={`${idPrefix}-all`} checked={all} onCheckedChange={(checked) => onChange(checked ? [ALL] : [])} />
        <Label htmlFor={`${idPrefix}-all`} className="font-normal">{t('webhooks.allEvents')}</Label>
      </div>
      {!all && (
        <div className="grid gap-1.5">
          {catalog?.map((event) => (
            <label key={event.name} className="flex cursor-pointer items-start gap-2 text-sm">
              <input type="checkbox" className="mt-1" checked={events.includes(event.name)} onChange={() => toggle(event.name)} />
              <span className="grid">
                <span className="font-mono text-xs">{event.name}</span>
                <span className="text-xs text-muted-foreground">{event.description}</span>
              </span>
            </label>
          ))}
        </div>
      )}
    </div>
  )
}

export function EventBadges({ events }: { events: string[] }) {
  return (
    <div className="flex flex-wrap gap-1">
      {events.map((event) => (
        <Badge key={event} variant="secondary" className="font-mono text-[11px]">
          {event === ALL ? t('webhooks.allEvents') : event}
        </Badge>
      ))}
    </div>
  )
}

// Crea o modifica un webhook: nome, URL ed eventi.
export function WebhookDialog({ webhook, onClose, onCreated }: {
  webhook: Webhook | null
  onClose: () => void
  onCreated: (secret: string) => void
}) {
  const create = useCreateWebhook()
  const update = useUpdateWebhook()
  const [name, setName] = useState(webhook?.name ?? t('notifications.typeWebhook'))
  const [url, setUrl] = useState(webhook?.url ?? '')
  const [events, setEvents] = useState<string[]>(webhook?.events ?? [ALL])

  function submit() {
    const body = { name, url, events }
    const onError = (error: Error) => toast.error(t('common.saveFailed', { message: error.message }))
    if (webhook) update.mutate({ id: webhook.id, body }, { onSuccess: onClose, onError })
    else
      create.mutate(body, {
        onSuccess: (created) => {
          onClose()
          onCreated(created.secret)
        },
        onError,
      })
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <NotificationLogo type="webhook" />
            {webhook ? t('notifications.editTitle', { name: webhook.name }) : t('webhooks.addTitle')}
          </DialogTitle>
          <DialogDescription>{t('webhooks.dialogHelp')}</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor="webhook-name">{t('webhooks.name')}</Label>
            <Input id="webhook-name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="webhook-url">{t('webhooks.url')}</Label>
            <Input id="webhook-url" value={url} placeholder="https://example.com/hooks/nazgarr" onChange={(e) => setUrl(e.target.value)} />
          </div>
          <EventsPicker idPrefix="webhook" events={events} onChange={setEvents} />
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>{t('common.cancel')}</Button>
          <Button disabled={!name.trim() || !url.trim() || events.length === 0 || create.isPending || update.isPending} onClick={submit}>
            {webhook ? t('common.save') : t('webhooks.create')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// L'esito di una consegna in una riga: codice HTTP, errore, prossimo tentativo.
function deliveryResult(d: Schemas['DeliveryResponse']) {
  return [
    d.last_status_code ? `HTTP ${d.last_status_code}` : '',
    d.last_error ?? '',
    d.status === 'pending' && d.next_attempt_at
      ? `· ${t('webhooks.nextAttempt', { when: relativeFromNow(d.next_attempt_at) })}`
      : '',
  ].filter(Boolean).join(' ')
}

// Le ultime consegne di un webhook o di un servizio di notifica.
export function DeliveriesDialog({ name, deliveries, onClose }: {
  name: string | null
  deliveries: Schemas['DeliveryResponse'][] | undefined
  onClose: () => void
}) {
  return (
    <Dialog open={name !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{t('webhooks.deliveriesTitle', { name: name ?? '' })}</DialogTitle>
          <DialogDescription>{t('webhooks.deliveriesHelp')}</DialogDescription>
        </DialogHeader>
        {(deliveries ?? []).length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('webhooks.noDeliveries')}</p>
        ) : (
          <div className="max-h-[60dvh] overflow-auto">
            {/* Da telefono cinque colonne lasciano all'esito pochi pixel e
                l'errore stava solo nel title: righe impilate, errore intero. */}
            <ul className="divide-y sm:hidden">
              {deliveries!.map((d) => (
                <li key={d.id} className="grid gap-1 py-2 text-xs">
                  <div className="flex items-center gap-2">
                    <span className="min-w-0 flex-1 truncate font-mono">{d.event}</span>
                    <StatusBadge status={d.status} />
                  </div>
                  <p className="break-words text-muted-foreground">{deliveryResult(d)}</p>
                  <p className="text-muted-foreground">
                    {t('webhooks.attempts')}: <span className="tabular-nums">{d.attempts}</span> ·{' '}
                    {relativeFromNow(d.delivered_at ?? d.created_at)}
                  </p>
                </li>
              ))}
            </ul>
            <div className="hidden sm:block">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('webhooks.event')}</TableHead>
                  <TableHead>{t('webhooks.statusColumn')}</TableHead>
                  <TableHead>{t('webhooks.attempts')}</TableHead>
                  <TableHead className="w-full">{t('webhooks.result')}</TableHead>
                  <TableHead>{t('webhooks.when')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {deliveries!.map((d) => (
                  <TableRow key={d.id}>
                    <TableCell className="font-mono text-xs">{d.event}</TableCell>
                    <TableCell><StatusBadge status={d.status} /></TableCell>
                    <TableCell className="tabular-nums">{d.attempts}</TableCell>
                    <TableCell className="max-w-0 text-xs text-muted-foreground">
                      <InfoPopover content={d.last_error} className="block truncate">
                        {deliveryResult(d)}
                      </InfoPopover>
                    </TableCell>
                    <TableCell className="text-xs whitespace-nowrap text-muted-foreground">
                      {relativeFromNow(d.delivered_at ?? d.created_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

// La card di un destinatario, webhook o servizio: icona, nome con l'esito
// dell'ultima consegna, tipo, interruttore; sotto il riepilogo, gli eventi
// e le azioni (la prova a sinistra).
export function DestinationCard({
  logo, name, subtitle, lastStatus, lastError, enabled, onToggle, children, events, onTest, testing, testDisabled,
  onDeliveries, onEdit, onDelete, extraActions,
}: {
  logo: ReactNode
  name: string
  subtitle: ReactNode
  lastStatus: string | null | undefined
  lastError?: string | null
  enabled: boolean
  onToggle: (enabled: boolean) => void
  children?: ReactNode
  events: string[]
  onTest: () => void
  testing: boolean
  testDisabled?: boolean
  onDeliveries: () => void
  onEdit: () => void
  onDelete: () => void
  extraActions?: ReactNode
}) {
  return (
    <Card className={cn('min-w-0', !enabled && 'opacity-70')}>
      <CardHeader className="flex flex-row items-center gap-3">
        {logo}
        <div className="grid min-w-0 flex-1 gap-0.5">
          <CardTitle className="flex items-center gap-2 truncate text-base">
            <span className="truncate">{name}</span>
            {lastStatus && (
              <InfoPopover content={lastStatus === 'failed' ? lastError : null}>
                <StatusBadge status={lastStatus} />
              </InfoPopover>
            )}
          </CardTitle>
          <span className="truncate text-xs text-muted-foreground">{subtitle}</span>
        </div>
        <Switch checked={enabled} title={t('webhooks.enabled')} onCheckedChange={onToggle} />
      </CardHeader>
      <CardContent className="grid min-w-0 gap-3 text-sm">
        {children}
        <EventBadges events={events} />
        <div className="flex items-center gap-1 border-t pt-3">
          <Button variant="outline" size="sm" disabled={testing || testDisabled} onClick={onTest}>
            <SendIcon className="size-4" />
            {t('webhooks.test')}
          </Button>
          <span className="flex-1" />
          <Button variant="ghost" size="icon-sm" title={t('webhooks.deliveries')} onClick={onDeliveries}>
            <HistoryIcon className="size-4" />
          </Button>
          {extraActions}
          <Button variant="ghost" size="icon-sm" title={t('common.edit')} onClick={onEdit}>
            <PencilIcon className="size-4" />
          </Button>
          <Button variant="ghost" size="icon-sm" title={t('common.delete')} onClick={onDelete}>
            <TrashIcon className="size-4" />
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

export function WebhookCard({ webhook, onEdit, onDelete, onDeliveries, onSecret }: {
  webhook: Webhook
  onEdit: () => void
  onDelete: () => void
  onDeliveries: () => void
  onSecret: (secret: string) => void
}) {
  const update = useUpdateWebhook()
  const rotate = useRotateWebhookSecret()
  const test = useTestWebhook()
  return (
    <DestinationCard
      logo={<NotificationLogo type="webhook" />}
      name={webhook.name}
      subtitle={t('notifications.typeWebhook')}
      lastStatus={webhook.last_status}
      enabled={webhook.enabled}
      onToggle={(enabled) => update.mutate({ id: webhook.id, body: { enabled } }, autosaveFeedback(webhook.name))}
      events={webhook.events}
      testing={test.isPending}
      onTest={() =>
        test.mutate(webhook.id, {
          onSuccess: (d) =>
            d.status === 'delivered'
              ? toast.success(t('webhooks.testDelivered'))
              : toast.error(t('webhooks.testFailed', { error: d.last_error ?? `HTTP ${d.last_status_code}` })),
        })
      }
      onDeliveries={onDeliveries}
      onEdit={onEdit}
      onDelete={onDelete}
      extraActions={
        <Button
          variant="ghost"
          size="icon-sm"
          title={t('webhooks.rotate')}
          onClick={() => rotate.mutate(webhook.id, { onSuccess: (r) => onSecret(r.secret) })}
        >
          <RotateCwIcon className="size-4" />
        </Button>
      }
    >
      {/* Al tocco il title non si vede: l'URL va a capo invece di troncarsi. */}
      <span className="truncate font-mono text-xs text-muted-foreground pointer-coarse:break-all pointer-coarse:whitespace-normal" title={webhook.url}>
        {webhook.url}
      </span>
    </DestinationCard>
  )
}
