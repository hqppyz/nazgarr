import {
  FilterXIcon,
  GaugeIcon,
  HardDriveDownloadIcon,
  HardDriveIcon,
  InfoIcon,
  LayoutGridIcon,
  PlugIcon,
  RadioTowerIcon,
  ScrollTextIcon,
  ShieldIcon,
  UploadCloudIcon,
  type LucideIcon,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { t } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { ApplicationSection } from '@/pages/config/ApplicationSection'
import { AutoApproveSection } from '@/pages/config/AutoApproveSection'
import { DisksSection } from '@/pages/config/DisksSection'
import { ExclusionsSection } from '@/pages/config/ExclusionsSection'
import { IntegrationsSection } from '@/pages/config/IntegrationsSection'
import { InterfaceSection } from '@/pages/config/InterfaceSection'
import { LogsSection } from '@/pages/config/LogsSection'
import { MetadataSection } from '@/pages/config/MetadataSection'
import { SecuritySection } from '@/pages/config/SecuritySection'
import { TimeLanguageSection } from '@/pages/config/TimeLanguageSection'
import { TorrentClientsSection } from '@/pages/config/TorrentClientsSection'
import { TrackersSection } from '@/pages/config/TrackersSection'
import { UploadSettingsSection } from '@/pages/config/UploadSettingsSection'

// Impostazioni in gruppi per argomento (Generale, Libreria, Torrent,
// Reseeding, Sistema). Il tab aperto sta nell'URL (?tab=…), così un link da
// un'altra pagina porta dritto al tab giusto.
//
// Layout: le card piccole si affiancano (due colonne da lg), le tabelle e
// le liste larghe restano a tutta larghezza.
const PAIRS = 'grid items-start gap-6 lg:grid-cols-2'
const STACK = 'grid gap-6'

interface Tab {
  value: string
  label: string
  icon: LucideIcon
  layout: string
  content: ReactNode
}

const GROUPS: { title: string; tabs: Tab[] }[] = [
  {
    title: t('config.groupGeneral'),
    tabs: [
      { value: 'application', label: t('config.tabApplication'), icon: InfoIcon, layout: PAIRS, content: <ApplicationSection /> },
      {
        value: 'interface',
        label: t('config.tabInterface'),
        icon: LayoutGridIcon,
        layout: PAIRS,
        content: (
          <>
            <InterfaceSection />
            <TimeLanguageSection />
          </>
        ),
      },
      { value: 'security', label: t('config.tabSecurity'), icon: ShieldIcon, layout: PAIRS, content: <SecuritySection /> },
    ],
  },
  {
    title: t('config.groupLibrary'),
    tabs: [
      { value: 'storage', label: t('config.tabStorage'), icon: HardDriveIcon, layout: STACK, content: <DisksSection /> },
      { value: 'exclusions', label: t('config.tabExclusions'), icon: FilterXIcon, layout: PAIRS, content: <ExclusionsSection /> },
      {
        value: 'integrations',
        label: t('config.tabIntegrations'),
        icon: PlugIcon,
        layout: STACK,
        content: (
          <>
            <div className={PAIRS}>
              <MetadataSection />
            </div>
            <IntegrationsSection />
          </>
        ),
      },
    ],
  },
  {
    title: t('config.groupTorrent'),
    tabs: [
      { value: 'clients', label: t('config.tabClients'), icon: HardDriveDownloadIcon, layout: STACK, content: <TorrentClientsSection /> },
      { value: 'trackers', label: t('config.tabTrackers'), icon: RadioTowerIcon, layout: STACK, content: <TrackersSection /> },
    ],
  },
  {
    title: t('config.groupReseeding'),
    tabs: [
      { value: 'matching', label: t('config.tabMatching'), icon: GaugeIcon, layout: PAIRS, content: <AutoApproveSection /> },
    ],
  },
  {
    title: t('config.groupSystem'),
    tabs: [
      { value: 'upload', label: t('config.tabUpload'), icon: UploadCloudIcon, layout: PAIRS, content: <UploadSettingsSection /> },
      { value: 'logs', label: t('config.tabLogs'), icon: ScrollTextIcon, layout: STACK, content: <LogsSection /> },
    ],
  },
]

const ALL_TABS = GROUPS.flatMap((group) => group.tabs)
// Tab di prima del riordino, per i link già salvati.
const RENAMED: Record<string, string> = { mapping: 'storage', metadata: 'integrations', 'time-language': 'interface' }

export function ConfigurationPage() {
  const [params, setParams] = useSearchParams()
  const requested = params.get('tab') ?? ''
  const current = ALL_TABS.some((tab) => tab.value === requested) ? requested : (RENAMED[requested] ?? 'application')

  return (
    <Tabs
      value={current}
      onValueChange={(value) => setParams({ tab: String(value) }, { replace: true })}
      orientation="vertical"
      className="gap-6"
    >
      <TabsList className="w-56 shrink-0 items-stretch gap-0.5 bg-transparent p-0">
        {GROUPS.map((group, i) => (
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
        <TabsContent key={tab.value} value={tab.value} className={tab.layout}>
          {tab.content}
        </TabsContent>
      ))}
    </Tabs>
  )
}
