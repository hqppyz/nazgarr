import { Navigate } from 'react-router-dom'

import { useSetting } from '@/api/hooks/settings'
import { LIBRARY_VIEW_PATHS, LIBRARY_VIEW_SETTING, libraryViewOf } from '@/lib/library-view'
import { RingLoader } from '@/components/RingLoader'

// /library: la vista scelta in Configuration > Interface (Folder di default).
export function LibraryDefaultView() {
  const { data, isPending } = useSetting(LIBRARY_VIEW_SETTING)
  if (isPending) return <RingLoader />
  return <Navigate to={LIBRARY_VIEW_PATHS[libraryViewOf(data?.value)]} replace />
}
