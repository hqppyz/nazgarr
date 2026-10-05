import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap } from '@/api/client'
import type { Schemas } from '@/api/client'

export type NotificationService = Schemas['NotificationServiceResponse']

// I servizi di notifica: istanze di Discord, Telegram o di un plugin, quante
// se ne vuole per tipo. I segreti non tornano mai, solo quali sono impostati.
export function useNotificationServices() {
  return useQuery({ queryKey: ['notifications'], queryFn: () => unwrap(api.GET('/api/notifications')) })
}

function useInvalidate() {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries({ queryKey: ['notifications'] })
}

export function useCreateNotificationService() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: (body: Schemas['NotificationServiceRequest']) => unwrap(api.POST('/api/notifications', { body })),
    onSuccess: invalidate,
  })
}

export function useUpdateNotificationService() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: Schemas['NotificationServiceRequest'] }) =>
      unwrap(api.PATCH('/api/notifications/{service_id}', { params: { path: { service_id: id } }, body })),
    onSuccess: invalidate,
  })
}

export function useDeleteNotificationService() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: (id: number) =>
      unwrap(api.DELETE('/api/notifications/{service_id}', { params: { path: { service_id: id } } })),
    onSuccess: invalidate,
  })
}

// La prova di un servizio salvato: passa dalla coda e resta nello storico.
export function useTestNotificationService() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: (id: number) =>
      unwrap(api.POST('/api/notifications/{service_id}/test', { params: { path: { service_id: id } } })),
    onSuccess: invalidate,
  })
}

// La prova dalla modale, con i valori non ancora salvati.
export function useTestUnsavedNotification() {
  return useMutation({
    mutationFn: (body: Schemas['NotificationTestRequest']) => unwrap(api.POST('/api/notifications/test', { body })),
  })
}

export function useNotificationDeliveries(id: number | null) {
  return useQuery({
    queryKey: ['notifications', id, 'deliveries'],
    queryFn: () =>
      unwrap(api.GET('/api/notifications/{service_id}/deliveries', { params: { path: { service_id: id! } } })),
    enabled: id !== null,
    refetchInterval: 10_000,
  })
}
