import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap } from '@/api/client'
import type { Schemas } from '@/api/client'

export function useRadarrInstances() {
  return useQuery({
    queryKey: ['radarr-instances'],
    queryFn: () => unwrap(api.GET('/api/radarr-instances')),
  })
}

export function useCreateRadarrInstance() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['RadarrInstanceCreateRequest']) => unwrap(api.POST('/api/radarr-instances', { body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['radarr-instances'] }),
  })
}

export function useUpdateRadarrInstance() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: Schemas['RadarrInstanceUpdateRequest'] }) =>
      unwrap(api.PATCH('/api/radarr-instances/{instance_id}', { params: { path: { instance_id: id } }, body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['radarr-instances'] }),
  })
}

export function useDeleteRadarrInstance() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      unwrap(api.DELETE('/api/radarr-instances/{instance_id}', { params: { path: { instance_id: id } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['radarr-instances'] }),
  })
}

export function useTestRadarrInstance() {
  return useMutation({
    mutationFn: (id: number) =>
      unwrap(api.POST('/api/radarr-instances/{instance_id}/test', { params: { path: { instance_id: id } } })),
  })
}

// Senza instance_id: usata dal dialog "Add instance" per testare prima
// ancora di salvare, con i valori appena digitati nel form.
export function useTestRadarrConnection() {
  return useMutation({
    mutationFn: (body: Schemas['RadarrConnectionTestRequest']) =>
      unwrap(api.POST('/api/radarr-instances/test', { body })),
  })
}

export function useSonarrInstances() {
  return useQuery({
    queryKey: ['sonarr-instances'],
    queryFn: () => unwrap(api.GET('/api/sonarr-instances')),
  })
}

export function useCreateSonarrInstance() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['SonarrInstanceCreateRequest']) => unwrap(api.POST('/api/sonarr-instances', { body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['sonarr-instances'] }),
  })
}

export function useUpdateSonarrInstance() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: Schemas['SonarrInstanceUpdateRequest'] }) =>
      unwrap(api.PATCH('/api/sonarr-instances/{instance_id}', { params: { path: { instance_id: id } }, body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['sonarr-instances'] }),
  })
}

export function useDeleteSonarrInstance() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      unwrap(api.DELETE('/api/sonarr-instances/{instance_id}', { params: { path: { instance_id: id } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['sonarr-instances'] }),
  })
}

export function useTestSonarrInstance() {
  return useMutation({
    mutationFn: (id: number) =>
      unwrap(api.POST('/api/sonarr-instances/{instance_id}/test', { params: { path: { instance_id: id } } })),
  })
}

// Senza instance_id: usata dal dialog "Add instance" per testare prima
// ancora di salvare, con i valori appena digitati nel form.
export function useTestSonarrConnection() {
  return useMutation({
    mutationFn: (body: Schemas['SonarrConnectionTestRequest']) =>
      unwrap(api.POST('/api/sonarr-instances/test', { body })),
  })
}

// Webhook di Radarr/Sonarr (nazgarr/integrations/arr_webhooks.py): la password si
// vede solo quando la si crea o la si rigenera.
export type ArrKind = 'radarr' | 'sonarr'

export function useSetupArrWebhook(kind: ArrKind) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      kind === 'radarr'
        ? unwrap(api.POST('/api/radarr-instances/{instance_id}/webhook', { params: { path: { instance_id: id } } }))
        : unwrap(api.POST('/api/sonarr-instances/{instance_id}/webhook', { params: { path: { instance_id: id } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [`${kind}-instances`] }),
  })
}

export function useRemoveArrWebhook(kind: ArrKind) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      kind === 'radarr'
        ? unwrap(api.DELETE('/api/radarr-instances/{instance_id}/webhook', { params: { path: { instance_id: id } } }))
        : unwrap(api.DELETE('/api/sonarr-instances/{instance_id}/webhook', { params: { path: { instance_id: id } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [`${kind}-instances`] }),
  })
}
