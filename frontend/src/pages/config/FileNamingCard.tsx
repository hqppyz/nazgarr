import { useState } from 'react'

import { useFileNaming, useFileNamingPreview, useSaveFileNaming } from '@/api/hooks/uploads'
import { NamingRulesEditor, type NamingRules } from '@/components/NamingRulesEditor'
import { useSetSetting, useSetting } from '@/api/hooks/settings'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { autosaveFeedback } from '@/lib/autosave'
import { t } from '@/lib/i18n'

// Il pattern dei nomi dei file dentro il torrent, quando non si usano quelli
// del torrent in hardlink (nazgarr/upload_file_names.py): un nome a punti, come
// le release.
// Acceso (default): il nome del torrent in hardlink, se no il pattern qui
// sotto per i file della libreria e le release della cartella osservata.
// Spento: ogni upload parte con i nomi originali (nazgarr/upload_file_names.py).
function AutoRenameSwitch() {
  const { data } = useSetting('upload_auto_rename')
  const save = useSetSetting('upload_auto_rename')
  const enabled = (data?.value ?? 'true').toLowerCase() !== 'false'
  return (
    <div className="flex items-start gap-3 rounded-md border p-3">
      <Switch
        id="upload-auto-rename"
        checked={enabled}
        disabled={save.isPending}
        onCheckedChange={(on) => save.mutate(on ? 'true' : 'false', autosaveFeedback(t('uploadSettings.autoRenameLabel')))}
        className="mt-0.5"
      />
      <div className="grid gap-1">
        <Label htmlFor="upload-auto-rename">{t('uploadSettings.autoRenameLabel')}</Label>
        <p className="text-xs text-muted-foreground">{t('uploadSettings.autoRenameHelp')}</p>
      </div>
    </div>
  )
}

export function FileNamingCard() {
  const { data } = useFileNaming()
  const save = useSaveFileNaming()
  const [draft, setDraft] = useState<NamingRules | null>(null)
  if (!data) return null
  const value = (draft ?? data.rules) as NamingRules
  const changed = draft !== null && JSON.stringify(draft) !== JSON.stringify(data.rules)
  const isDefault = JSON.stringify(value) === JSON.stringify(data.default)
  const feedback = autosaveFeedback(t('uploadSettings.fileNamesTitle'))

  return (
    <Card data-masonry="full" data-tour="upload.file-names">
      <CardHeader>
        <CardTitle>{t('uploadSettings.fileNamesTitle')}</CardTitle>
        <CardDescription>{t('uploadSettings.fileNamesDescription')}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <AutoRenameSwitch />
        <NamingRulesEditor value={value} onChange={setDraft} usePreview={useFileNamingPreview} forFileNames />
        <div className="flex flex-wrap justify-end gap-2">
          {!isDefault && (
            <Button variant="ghost" onClick={() => setDraft(data.default as NamingRules)}>
              {t('uploadSettings.fileNamesReset')}
            </Button>
          )}
          <Button
            disabled={!changed || save.isPending}
            onClick={() => save.mutate(value, { ...feedback, onSuccess: () => { setDraft(null); feedback.onSuccess() } })}
          >
            {t('common.save')}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
