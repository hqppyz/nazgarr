import { PuzzleIcon, ShieldAlertIcon } from 'lucide-react'

import { usePlugins } from '@/api/hooks/plugins'
import { Badge } from '@/components/ui/badge'
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
