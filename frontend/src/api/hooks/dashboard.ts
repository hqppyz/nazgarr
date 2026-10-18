import { useQuery } from '@tanstack/react-query'

import { api, unwrap } from '@/api/client'
import { useTrackerFilter } from '@/lib/trackerFilter'

// refetchInterval: la dashboard ogni 15 s; chi ne mostra solo due numeri
// su ogni pagina (il piè della sidebar) può chiederla più di rado.
export function useDashboard(refetchInterval = 15_000) {
  const tracker = useTrackerFilter()
  return useQuery({
    queryKey: ['dashboard', tracker],
    queryFn: () => unwrap(api.GET('/api/dashboard', { params: { query: { tracker } } })),
    refetchInterval,
  })
}

// days: finestra 7/30/90 giorni della dashboard; null = tutto lo storico.
export function useDashboardHistory(days: number | null) {
  const tracker = useTrackerFilter()
  return useQuery({
    queryKey: ['dashboard', 'history', days, tracker],
    queryFn: () =>
      unwrap(
        api.GET('/api/dashboard/history', {
          params: { query: days == null ? { limit: 1000, tracker } : { days, tracker } },
        }),
      ),
  })
}

export function useDashboardChanges() {
  return useQuery({
    queryKey: ['dashboard', 'changes'],
    queryFn: () => unwrap(api.GET('/api/dashboard/changes')),
    refetchInterval: 60_000,
  })
}
