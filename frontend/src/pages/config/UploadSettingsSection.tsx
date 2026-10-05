import { useState } from 'react'
import { toast } from 'sonner'

import { useSetSetting, useSetting } from '@/api/hooks/settings'
import { SettingField } from '@/components/SettingField'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { t } from '@/lib/i18n'
import { FileNamingCard } from '@/pages/config/FileNamingCard'
import { ImageHostPriorityField, parseOrder } from '@/pages/config/ImageHostPriorityField'
import { autosaveFeedback } from '@/lib/autosave'

function TonemapSwitch() {
  const { data } = useSetting('upload_tonemap_hdr')
  const setSetting = useSetSetting('upload_tonemap_hdr')
  const checked = data?.value === 'true'

  return (
    <div className="flex items-center justify-between">
      <div className="grid gap-0.5">
        <Label htmlFor="upload-tonemap">{t('uploadSettings.tonemapLabel')}</Label>
        <p className="text-xs text-muted-foreground">{t('uploadSettings.tonemapDescription')}</p>
      </div>
      <Switch
        id="upload-tonemap"
        checked={checked}
        onCheckedChange={(v) => setSetting.mutate(v ? 'true' : 'false', autosaveFeedback(t('uploadSettings.tonemapLabel')))}
      />
    </div>
  )
}

// Testo fisso aggiunto alla descrizione generata dal template del tracker:
// l'intestazione in cima, la firma in fondo (nazgarr/upload/description.py prepare).
// Salvataggio esplicito: un textarea in autosave salverebbe a ogni tasto.
function DescriptionTextField({
  settingKey,
  label,
  help,
  saveLabel,
  savedMessage,
}: {
  settingKey: string
  label: string
  help: string
  saveLabel: string
  savedMessage: string
}) {
  const { data } = useSetting(settingKey)
  const setSetting = useSetSetting(settingKey)
  const [draft, setDraft] = useState<string | null>(null)
  const value = draft ?? data?.value ?? ''

  return (
    <div className="grid gap-1.5">
      <Label htmlFor={settingKey}>{label}</Label>
      <p className="text-xs text-muted-foreground">{help}</p>
      <Textarea id={settingKey} rows={3} className="font-mono text-xs" value={value} onChange={(e) => setDraft(e.target.value)} />
      <button
        type="button"
        className="w-fit text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground"
        onClick={() =>
          setSetting.mutate(value, {
            onSuccess: () => {
              toast.success(savedMessage)
              setDraft(null)
            },
            onError: (error) => toast.error(t('common.saveFailed', { message: error.message })),
          })
        }
      >
        {saveLabel}
      </button>
    </div>
  )
}

// Gli host che vogliono una API key (gli altri caricano anonimi).
const KEYED_HOSTS = [
  { key: 'ptpimg', label: 'PTPImg', url: 'https://ptpimg.me' },
  { key: 'imgbb', label: 'ImgBB', url: 'https://api.imgbb.com' },
  { key: 'lensdump', label: 'Lensdump', url: 'https://lensdump.com' },
  { key: 'ptscreens', label: 'PTScreens', url: 'https://ptscreens.com' },
  { key: 'onlyimage', label: 'OnlyImage', url: 'https://onlyimage.org' },
  { key: 'dalexni', label: 'Dalexni', url: 'https://dalexni.com' },
  { key: 'utppm', label: 'utp.pm', url: 'https://utp.pm' },
  { key: 'seedpool_cdn', label: 'Seedpool CDN', url: 'https://i.seedpool.org' },
]

// Settings > Upload > Images: dove vanno gli screenshot e come si fanno.
export function UploadImagesSection() {
  const { data: priority } = useSetting('image_host_priority')
  const enabled = parseOrder(priority?.value)
  return (
    <>
      {/* A tutta larghezza: priorità e API key affiancate. */}
      <Card data-masonry="full" data-tour="upload.image-hosts">
        <CardHeader>
          <CardTitle>{t('uploadSettings.imageHostsTitle')}</CardTitle>
          <CardDescription>{t('uploadSettings.imageHostsDescription')}</CardDescription>
        </CardHeader>
        {/* content-start: le chiavi restano in cima con la loro spaziatura,
            non si allargano all'altezza della colonna delle priorità. */}
        <CardContent className="grid items-start gap-6 md:grid-cols-2">
          <ImageHostPriorityField />
          <div className="grid content-start gap-2">
            <div className="grid gap-1.5">
              <Label>{t('uploadSettings.apiKeysLabel')}</Label>
              <p className="text-xs text-muted-foreground">{t('uploadSettings.apiKeysHelp')}</p>
            </div>
            {/* Solo gli host attivi nella priorità: una chiave di un host spento
                resta salvata, solo nascosta finché non lo riattivi. */}
            {KEYED_HOSTS.filter((host) => enabled.includes(host.key)).map((host) => (
              <SettingField
                key={host.key}
                compact
                settingKey={`image_host_${host.key}_api_key`}
                label={host.label}
                description={host.url}
                type="password"
              />
            ))}
          </div>
        </CardContent>
      </Card>

      <Card data-tour="upload.screenshots">
        <CardHeader>
          <CardTitle>{t('uploadSettings.screenshotsTitle')}</CardTitle>
          <CardDescription>{t('uploadSettings.screenshotsDescription')}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <SettingField
            settingKey="upload_screenshot_count"
            label={t('uploadSettings.screenshotCountLabel')}
            description={t('uploadSettings.screenshotCountDescription')}
            type="number"
            placeholder="4"
          />
          <TonemapSwitch />
        </CardContent>
      </Card>
    </>
  )
}

// Settings > Upload > Releases: le release del releaser, la descrizione e i
// nomi dei file nei torrent.
export function UploadReleasesSection() {
  return (
    <>
      {/* Le release del releaser: il suo nome e la cartella osservata (Storage). */}
      <Card data-tour="upload.releases">
        <CardHeader>
          <CardTitle>{t('uploadSettings.releasesTitle')}</CardTitle>
          <CardDescription>{t('uploadSettings.releasesDescription')}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <SettingField
            settingKey="upload_releaser_name"
            label={t('uploadSettings.releaserLabel')}
            description={t('uploadSettings.releaserDescription')}
            placeholder="NZG"
          />
          <SettingField
            settingKey="upload_auto_match_threshold"
            label={t('uploadSettings.autoMatchLabel')}
            description={t('uploadSettings.autoMatchDescription')}
            type="number"
            placeholder="0.9"
          />
        </CardContent>
      </Card>

      <Card data-tour="upload.description">
        <CardHeader>
          <CardTitle>{t('uploadSettings.descriptionTitle')}</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-6">
          <DescriptionTextField
            settingKey="upload_description_header"
            label={t('uploadSettings.descriptionHeaderLabel')}
            help={t('uploadSettings.descriptionHeaderHelp')}
            saveLabel={t('uploadSettings.saveHeaderButton')}
            savedMessage={t('uploadSettings.descriptionHeaderSaved')}
          />
          <DescriptionTextField
            settingKey="upload_description_signature"
            label={t('uploadSettings.signatureLabel')}
            help={t('uploadSettings.signatureHelp')}
            saveLabel={t('uploadSettings.saveSignatureButton')}
            savedMessage={t('uploadSettings.signatureSaved')}
          />
        </CardContent>
      </Card>
      <FileNamingCard />
    </>
  )
}
