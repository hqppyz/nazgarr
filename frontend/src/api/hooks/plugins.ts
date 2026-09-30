import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap } from '@/api/client'

// Plugin caricati e adapter disponibili (integrati e dei plugin).
export function usePlugins() {
  return useQuery({
    queryKey: ['plugins'],
    queryFn: () => unwrap(api.GET('/api/plugins')),
    staleTime: 60_000,
  })
}

// Configurazione di un adapter globale di un plugin (host di immagini,
// resolver, notifiche): i segreti non tornano mai, solo quali sono impostati.
export function useAdapterConfig(kind: string, adapterType: string) {
  return useQuery({
    queryKey: ['plugins', 'config', kind, adapterType],
    queryFn: () =>
      unwrap(api.GET('/api/plugins/config/{kind}/{adapter_type}', { params: { path: { kind, adapter_type: adapterType } } })),
  })
}

export function useSaveAdapterConfig(kind: string, adapterType: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { enabled?: boolean; config?: Record<string, unknown> }) =>
      unwrap(
        api.PUT('/api/plugins/config/{kind}/{adapter_type}', { params: { path: { kind, adapter_type: adapterType } }, body }),
      ),
    onSuccess: (data) => queryClient.setQueryData(['plugins', 'config', kind, adapterType], data),
  })
}
