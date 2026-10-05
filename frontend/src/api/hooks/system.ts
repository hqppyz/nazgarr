import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap } from '@/api/client'

export function useAppInfo() {
  return useQuery({
    queryKey: ['system', 'info'],
    queryFn: () => unwrap(api.GET('/api/system/info')),
  })
}

export function useUpdateCheck(enabled: boolean) {
  return useQuery({
    queryKey: ['system', 'update-check'],
    queryFn: () => unwrap(api.GET('/api/system/update-check')),
    enabled,
    staleTime: 0,
  })
}

export function useLogs(minLevel: string) {
  return useQuery({
    queryKey: ['system', 'logs', minLevel],
    queryFn: () => unwrap(api.GET('/api/system/logs', { params: { query: { min_level: minLevel } } })),
    refetchInterval: 10_000,
  })
}

// L'ultimo esito del controllo aggiornamenti salvato dal backend (manuale o
// automatico): niente chiamate a GitHub, solo per l'avviso nella barra laterale.
export function useUpdateStatus() {
  return useQuery({
    queryKey: ['system', 'update-status'],
    queryFn: () => unwrap(api.GET('/api/system/update-status')),
    staleTime: 30 * 60_000,
  })
}

// Le note delle versioni arrivate dall'ultima vista (dopo un aggiornamento).
export function useReleaseNotes() {
  return useQuery({
    queryKey: ['system', 'release-notes'],
    queryFn: () => unwrap(api.GET('/api/system/release-notes')),
    staleTime: Infinity,
  })
}

export function useMarkReleaseNotesSeen() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.POST('/api/system/release-notes/seen')),
    onSuccess: () => queryClient.setQueryData(['system', 'release-notes'], (old: { current_version: string } | undefined) =>
      old ? { ...old, entries: [] } : old),
  })
}
