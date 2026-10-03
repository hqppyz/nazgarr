import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap, type Schemas } from '@/api/client'
import { getToken } from '@/lib/authToken'

export type Instance = Schemas['InstanceResponse']

// Le istanze registrate su questa (nazgarr/api/instances.py), con il loro
// stato (versione, chiave, compatibilità) se probe.
export function useInstances(probe = false) {
  return useQuery({
    queryKey: ['instances', probe],
    queryFn: () => unwrap(api.GET('/api/instances', { params: { query: { probe } } })),
    refetchInterval: probe ? 60_000 : false,
  })
}

function invalidate(queryClient: ReturnType<typeof useQueryClient>) {
  return queryClient.invalidateQueries({ queryKey: ['instances'] })
}

export function useCreateInstance() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['InstanceCreateRequest']) => unwrap(api.POST('/api/instances', { body })),
    onSuccess: () => invalidate(queryClient),
  })
}

export function useUpdateInstance() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: Schemas['InstanceUpdateRequest'] }) =>
      unwrap(api.PATCH('/api/instances/{instance_id}', { params: { path: { instance_id: id } }, body })),
    onSuccess: () => invalidate(queryClient),
  })
}

export function useDeleteInstance() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      unwrap(api.DELETE('/api/instances/{instance_id}', { params: { path: { instance_id: id } } })),
    onSuccess: () => invalidate(queryClient),
  })
}

export function useTestInstance() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      unwrap(api.POST('/api/instances/{instance_id}/test', { params: { path: { instance_id: id } } })),
    onSuccess: () => invalidate(queryClient),
  })
}

// Una chiamata in sola lettura a un'istanza precisa, qualunque sia quella
// che si sta guardando (la panoramica le guarda tutte insieme). id null =
// questa istanza.
async function getFrom<T>(id: number | null, path: string): Promise<T> {
  const token = getToken()
  const response = await fetch(id === null ? path : `/api/remote/${id}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!response.ok) throw new Error(String(response.status))
  return response.json() as Promise<T>
}

export interface InstanceSnapshot {
  dashboard: Schemas['DashboardResponse']
  uploads: { status: string }[]
  version: string
}

export function useInstanceSnapshot(id: number | null, enabled = true) {
  return useQuery({
    queryKey: ['instances', 'snapshot', id],
    enabled,
    refetchInterval: 60_000,
    queryFn: async (): Promise<InstanceSnapshot> => {
      const [dashboard, uploads, health] = await Promise.all([
        getFrom<Schemas['DashboardResponse']>(id, '/api/dashboard'),
        getFrom<{ status: string }[]>(id, '/api/uploads'),
        getFrom<{ version: string }>(id, '/api/health'),
      ])
      return { dashboard, uploads, version: health.version }
    },
  })
}
