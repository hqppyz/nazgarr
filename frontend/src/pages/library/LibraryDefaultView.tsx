import { Navigate } from 'react-router-dom'

import { useSetting } from '@/api/hooks/settings'
import { t } from '@/lib/i18n'
import { LIBRARY_VIEW_PATHS, LIBRARY_VIEW_SETTING, libraryViewOf } from '@/lib/library-view'

// /library: la vista scelta in Configuration > Interface (Folder di default).
export function LibraryDefaultView() {
  const { data, isPending } = useSetting(LIBRARY_VIEW_SETTING)
  if (isPending) return <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
  return <Navigate to={LIBRARY_VIEW_PATHS[libraryViewOf(data?.value)]} replace />
}
