import { useQueryClient } from '@tanstack/react-query'
import {
  BellIcon,
  HardDriveDownloadIcon,
  ImageIcon,
  PuzzleIcon,
  RadioTowerIcon,
  ScanSearchIcon,
  SettingsIcon,
  ShieldAlertIcon,
  type LucideIcon,
} from 'lucide-react'
import { useState } from 'react'

import type { Schemas } from '@/api/client'
import { useAdapterConfig, usePlugins, useSaveAdapterConfig, useSetPluginEnabled } from '@/api/hooks/plugins'
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
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Switch } from '@/components/ui/switch'
import { autosaveFeedback } from '@/lib/autosave'
import { t } from '@/lib/i18n'
import { cn } from '@/lib/utils'

type Plugin = Schemas['PluginResponse']
type Adapter = Schemas['AdapterResponse']

// L'icona di un plugin senza la sua: quella della sua categoria.
const KIND_ICONS: Record<string, LucideIcon> = {
  image_host: ImageIcon, notification: BellIcon, tracker: RadioTowerIcon, torrent_client: HardDriveDownloadIcon,
  media_resolver: ScanSearchIcon,
}
const BROKEN = ['failed', 'incompatible', 'install_failed']

// La configurazione di un adapter globale del plugin (host di immagini,
// resolver), nel dialogo delle impostazioni.
function AdapterSettings({ adapter }: { adapter: Adapter }) {
  const { data } = useAdapterConfig(adapter.kind, adapter.adapter_type)
  const save = useSaveAdapterConfig(adapter.kind, adapter.adapter_type)
  const queryClient = useQueryClient()
  const [values, setValues] = useState<ConfigValues | null>(null)
  if (!data) return <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
  const current = values ?? initialConfigValues(adapter.config_fields, data.values)
  return (
    <div className="grid gap-3">
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
          disabled={save.isPending || values === null || missingRequired(adapter.config_fields, current, data.secrets_set)}
          onClick={() => {
            const feedback = autosaveFeedback(adapter.label)
            save.mutate({ config: configPayload(adapter.config_fields, current) }, {
              onSuccess: () => {
                setValues(null)
                feedback.onSuccess()
              },
              onError: feedback.onError,
              onSettled: () => queryClient.invalidateQueries({ queryKey: ['uploads', 'image-hosts'] }),
            })
          }}
        >
          {t('common.save')}
        </Button>
      </div>
    </div>
  )
}

// Come le estensioni di un browser: nome, interruttore, fonte, categoria e,
// se ne ha, le impostazioni in un dialogo.
function PluginCard({ plugin, adapters }: { plugin: Plugin; adapters: Adapter[] }) {
  const setEnabled = useSetPluginEnabled(plugin.name)
  const [open, setOpen] = useState(false)
  const broken = BROKEN.includes(plugin.status)
  const Icon = KIND_ICONS[plugin.categories[0] ?? ''] ?? PuzzleIcon
  const settings = adapters.filter((a) => plugin.settings.includes(`${a.kind}:${a.adapter_type}`))
  return (
    <Card size="sm" className={cn('gap-3', !plugin.enabled && 'opacity-70')}>
      <CardHeader className="flex flex-row items-start gap-3">
        <div className="flex size-9 shrink-0 items-center justify-center rounded-md bg-muted">
          {plugin.icon ? <img src={plugin.icon} alt="" className="size-5" /> : <Icon className="size-4 text-muted-foreground" />}
        </div>
        <div className="grid min-w-0 flex-1 gap-1">
          <CardTitle className="truncate text-sm">{plugin.label}</CardTitle>
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge variant="secondary" className="text-[11px]">
              {plugin.bundled ? t('plugins.native') : t('plugins.installed')}
            </Badge>
            {plugin.categories.map((kind) => (
              <Badge key={kind} variant="outline" className="text-[11px]">{t(`plugins.kind.${kind}`)}</Badge>
            ))}
            {broken && (
              <Badge variant="outline" className="border-red-500/40 bg-red-500/10 text-[11px] text-red-700 dark:text-red-300">
                {t(`plugins.status.${plugin.status}`)}
              </Badge>
            )}
          </div>
        </div>
        {!broken && (
          <Switch
            checked={plugin.enabled}
            disabled={setEnabled.isPending}
            aria-label={t('plugins.toggle', { name: plugin.label })}
            onCheckedChange={(enabled) =>
              setEnabled.mutate(enabled, autosaveFeedback(t(enabled ? 'plugins.switchedOn' : 'plugins.switchedOff', { name: plugin.label })))
            }
          />
        )}
      </CardHeader>
      <CardContent className="grid gap-2">
        {plugin.description && <p className="line-clamp-2 text-xs text-muted-foreground">{plugin.description}</p>}
        {plugin.error && <p className="font-mono text-xs break-words text-red-700 dark:text-red-300">{plugin.error}</p>}
        <div className="flex items-center gap-2">
          <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-muted-foreground">
            {plugin.bundled ? plugin.name : [plugin.distribution ?? plugin.name, plugin.version].filter(Boolean).join(' ')}
          </span>
          {settings.length > 0 && plugin.enabled && (
            <Button size="xs" variant="outline" onClick={() => setOpen(true)}>
              <SettingsIcon className="size-3" />
              {t('plugins.settings')}
            </Button>
          )}
        </div>
      </CardContent>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('plugins.settingsTitle', { name: plugin.label })}</DialogTitle>
            {plugin.description && <DialogDescription>{plugin.description}</DialogDescription>}
          </DialogHeader>
          {settings.map((adapter) => (
            <div key={adapter.adapter_type} className="grid gap-2">
              {settings.length > 1 && <p className="text-sm font-medium">{adapter.label}</p>}
              <AdapterSettings adapter={adapter} />
            </div>
          ))}
        </DialogContent>
      </Dialog>
    </Card>
  )
}

// I plugin nativi (inclusi in Nazgarr) e quelli installati, uno per card. La
// lista dei plugin installati si cambia da NAZGARR_PLUGINS o plugins.txt, con
// un riavvio; accenderli e spegnerli no.
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

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {data.plugins.map((plugin) => (
          <PluginCard key={plugin.name} plugin={plugin} adapters={data.adapters} />
        ))}
      </div>

      <Card data-tour="plugins.source">
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center gap-2">
            {t('plugins.addTitle')}
            <Badge variant="outline" className="font-mono">{t('plugins.sdkVersion', { version: data.sdk_version })}</Badge>
          </CardTitle>
          <CardDescription>{t('plugins.howTo', { env: data.env_var })}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-2">
          <p className="text-sm">{source}</p>
          {data.requested.length > 0 && (
            <p className="font-mono text-xs break-all text-muted-foreground">{data.requested.join('  ')}</p>
          )}
          {data.install_error && (
            <div className="grid gap-1 rounded-md border border-red-500/40 bg-red-500/10 p-3 text-xs">
              <p className="font-medium text-red-700 dark:text-red-300">{t('plugins.installFailed')}</p>
              <pre className="overflow-x-auto font-mono whitespace-pre-wrap text-muted-foreground">{data.install_error}</pre>
            </div>
          )}
        </CardContent>
      </Card>
    </>
  )
}
