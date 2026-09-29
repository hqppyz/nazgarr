import { useLocation, useNavigate } from 'react-router-dom'

import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { t } from '@/lib/i18n'
import { LIBRARY_VIEW_PATHS, type LibraryView } from '@/lib/library-view'

// Poster | Folder in cima alle due viste della libreria, come Movie/TV.
export function LibraryViewSwitch() {
  const location = useLocation()
  const navigate = useNavigate()
  const current: LibraryView = location.pathname.startsWith(LIBRARY_VIEW_PATHS.poster) ? 'poster' : 'folder'
  return (
    <Tabs value={current} onValueChange={(v) => navigate(LIBRARY_VIEW_PATHS[v as LibraryView])}>
      <TabsList>
        <TabsTrigger value="folder">{t('library.folderView')}</TabsTrigger>
        <TabsTrigger value="poster">{t('library.posterView')}</TabsTrigger>
      </TabsList>
    </Tabs>
  )
}
