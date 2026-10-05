import {
  BellIcon,
  FilterXIcon,
  GaugeIcon,
  HardDriveDownloadIcon,
  HardDriveIcon,
  ImageIcon,
  InfoIcon,
  KeyRoundIcon,
  LayoutGridIcon,
  LockIcon,
  PlugIcon,
  PuzzleIcon,
  RadioTowerIcon,
  ScrollTextIcon,
  ServerIcon,
  ShieldIcon,
  UploadCloudIcon,
  type LucideIcon,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'

import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Masonry } from '@/components/Masonry'
import { SettingsHeader } from '@/components/SettingsHeader'
import { t } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { safeHref } from '@/lib/safeUrl'
import { activeInstanceId, isRemote } from '@/lib/instance'
import { useInstances } from '@/api/hooks/instances'
import { ApiKeysSection } from '@/pages/config/ApiKeysSection'
import { ApplicationSection } from '@/pages/config/ApplicationSection'
import { AutoApproveSection } from '@/pages/config/AutoApproveSection'
import { DisksSection } from '@/pages/config/DisksSection'
import { ExclusionsSection } from '@/pages/config/ExclusionsSection'
import { IntegrationsSection } from '@/pages/config/IntegrationsSection'
import { InterfaceSection } from '@/pages/config/InterfaceSection'
import { LogsSection } from '@/pages/config/LogsSection'
import { InstancesSection } from '@/pages/config/InstancesSection'
import { MetadataSection } from '@/pages/config/MetadataSection'
import { NotificationsSection } from '@/pages/config/NotificationsSection'
import { PluginsSection } from '@/pages/config/PluginsSection'
import { SecuritySection } from '@/pages/config/SecuritySection'
import { TorrentClientsSection } from '@/pages/config/TorrentClientsSection'
import { TrackersSection } from '@/pages/config/TrackersSection'
import { UploadImagesSection, UploadReleasesSection } from '@/pages/config/UploadSettingsSection'

// Impostazioni in gruppi per argomento (Generale, Libreria, Torrent,
// Reseeding, Upload, Estensioni, Sistema). Il tab aperto sta nell'URL (?tab=…), così un link da
// un'altra pagina porta dritto al tab giusto.
//
// Layout: le card piccole in un masonry a due colonne (components/Masonry.tsx,
// da lg): ogni card nella colonna più corta, quelle con data-masonry="full"
// a tutta larghezza. Le tabelle e le liste larghe restano impilate.
const PAIRS = 'masonry'
const STACK = 'stack'

interface Tab {
  value: string
  label: string
  icon: LucideIcon
  layout: 'masonry' | 'stack'
  content: ReactNode
  // Sotto il titolo: a cosa serve il tab.
  description?: string
  // Il tab ha la sua intestazione (SettingsHeader con il pulsante "Add" o un
  // filtro a destra): clienti, tracker, API key, webhook, log.
  ownHeading?: boolean
}

const GROUPS: { title: string; tabs: Tab[] }[] = [
  {
    title: t('config.groupGeneral'),
    tabs: [
      { value: 'application', label: t('config.tabApplication'), icon: InfoIcon, layout: PAIRS, content: <ApplicationSection />, description: t('config.descApplication') },
      { value: 'interface', label: t('config.tabInterface'), icon: LayoutGridIcon, layout: PAIRS, content: <InterfaceSection />, description: t('config.descInterface') },
      { value: 'security', label: t('config.tabSecurity'), icon: ShieldIcon, layout: PAIRS, content: <SecuritySection />, description: t('config.descSecurity') },
    ],
  },
  {
    title: t('config.groupLibrary'),
    tabs: [
      { value: 'storage', label: t('config.tabStorage'), icon: HardDriveIcon, layout: STACK, content: <DisksSection />, ownHeading: true },
      { value: 'exclusions', label: t('config.tabExclusions'), icon: FilterXIcon, layout: PAIRS, content: <ExclusionsSection />, description: t('config.descExclusions') },
      {
        value: 'integrations',
        label: t('config.tabIntegrations'),
        icon: PlugIcon,
        layout: STACK,
        description: t('config.descIntegrations'),
        content: (
          <>
            <Masonry gap={24}>
              <MetadataSection />
            </Masonry>
            <IntegrationsSection />
          </>
        ),
      },
    ],
  },
  {
    title: t('config.groupTorrent'),
    tabs: [
      { value: 'clients', label: t('config.tabClients'), icon: HardDriveDownloadIcon, layout: STACK, content: <TorrentClientsSection />, ownHeading: true },
      { value: 'trackers', label: t('config.tabTrackers'), icon: RadioTowerIcon, layout: STACK, content: <TrackersSection />, ownHeading: true },
    ],
  },
  {
    title: t('config.groupReseeding'),
    tabs: [
      { value: 'matching', label: t('config.tabMatching'), icon: GaugeIcon, layout: PAIRS, content: <AutoApproveSection />,
        description: t('config.descMatching') },
    ],
  },
  {
    // Pubblicare nuovi upload: gli screenshot (host e scatti) e le release
    // (releaser, cartella osservata, descrizione, nomi dei file).
    title: t('config.groupUpload'),
    tabs: [
      { value: 'images', label: t('config.tabImages'), icon: ImageIcon, layout: PAIRS, content: <UploadImagesSection />,
        description: t('config.descImages') },
      { value: 'releases', label: t('config.tabReleases'), icon: UploadCloudIcon, layout: PAIRS,
        content: <UploadReleasesSection />, description: t('config.descReleases') },
    ],
  },
  {
    // Quello che estende Nazgarr o lo collega ad altri servizi: plugin,
    // notifiche, webhook e API key (docs/SDK.md).
    title: t('config.groupExtensions'),
    tabs: [
      { value: 'api-keys', label: t('config.tabApiKeys'), icon: KeyRoundIcon, layout: STACK, content: <ApiKeysSection />,
        ownHeading: true },
      { value: 'plugins', label: t('config.tabPlugins'), icon: PuzzleIcon, layout: STACK, content: <PluginsSection />,
        description: t('config.descPlugins') },
      { value: 'notifications', label: t('config.tabNotifications'), icon: BellIcon, layout: STACK,
        content: <NotificationsSection />, ownHeading: true },
    ],
  },
  {
    title: t('config.groupSystem'),
    tabs: [
      { value: 'instances', label: t('instances.title'), icon: ServerIcon, layout: STACK, content: <InstancesSection />,
        ownHeading: true },
      { value: 'logs', label: t('config.tabLogs'), icon: ScrollTextIcon, layout: STACK, content: <LogsSection />, ownHeading: true },
    ],
  },
]

