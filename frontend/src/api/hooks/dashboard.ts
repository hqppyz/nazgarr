import { useQuery } from '@tanstack/react-query'

import { api, unwrap } from '@/api/client'

export function useDashboard() {
  return useQuery({
    queryKey: ['dashboard'],
    queryFn: () => unwrap(api.GET('/api/dashboard')),
    refetchInterval: 15_000,
  })
}

// days: finestra 7/30/90 giorni della dashboard; null = tutto lo storico.
export function useDashboardHistory(days: number | null) {
  return useQuery({
    queryKey: ['dashboard', 'history', days],
    queryFn: () =>
      unwrap(
        api.GET('/api/dashboard/history', {
          params: { query: days == null ? { limit: 1000 } : { days } },
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
