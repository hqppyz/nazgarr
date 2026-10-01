import { HistoryIcon, PencilIcon, PlusIcon, RotateCwIcon, SendIcon, TrashIcon, WebhookIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import {
  useCreateWebhook,
  useDeleteWebhook,
  useRotateWebhookSecret,
  useTestWebhook,
  useUpdateWebhook,
  useWebhookDeliveries,
  useWebhookEvents,
  useWebhooks,
  type Webhook,
} from '@/api/hooks/webhooks'
import { OneTimeSecretDialog } from '@/components/OneTimeSecretDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
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

const ALL = '*'
const STATUS_STYLE: Record<string, string> = {
  delivered: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
  failed: 'border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-300',
  pending: 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300',
}

function StatusBadge({ status }: { status: string }) {
  return (
    <Badge variant="outline" className={cn(STATUS_STYLE[status])}>
      {t(`webhooks.status.${status}`)}
    </Badge>
  )
}

// Crea o modifica: nome, URL ed eventi (tutti, o solo alcuni).
function WebhookDialog({ webhook, open, onClose, onCreated }: {
  webhook: Webhook | null
  open: boolean
  onClose: () => void
  onCreated: (secret: string) => void
}) {
  const { data: catalog } = useWebhookEvents()
  const create = useCreateWebhook()
  const update = useUpdateWebhook()
  const [name, setName] = useState(webhook?.name ?? '')
  const [url, setUrl] = useState(webhook?.url ?? '')
  const [events, setEvents] = useState<string[]>(webhook?.events ?? [ALL])
  const all = events.includes(ALL)
  const toggle = (event: string) =>
    setEvents((prev) => (prev.includes(event) ? prev.filter((e) => e !== event) : [...prev.filter((e) => e !== ALL), event]))

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
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{webhook ? t('webhooks.editTitle') : t('webhooks.addTitle')}</DialogTitle>
          <DialogDescription>{t('webhooks.dialogHelp')}</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor="webhook-name">{t('webhooks.name')}</Label>
            <Input id="webhook-name" value={name} placeholder="discord" onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="webhook-url">{t('webhooks.url')}</Label>
            <Input id="webhook-url" value={url} placeholder="https://example.com/hooks/nazgarr" onChange={(e) => setUrl(e.target.value)} />
          </div>
          <div className="grid gap-2">
            <Label>{t('webhooks.events')}</Label>
            <div className="flex items-center gap-2">
              <Switch id="webhook-all" checked={all} onCheckedChange={(checked) => setEvents(checked ? [ALL] : [])} />
              <Label htmlFor="webhook-all" className="font-normal">{t('webhooks.allEvents')}</Label>
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

function DeliveriesDialog({ webhook, onClose }: { webhook: Webhook | null; onClose: () => void }) {
  const { data } = useWebhookDeliveries(webhook?.id ?? null)
  return (
    <Dialog open={webhook !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{t('webhooks.deliveriesTitle', { name: webhook?.name ?? '' })}</DialogTitle>
          <DialogDescription>{t('webhooks.deliveriesHelp')}</DialogDescription>
        </DialogHeader>
        {(data ?? []).length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('webhooks.noDeliveries')}</p>
        ) : (
          <div className="max-h-[60vh] overflow-auto">
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
                {data!.map((d) => (
                  <TableRow key={d.id}>
                    <TableCell className="font-mono text-xs">{d.event}</TableCell>
                    <TableCell><StatusBadge status={d.status} /></TableCell>
                    <TableCell className="tabular-nums">{d.attempts}</TableCell>
                    <TableCell className="max-w-0 text-xs text-muted-foreground">
                      <span className="block truncate" title={d.last_error ?? undefined}>
                        {d.last_status_code ? `HTTP ${d.last_status_code}` : ''}
                        {d.last_error ? ` ${d.last_error}` : ''}
                        {d.status === 'pending' && d.next_attempt_at
                          ? ` · ${t('webhooks.nextAttempt', { when: relativeFromNow(d.next_attempt_at) })}`
                          : ''}
                      </span>
                    </TableCell>
                    <TableCell className="text-xs whitespace-nowrap text-muted-foreground">
                      {relativeFromNow(d.delivered_at ?? d.created_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

// Webhook firmati con HMAC per gli eventi di Nazgarr (app/webhooks.py).
export function WebhooksSection() {
  const { data: webhooks } = useWebhooks()
  const update = useUpdateWebhook()
  const remove = useDeleteWebhook()
  const rotate = useRotateWebhookSecret()
  const test = useTestWebhook()
  const [editing, setEditing] = useState<Webhook | null | 'new'>(null)
  const [deliveries, setDeliveries] = useState<Webhook | null>(null)
  const [secret, setSecret] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<Webhook | null>(null)

  return (
    <>
      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-3">
          <div className="grid gap-1">
            <CardTitle>{t('webhooks.title')}</CardTitle>
            <CardDescription>{t('webhooks.description')}</CardDescription>
          </div>
          <Button onClick={() => setEditing('new')}>
            <PlusIcon className="size-4" />
            {t('webhooks.add')}
          </Button>
        </CardHeader>
        <CardContent className="grid gap-2">
          {(webhooks ?? []).length === 0 && <p className="text-sm text-muted-foreground">{t('webhooks.none')}</p>}
          {webhooks?.map((webhook) => (
            <div key={webhook.id} className={cn('grid gap-2 rounded-md border p-3', !webhook.enabled && 'opacity-60')}>
              <div className="flex flex-wrap items-center gap-2">
                <WebhookIcon className="size-4 text-muted-foreground" />
                <span className="font-medium">{webhook.name}</span>
                {webhook.last_status && <StatusBadge status={webhook.last_status} />}
                <Switch
                  className="ml-auto"
                  checked={webhook.enabled}
                  title={t('webhooks.enabled')}
                  onCheckedChange={(enabled) =>
                    update.mutate({ id: webhook.id, body: { enabled } }, autosaveFeedback(webhook.name))
                  }
                />
              </div>
              <p className="truncate font-mono text-xs text-muted-foreground" title={webhook.url}>{webhook.url}</p>
              <div className="flex flex-wrap gap-1">
                {webhook.events.map((event) => (
                  <Badge key={event} variant="secondary" className="font-mono text-[11px]">
                    {event === ALL ? t('webhooks.allEvents') : event}
                  </Badge>
                ))}
              </div>
              <div className="flex flex-wrap justify-end gap-1 border-t pt-2">
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={test.isPending}
                  onClick={() =>
                    test.mutate(webhook.id, {
                      onSuccess: (d) =>
                        d.status === 'delivered'
                          ? toast.success(t('webhooks.testDelivered'))
                          : toast.error(t('webhooks.testFailed', { error: d.last_error ?? `HTTP ${d.last_status_code}` })),
                    })
                  }
                >
                  <SendIcon className="size-4" />
                  {t('webhooks.test')}
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setDeliveries(webhook)}>
                  <HistoryIcon className="size-4" />
                  {t('webhooks.deliveries')}
                </Button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  title={t('webhooks.rotate')}
                  onClick={() => rotate.mutate(webhook.id, { onSuccess: (r) => setSecret(r.secret) })}
                >
                  <RotateCwIcon className="size-4" />
                </Button>
                <Button variant="ghost" size="icon-sm" title={t('common.edit')} onClick={() => setEditing(webhook)}>
                  <PencilIcon className="size-4" />
                </Button>
                <Button variant="ghost" size="icon-sm" title={t('common.delete')} onClick={() => setDeleting(webhook)}>
                  <TrashIcon className="size-4" />
                </Button>
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      {editing !== null && (
        <WebhookDialog
          key={editing === 'new' ? 'new' : editing.id}
          webhook={editing === 'new' ? null : editing}
          open
          onClose={() => setEditing(null)}
          onCreated={setSecret}
        />
      )}
      <DeliveriesDialog webhook={deliveries} onClose={() => setDeliveries(null)} />
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
            <DialogTitle>{t('webhooks.deleteTitle', { name: deleting?.name ?? '' })}</DialogTitle>
            <DialogDescription>{t('webhooks.deleteDescription')}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDeleting(null)}>{t('common.cancel')}</Button>
            <Button
              className="bg-destructive text-white hover:bg-destructive/90"
              onClick={() => deleting && remove.mutate(deleting.id, { onSuccess: () => setDeleting(null) })}
            >
              {t('common.delete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
