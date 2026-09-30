import { useQuery } from '@tanstack/react-query'

import { api, unwrap } from '@/api/client'

// Plugin caricati e adapter disponibili (integrati e dei plugin).
export function usePlugins() {
  return useQuery({
    queryKey: ['plugins'],
    queryFn: () => unwrap(api.GET('/api/plugins')),
    staleTime: 60_000,
  })
}
