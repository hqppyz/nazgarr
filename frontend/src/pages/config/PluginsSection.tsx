import { PuzzleIcon, SendIcon, ShieldAlertIcon } from 'lucide-react'
import { toast } from 'sonner'
import { useState } from 'react'

import { useAdapterConfig, usePlugins, useSaveAdapterConfig, useTestNotification } from '@/api/hooks/plugins'
import { useWebhookEvents } from '@/api/hooks/webhooks'
import type { Schemas } from '@/api/client'
import {
  AdapterConfigFields,
  configPayload,
  initialConfigValues,
  missingRequired,
  type ConfigValues,
} from '@/components/AdapterConfigFields'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { autosaveFeedback } from '@/lib/autosave'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { t } from '@/lib/i18n'
import { cn } from '@/lib/utils'

const STATUS_STYLE: Record<string, string> = {
  loaded: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
  failed: 'border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-300',
  incompatible: 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300',
  install_failed: 'border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-300',
}
const KINDS = ['tracker', 'torrent_client', 'media_resolver', 'image_host', 'notification'] as const
// Gli adapter senza una riga propria: si configurano qui.
const GLOBAL_KINDS = ['image_host', 'media_resolver', 'notification']

type Adapter = Schemas['AdapterResponse']
const ALL = '*'

// Notifiche: quali eventi manda, l'ultima consegna e l'invio di prova.
function NotificationControls({ adapter, events, lastDelivery }: {
  adapter: Adapter
  events: string[]
  lastDelivery: Schemas['LastDelivery'] | null | undefined
}) {
  const { data: catalog } = useWebhookEvents()
  const save = useSaveAdapterConfig(adapter.kind, adapter.adapter_type)
  const test = useTestNotification(adapter.adapter_type)
  const all = events.includes(ALL)
  const feedback = autosaveFeedback(`${adapter.label} · ${t('plugins.events')}`)
  const setEvents = (next: string[]) => next.length > 0 && save.mutate({ events: next }, feedback)
  return (
    <div className="grid gap-2 border-t pt-3">
      <div className="flex items-center gap-2">
        <Switch id={`n-all-${adapter.adapter_type}`} checked={all} onCheckedChange={(checked) => checked && setEvents([ALL])} />
        <label htmlFor={`n-all-${adapter.adapter_type}`} className="text-sm">{t('webhooks.allEvents')}</label>
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {catalog?.map((event) => (
          <label key={event.name} className="flex cursor-pointer items-center gap-1.5 text-xs" title={event.description}>
            <input
              type="checkbox"
              checked={all || events.includes(event.name)}
              onChange={(e) => {
                const current = all ? catalog.map((c) => c.name) : events
                setEvents(e.target.checked ? [...current, event.name] : current.filter((n) => n !== event.name))
              }}
            />
            <span className="font-mono">{event.name}</span>
          </label>
        ))}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs text-muted-foreground">
          {lastDelivery
            ? t('plugins.lastDelivery', { event: lastDelivery.event, status: t(`webhooks.status.${lastDelivery.status}`) }) +
              (lastDelivery.error ? ` — ${lastDelivery.error}` : '')
            : t('webhooks.noDeliveries')}
        </span>
        <Button
          variant="outline"
          size="sm"
          disabled={test.isPending}
          onClick={() =>
            test.mutate(undefined, {
              onSuccess: (r) =>
                r.status === 'delivered'
                  ? toast.success(t('webhooks.testDelivered'))
                  : toast.error(t('webhooks.testFailed', { error: r.error ?? '' })),
            })
          }
        >
          <SendIcon className="size-4" />
          {t('webhooks.test')}
        </Button>
      </div>
    </div>
  )
}

export function GlobalAdapterCard({ adapter }: { adapter: Adapter }) {
  const { data } = useAdapterConfig(adapter.kind, adapter.adapter_type)
  const save = useSaveAdapterConfig(adapter.kind, adapter.adapter_type)
  const [values, setValues] = useState<ConfigValues | null>(null)
  if (!data) return null
  const current = values ?? initialConfigValues(adapter.config_fields, data.values)
  const title = `${adapter.label} · ${t(`plugins.kind.${adapter.kind}`)}`
  const notification = adapter.kind === 'notification' ? (
    <NotificationControls adapter={adapter} events={data.events ?? [ALL]} lastDelivery={data.last_delivery} />
  ) : null
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3">
        <div className="grid gap-1">
          <CardTitle className="text-base">{adapter.label}</CardTitle>
          <CardDescription>
            {t(`plugins.kind.${adapter.kind}`)} · {adapter.plugin ?? t('plugins.builtin')}
            {adapter.description ? ` — ${adapter.description}` : ''}
          </CardDescription>
        </div>
        <Switch
          checked={data.enabled}
          title={t('plugins.enabled')}
          onCheckedChange={(enabled) => save.mutate({ enabled }, autosaveFeedback(title))}
        />
      </CardHeader>
      {adapter.config_fields.length > 0 && (
        <CardContent className="grid gap-3">
          <AdapterConfigFields
            idPrefix={`plugin-${adapter.kind}-${adapter.adapter_type}`}
            fields={adapter.config_fields}
            values={current}
            secretsSet={data.secrets_set}
            onChange={setValues}
          />
          <div className="flex justify-end">
            <Button
              size="sm"
              disabled={save.isPending || missingRequired(adapter.config_fields, current, data.secrets_set)}
              onClick={() => {
                const feedback = autosaveFeedback(title)
                save.mutate(
                  { config: configPayload(adapter.config_fields, current) },
                  {
                    onSuccess: () => {
                      setValues(null)
                      feedback.onSuccess()
                    },
                    onError: feedback.onError,
                  },
                )
              }}
            >
              {t('common.save')}
            </Button>
          </div>
          {notification}
        </CardContent>
      )}
      {adapter.config_fields.length === 0 && notification && <CardContent>{notification}</CardContent>}
    </Card>
  )
}

