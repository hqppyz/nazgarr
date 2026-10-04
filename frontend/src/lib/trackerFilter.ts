import { useSetting } from '@/api/hooks/settings'

// Filtro per tracker delle viste (nazgarr/torrents/tracker_scope.py): "all", "configured"
// o l'id di un tracker. È un'impostazione, quindi resta quella scelta.
export const TRACKER_FILTER_SETTING = 'tracker_filter'

export function useTrackerFilter(): string {
  const { data } = useSetting(TRACKER_FILTER_SETTING)
  return data?.value || 'all'
}

// Le pagine a cui il filtro si applica.
export function usesTrackerFilter(pathname: string): boolean {
  return pathname === '/dashboard' || pathname.startsWith('/library') || pathname.startsWith('/torrent')
}
