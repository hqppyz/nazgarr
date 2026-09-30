import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap } from '@/api/client'
import type { Schemas } from '@/api/client'

export type Webhook = Schemas['WebhookResponse']

export function useWebhookEvents() {
  return useQuery({ queryKey: ['webhooks', 'events'], queryFn: () => unwrap(api.GET('/api/webhooks/events')), staleTime: Infinity })
}

export function useWebhooks() {
  return useQuery({ queryKey: ['webhooks'], queryFn: () => unwrap(api.GET('/api/webhooks')) })
}

function useInvalidate() {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries({ queryKey: ['webhooks'] })
}

// La risposta di creazione e di rotazione contiene il segreto: l'unica volta.
export function useCreateWebhook() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: (body: Schemas['WebhookRequest']) => unwrap(api.POST('/api/webhooks', { body })),
    onSuccess: invalidate,
  })
}

export function useUpdateWebhook() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: Schemas['WebhookRequest'] }) =>
      unwrap(api.PATCH('/api/webhooks/{webhook_id}', { params: { path: { webhook_id: id } }, body })),
    onSuccess: invalidate,
  })
}

export function useRotateWebhookSecret() {
  return useMutation({
    mutationFn: (id: number) =>
      unwrap(api.POST('/api/webhooks/{webhook_id}/rotate-secret', { params: { path: { webhook_id: id } } })),
  })
}

export function useDeleteWebhook() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: (id: number) => unwrap(api.DELETE('/api/webhooks/{webhook_id}', { params: { path: { webhook_id: id } } })),
    onSuccess: invalidate,
  })
}

export function useTestWebhook() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => unwrap(api.POST('/api/webhooks/{webhook_id}/test', { params: { path: { webhook_id: id } } })),
    onSuccess: (_data, id) => {
      queryClient.invalidateQueries({ queryKey: ['webhooks'] })
      queryClient.invalidateQueries({ queryKey: ['webhooks', id, 'deliveries'] })
    },
  })
}

export function useWebhookDeliveries(id: number | null) {
  return useQuery({
    queryKey: ['webhooks', id, 'deliveries'],
    queryFn: () =>
      unwrap(api.GET('/api/webhooks/{webhook_id}/deliveries', { params: { path: { webhook_id: id! } } })),
    enabled: id !== null,
    refetchInterval: 10_000,
  })
}
