import { usePlugins } from '@/api/hooks/plugins'
import { SettingsHeader } from '@/components/SettingsHeader'
import { t } from '@/lib/i18n'
import { GlobalAdapterCard } from '@/pages/config/PluginsSection'

// I servizi di notifica (integrati: Discord, Telegram; più quelli dei plugin):
// una card ciascuno, con i suoi campi, gli eventi da mandare e l'invio di prova.
export function NotificationsSection() {
  const { data, isPending } = usePlugins()
  const services = data?.adapters.filter((a) => a.kind === 'notification') ?? []
  return (
    <div className="grid content-start gap-4">
      <SettingsHeader title={t('config.tabNotifications')} description={t('config.descNotifications')} />
      {isPending && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}
      <div className="grid gap-4 lg:grid-cols-2">
        {services.map((adapter) => (
          <GlobalAdapterCard key={adapter.adapter_type} adapter={adapter} />
        ))}
      </div>
    </div>
  )
}