// Su un'altra istanza: Sicurezza (il login di questa) e API key (che una API
// key non gestisce) restano nel menu, ma al loro posto c'è un avviso.
const LOCAL_ONLY = ['security', 'api-keys']
const VISIBLE_GROUPS = GROUPS
const ALL_TABS = VISIBLE_GROUPS.flatMap((group) => group.tabs)
// Tab di prima del riordino, per i link già salvati.
const RENAMED: Record<string, string> = {
  mapping: 'storage', metadata: 'integrations', 'time-language': 'interface', upload: 'images',
  webhooks: 'notifications',
}

// Al posto di Sicurezza e API key mentre si guarda un'altra istanza: si
// cambiano solo dalla sua interfaccia.
function LockedOnRemote({ title }: { title: string }) {
  const { data } = useInstances(true)
  const id = activeInstanceId()
  const instance = data?.instances.find((i) => i.id === id)
  return (
    <div className="grid max-w-2xl gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 text-sm">
      <p className="flex items-center gap-2 font-medium">
        <LockIcon className="size-4" />
        {t('instances.lockedTitle', { section: title, label: instance?.label ?? '' })}
      </p>
      <p className="text-muted-foreground">{t('instances.lockedHelp')}</p>
      {instance && (
        <a href={safeHref(instance.base_url)} target="_blank" rel="noreferrer"
           className="w-fit font-medium text-primary underline-offset-4 hover:underline">
          {t('instances.openItsUi')}
        </a>
      )}
    </div>
  )
}

export function ConfigurationPage() {
  const [params, setParams] = useSearchParams()
  const requested = params.get('tab') ?? ''
  const current = ALL_TABS.some((tab) => tab.value === requested) ? requested : (RENAMED[requested] ?? 'application')

  const select = (value: string) => setParams({ tab: value }, { replace: true })
  const currentTab = ALL_TABS.find((tab) => tab.value === current)

  return (
    <Tabs
      value={current}
      onValueChange={(value) => select(String(value))}
      orientation="vertical"
      className="flex-col gap-4 md:flex-row md:gap-6"
    >
      {/* Da telefono la colonna delle sezioni non ci sta: un select in cima. */}
      <Select value={current} onValueChange={(value) => value != null && select(String(value))}>
        <SelectTrigger className="w-full md:hidden" aria-label={t('nav.configuration')}>
          <SelectValue>
            {() =>
              currentTab && (
                <span className="flex items-center gap-2">
                  <currentTab.icon className="size-4" />
                  {currentTab.label}
                </span>
              )
            }
          </SelectValue>
        </SelectTrigger>
        <SelectContent>
          {VISIBLE_GROUPS.map((group) => (
            <SelectGroup key={group.title}>
              <SelectLabel>{group.title}</SelectLabel>
              {group.tabs.map((tab) => (
                <SelectItem key={tab.value} value={tab.value}>
                  <tab.icon className="size-4" />
                  {tab.label}
                </SelectItem>
              ))}
            </SelectGroup>
          ))}
        </SelectContent>
      </Select>
      {/* La colonna delle sezioni resta ferma mentre il contenuto scorre. */}
      <TabsList className="sticky top-0 hidden max-h-[calc(100svh-6rem)] w-56 shrink-0 items-stretch gap-0.5 self-start overflow-y-auto bg-transparent p-0 md:flex">
        {VISIBLE_GROUPS.map((group, i) => (
          <div key={group.title} className={cn('grid gap-0.5', i > 0 && 'mt-3')}>
            <p className="px-3 pb-1 text-[length:var(--text-xxs)] font-medium tracking-wide text-muted-foreground uppercase">
              {group.title}
            </p>
            {group.tabs.map((tab) => (
              <TabsTrigger key={tab.value} value={tab.value} className="justify-start gap-2 px-3 py-2">
                <tab.icon />
                {tab.label}
              </TabsTrigger>
            ))}
          </div>
        ))}
      </TabsList>
      {ALL_TABS.map((tab) => (
        <TabsContent key={tab.value} value={tab.value} className="grid min-w-0 content-start gap-4">
          {/* La stessa intestazione per ogni impostazione (components/SettingsHeader.tsx). */}
          {isRemote() && LOCAL_ONLY.includes(tab.value) ? (
            <LockedOnRemote title={tab.label} />
          ) : (
          <>
          {!tab.ownHeading && <SettingsHeader title={tab.label} description={tab.description} />}
          {tab.layout === 'masonry' ? (
            <Masonry gap={24}>{tab.content}</Masonry>
          ) : (
            <div className="grid min-w-0 content-start gap-6">{tab.content}</div>
          )}
          </>
          )}
        </TabsContent>
      ))}
    </Tabs>
  )
}
