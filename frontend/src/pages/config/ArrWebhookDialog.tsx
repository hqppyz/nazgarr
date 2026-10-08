import { CheckIcon, CopyIcon, WebhookIcon } from 'lucide-react'
import { useState } from 'react'

import { type ArrKind, useRemoveArrWebhook, useSetupArrWebhook } from '@/api/hooks/arrInstances'
import { useSetSetting, useSetting } from '@/api/hooks/settings'
import type { Schemas } from '@/api/client'
import { ConfirmButton } from '@/components/ConfirmButton'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { autosaveFeedback } from '@/lib/autosave'
import { t } from '@/lib/i18n'
import { relativeFromNow } from '@/lib/time'
import { cn } from '@/lib/utils'

interface Instance {
  id: number
  label: string
  webhook_enabled?: boolean
  webhook_last_event?: Schemas['ArrWebhookEventSummary'] | null
}

function CopyField({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="grid gap-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      <div className="flex items-center gap-2">
        <code className="min-w-0 flex-1 rounded bg-muted px-2 py-1.5 font-mono text-xs break-all">{value}</code>
        <Button size="icon-sm" variant="outline" aria-label={t('integrations.webhook.copy', { what: label })}
                onClick={() => {
                  void navigator.clipboard?.writeText(value)
                  setCopied(true)
                  window.setTimeout(() => setCopied(false), 1500)
                }}>
          {copied ? <CheckIcon className="size-4" /> : <CopyIcon className="size-4" />}
        </Button>
      </div>
    </div>
  )
}

// Il webhook di un'istanza Radarr/Sonarr: un file importato, aggiornato,
// rinominato o cancellato aggiorna subito la libreria, senza una scansione.
export function ArrWebhookDialog({ kind, instance, serviceName }: { kind: ArrKind; instance: Instance; serviceName: string }) {
  const setup = useSetupArrWebhook(kind)
  const remove = useRemoveArrWebhook(kind)
  const { data: search } = useSetting('arr_webhook_search')
  const setSearch = useSetSetting('arr_webhook_search')
  const [created, setCreated] = useState<{ url: string; token: string } | null>(null)
  const last = instance.webhook_last_event
  const create = () =>
    setup.mutate(instance.id, {
      onSuccess: (result) => setCreated({ url: `${window.location.origin}${result.path}`, token: result.token }),
    })

  return (
    <Dialog onOpenChange={(open) => !open && setCreated(null)}>
      <DialogTrigger
        render={
          <Button variant="ghost" size="icon-sm" title={t('integrations.webhook.title')}
                  aria-label={t('integrations.webhook.title')}>
            <WebhookIcon className={cn('size-4', instance.webhook_enabled ? 'text-primary' : 'text-muted-foreground')} />
          </Button>
        }
      />
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('integrations.webhook.dialogTitle', { label: instance.label })}</DialogTitle>
          <DialogDescription>{t('integrations.webhook.description', { name: serviceName })}</DialogDescription>
        </DialogHeader>

        {created ? (
          <div className="grid gap-3">
            <CopyField label={t('integrations.webhook.url')} value={created.url} />
            <CopyField label={t('integrations.webhook.password')} value={created.token} />
            <p className="text-xs text-muted-foreground">{t('integrations.webhook.shownOnce')}</p>
            <ol className="grid list-decimal gap-1 pl-5 text-sm">
              <li>{t('integrations.webhook.step1', { name: serviceName })}</li>
              <li>{t('integrations.webhook.step2')}</li>
              <li>{t(kind === 'radarr' ? 'integrations.webhook.step3Radarr' : 'integrations.webhook.step3Sonarr')}</li>
              <li>{t('integrations.webhook.step4')}</li>
            </ol>
            <p className="text-xs text-muted-foreground">{t('integrations.webhook.reachability', { name: serviceName })}</p>
          </div>
        ) : instance.webhook_enabled ? (
          <div className="grid gap-3 text-sm">
            <p>
              {last
                ? t('integrations.webhook.lastEvent', {
                    event: last.event_type, when: relativeFromNow(last.received_at), detail: last.detail ?? last.status,
                  })
                : t('integrations.webhook.noEventYet', { name: serviceName })}
            </p>
            <div className="flex flex-wrap gap-2">
              <ConfirmButton
                trigger={<Button size="sm" variant="outline">{t('integrations.webhook.regenerate')}</Button>}
                title={t('integrations.webhook.regenerateTitle')}
                description={t('integrations.webhook.regenerateDescription', { name: serviceName })}
                confirmLabel={t('integrations.webhook.regenerate')}
                pending={setup.isPending}
                onConfirm={create}
              />
              <ConfirmButton
                trigger={<Button size="sm" variant="ghost">{t('integrations.webhook.disable')}</Button>}
                title={t('integrations.webhook.disableTitle')}
                description={t('integrations.webhook.disableDescription', { name: serviceName })}
                confirmLabel={t('integrations.webhook.disable')}
                pending={remove.isPending}
                onConfirm={() => remove.mutate(instance.id)}
              />
            </div>
          </div>
        ) : (
          <div className="grid gap-3 text-sm">
            <p className="text-muted-foreground">{t('integrations.webhook.why')}</p>
            <Button className="w-fit" disabled={setup.isPending} onClick={create}>{t('integrations.webhook.enable')}</Button>
          </div>
        )}

        <div className="flex items-start justify-between gap-3 border-t pt-3">
          <div className="grid gap-0.5">
            <Label htmlFor={`webhook-search-${kind}-${instance.id}`}>{t('integrations.webhook.searchLabel')}</Label>
            <p className="text-xs text-muted-foreground">{t('integrations.webhook.searchHelp')}</p>
          </div>
          <Switch
            id={`webhook-search-${kind}-${instance.id}`}
            checked={search?.value === 'true'}
            disabled={setSearch.isPending}
            onCheckedChange={(on) => setSearch.mutate(on ? 'true' : 'false', autosaveFeedback(t('integrations.webhook.searchLabel')))}
          />
        </div>
      </DialogContent>
    </Dialog>
  )
}
