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
import { ImageHostsCard } from '@/pages/config/ImageHostsCard'
import { autosaveFeedback } from '@/lib/autosave'

function TonemapSwitch() {
  const { data } = useSetting('upload_tonemap_hdr')
  const setSetting = useSetSetting('upload_tonemap_hdr')
  const checked = data?.value === 'true'

  return (
    <div className="flex items-center justify-between gap-3">
      <div className="grid min-w-0 gap-0.5">
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

// Settings > Upload > Images: dove vanno gli screenshot e come si fanno.
export function UploadImagesSection() {
  return (
    <>
      <ImageHostsCard />

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
