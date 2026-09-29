import { useSetSetting, useSetting } from '@/api/hooks/settings'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { autosaveFeedback } from '@/lib/autosave'
import { t } from '@/lib/i18n'
import { LIBRARY_VIEW_SETTING, libraryViewOf } from '@/lib/library-view'

export function InterfaceSection() {
  const { data } = useSetting(LIBRARY_VIEW_SETTING)
  const setSetting = useSetSetting(LIBRARY_VIEW_SETTING)
  const value = libraryViewOf(data?.value)

  return (
    <div className="grid max-w-xl gap-6">
      <Card>
        <CardHeader>
          <CardTitle>{t('interface.libraryViewTitle')}</CardTitle>
          <CardDescription>{t('interface.libraryViewDescription')}</CardDescription>
        </CardHeader>
        <CardContent>
          <Select
            value={value}
            onValueChange={(v) => setSetting.mutate(v as string, autosaveFeedback(t('interface.libraryViewTitle')))}
          >
            <SelectTrigger className="w-56">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="folder">{t('library.folderView')}</SelectItem>
              <SelectItem value="poster">{t('library.posterView')}</SelectItem>
            </SelectContent>
          </Select>
        </CardContent>
      </Card>
    </div>
  )
}
