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
// resolver): i segreti non tornano mai, solo quali sono impostati. I servizi
// di notifica hanno le loro istanze (hooks/notifications.ts).
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

// Accende o spegne un plugin, nativo o installato, senza riavviare: i suoi
// adapter entrano o escono dal registro (un host di immagini dalla catena).
export function useSetPluginEnabled(name: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (enabled: boolean) =>
      unwrap(api.PUT('/api/plugins/{name}/enabled', { params: { path: { name } }, body: { enabled } })),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['plugins'] })
      queryClient.invalidateQueries({ queryKey: ['uploads', 'image-hosts'] })
    },
  })
}
