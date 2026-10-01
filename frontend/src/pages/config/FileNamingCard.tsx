import { useState } from 'react'

import { useFileNaming, useFileNamingPreview, useSaveFileNaming } from '@/api/hooks/uploads'
import { NamingRulesEditor, type NamingRules } from '@/components/NamingRulesEditor'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { autosaveFeedback } from '@/lib/autosave'
import { t } from '@/lib/i18n'

// Il pattern dei nomi dei file dentro il torrent, quando non si usano quelli
// del torrent in hardlink (app/upload_file_names.py): un nome a punti, come
// le release.
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
    <Card data-masonry="full">
      <CardHeader>
        <CardTitle>{t('uploadSettings.fileNamesTitle')}</CardTitle>
        <CardDescription>{t('uploadSettings.fileNamesDescription')}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
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
