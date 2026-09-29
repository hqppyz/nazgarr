import {
  FilterXIcon,
  HardDriveIcon,
  InfoIcon,
  LanguagesIcon,
  LayoutGridIcon,
  PlugIcon,
  ScrollTextIcon,
  ShieldIcon,
  TagIcon,
  UploadCloudIcon,
} from 'lucide-react'

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
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
import { t } from '@/lib/i18n'

export function ConfigurationPage() {
  return (
    <Tabs defaultValue="application" orientation="vertical" className="gap-6">
      <TabsList className="w-56 shrink-0 items-stretch gap-1 bg-transparent p-0">
        <TabsTrigger value="application" className="justify-start gap-2 px-3 py-2">
          <InfoIcon />
          Application
        </TabsTrigger>
        <TabsTrigger value="mapping" className="justify-start gap-2 px-3 py-2">
          <HardDriveIcon />
          Mapping
        </TabsTrigger>
        <TabsTrigger value="exclusions" className="justify-start gap-2 px-3 py-2">
          <FilterXIcon />
          {t('exclusions.tab')}
        </TabsTrigger>
        <TabsTrigger value="integrations" className="justify-start gap-2 px-3 py-2">
          <PlugIcon />
          Integrations
        </TabsTrigger>
        <TabsTrigger value="metadata" className="justify-start gap-2 px-3 py-2">
          <TagIcon />
          Metadata
        </TabsTrigger>
        <TabsTrigger value="upload" className="justify-start gap-2 px-3 py-2">
          <UploadCloudIcon />
          Upload
        </TabsTrigger>
        <TabsTrigger value="security" className="justify-start gap-2 px-3 py-2">
          <ShieldIcon />
          Security
        </TabsTrigger>
        <TabsTrigger value="interface" className="justify-start gap-2 px-3 py-2">
          <LayoutGridIcon />
          {t('interface.tab')}
        </TabsTrigger>
        <TabsTrigger value="time-language" className="justify-start gap-2 px-3 py-2">
          <LanguagesIcon />
          Language & Formats
        </TabsTrigger>
        <TabsTrigger value="logs" className="justify-start gap-2 px-3 py-2">
          <ScrollTextIcon />
          Logs
        </TabsTrigger>
      </TabsList>
      <TabsContent value="interface">
        <InterfaceSection />
      </TabsContent>
      <TabsContent value="application">
        <ApplicationSection />
      </TabsContent>
      <TabsContent value="mapping" className="grid gap-6">
        <DisksSection />
        <TorrentClientsSection />
        <AutoApproveSection />
      </TabsContent>
      <TabsContent value="exclusions">
        <ExclusionsSection />
      </TabsContent>
      <TabsContent value="integrations" className="grid gap-6">
        <TrackersSection />
        <IntegrationsSection />
      </TabsContent>
      <TabsContent value="metadata">
        <MetadataSection />
      </TabsContent>
      <TabsContent value="upload">
        <UploadSettingsSection />
      </TabsContent>
      <TabsContent value="security">
        <SecuritySection />
      </TabsContent>
      <TabsContent value="time-language">
        <TimeLanguageSection />
      </TabsContent>
      <TabsContent value="logs">
        <LogsSection />
      </TabsContent>
    </Tabs>
  )
}
