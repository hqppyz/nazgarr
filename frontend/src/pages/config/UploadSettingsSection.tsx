import { useState } from 'react'
import { toast } from 'sonner'

import { useSetSetting, useSetting } from '@/api/hooks/settings'
import { SettingField } from '@/components/SettingField'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { t } from '@/lib/i18n'
import { ImageHostPriorityField } from '@/pages/config/ImageHostPriorityField'
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
// l'intestazione in cima, la firma in fondo (app/upload.py prepare).
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

export function UploadSettingsSection() {
  return (
    <>
      <Card>
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

      <Card>
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

      {/* A tutta larghezza sotto le due colonne: priorità e API key affiancate. */}
      <Card data-masonry="full">
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
            <SettingField compact settingKey="image_host_ptpimg_api_key" label="PTPImg" description="https://ptpimg.me" type="password" />
            <SettingField compact settingKey="image_host_imgbb_api_key" label="ImgBB" description="https://api.imgbb.com" type="password" />
            <SettingField compact settingKey="image_host_lensdump_api_key" label="Lensdump" description="https://lensdump.com" type="password" />
            <SettingField compact settingKey="image_host_ptscreens_api_key" label="PTScreens" description="https://ptscreens.com" type="password" />
            <SettingField compact settingKey="image_host_onlyimage_api_key" label="OnlyImage" description="https://onlyimage.org" type="password" />
            <SettingField compact settingKey="image_host_dalexni_api_key" label="Dalexni" description="https://dalexni.com" type="password" />
            <SettingField compact settingKey="image_host_utppm_api_key" label="utp.pm" description="https://utp.pm" type="password" />
            <SettingField compact settingKey="image_host_seedpool_cdn_api_key" label="Seedpool CDN" description="https://i.seedpool.org" type="password" />
          </div>
        </CardContent>
      </Card>
    </>
  )
}
