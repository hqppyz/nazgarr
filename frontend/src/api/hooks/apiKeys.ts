import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap } from '@/api/client'

export function useApiKeys() {
  return useQuery({ queryKey: ['api-keys'], queryFn: () => unwrap(api.GET('/api/api-keys')) })
}

// La risposta contiene la chiave in chiaro: l'unica volta che si vede.
export function useCreateApiKey() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { name: string; level: 'read' | 'write' }) => unwrap(api.POST('/api/api-keys', { body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['api-keys'] }),
  })
}

export function useRevokeApiKey() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => unwrap(api.POST('/api/api-keys/{key_id}/revoke', { params: { path: { key_id: id } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['api-keys'] }),
  })
}