// Plugin caricati e adapter disponibili, in sola lettura: la lista dei
// plugin si cambia da NAZGARR_PLUGINS o plugins.txt, con un riavvio.
export function PluginsSection() {
  const { data, isPending } = usePlugins()
  if (isPending || !data) return <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
  const source = data.source
    ? t(`plugins.source.${data.source}`, { env: data.env_var })
    : t('plugins.source.none')

  return (
    <>
      <div className="flex gap-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 text-sm">
        <ShieldAlertIcon className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400" />
        <div className="grid gap-1">
          <p className="font-medium">{t('plugins.trustTitle')}</p>
          <p className="text-muted-foreground">{t('plugins.trust')}</p>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center gap-2">
            {source}
            <Badge variant="outline" className="font-mono">{t('plugins.sdkVersion', { version: data.sdk_version })}</Badge>
          </CardTitle>
          <CardDescription>{t('plugins.howTo', { env: data.env_var })}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3">
          {data.requested.length > 0 && (
            <p className="font-mono text-xs break-all text-muted-foreground">{data.requested.join('  ')}</p>
          )}
          {data.install_error && (
            <div className="grid gap-1 rounded-md border border-red-500/40 bg-red-500/10 p-3 text-xs">
              <p className="font-medium text-red-700 dark:text-red-300">{t('plugins.installFailed')}</p>
              <pre className="overflow-x-auto font-mono whitespace-pre-wrap text-muted-foreground">{data.install_error}</pre>
            </div>
          )}
          {data.plugins.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t('plugins.none')}</p>
          ) : (
            <ul className="grid gap-2">
              {data.plugins.map((plugin) => (
                <li key={plugin.name} className="grid gap-1 rounded-md border p-3 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <PuzzleIcon className="size-4 text-muted-foreground" />
                    <span className="font-medium">{plugin.distribution ?? plugin.name}</span>
                    {plugin.version && <span className="font-mono text-xs text-muted-foreground">{plugin.version}</span>}
                    <Badge variant="outline" className={cn(STATUS_STYLE[plugin.status])}>
                      {t(`plugins.status.${plugin.status}`)}
                    </Badge>
                    {plugin.requires_sdk && (
                      <span className="font-mono text-[11px] text-muted-foreground">SDK {plugin.requires_sdk}</span>
                    )}
                  </div>
                  {plugin.error && <p className="font-mono text-xs break-words text-red-700 dark:text-red-300">{plugin.error}</p>}
                  <p className="text-xs text-muted-foreground">
                    {plugin.adapters.length > 0
                      ? t('plugins.provides', { adapters: plugin.adapters.join(', ') })
                      : t('plugins.providesNothing')}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {data.adapters
        // I servizi di notifica stanno in Impostazioni › Notifiche, integrati e dei plugin.
        .filter((a) => a.plugin && GLOBAL_KINDS.includes(a.kind) && a.kind !== 'notification')
        .map((adapter) => (
          <GlobalAdapterCard key={`${adapter.kind}:${adapter.adapter_type}`} adapter={adapter} />
        ))}

      <Card>
        <CardHeader>
          <CardTitle>{t('plugins.adaptersTitle')}</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          {KINDS.map((kind) => {
            const adapters = data.adapters.filter((a) => a.kind === kind)
            if (adapters.length === 0) return null
            return (
              <div key={kind} className="grid content-start gap-1.5">
                <p className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">{t(`plugins.kind.${kind}`)}</p>
                <div className="flex flex-wrap gap-1.5">
                  {adapters.map((adapter) => (
                    <Badge key={adapter.adapter_type} variant="secondary" title={adapter.description ?? undefined}>
                      {adapter.label}
                      <span className="ml-1 font-normal text-muted-foreground">
                        {adapter.plugin ?? t('plugins.builtin')}
                      </span>
                    </Badge>
                  ))}
                </div>
              </div>
            )
          })}
        </CardContent>
      </Card>
    </>
  )
}
