import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap } from '@/api/client'
import type { Schemas } from '@/api/client'

export type UploadJob = Schemas['UploadJobDetail']
export type UploadJobSummary = Schemas['UploadJobSummary']
export type UploadTarget = Schemas['UploadTargetResponse']

// Stati in cui il worker sta lavorando (app/upload_jobs.py WORKER_STATES):
// solo lì serve il polling, a un punto di approvazione o a job finito no.
export const WORKER_STATES = ['identifying', 'analyzing', 'queued', 'running']
const POLL_MS = 2000

function isWorking(status: string | undefined) {
  return status !== undefined && WORKER_STATES.includes(status)
}

export function useUploads() {
  return useQuery({
    queryKey: ['uploads'],
    queryFn: () => unwrap(api.GET('/api/uploads')),
    refetchInterval: (query) => (query.state.data?.some((job) => isWorking(job.status)) ? POLL_MS : false),
  })
}

export function useUpload(uploadId: number | null) {
  return useQuery({
    queryKey: ['uploads', uploadId],
    queryFn: () => unwrap(api.GET('/api/uploads/{upload_id}', { params: { path: { upload_id: uploadId! } } })),
    enabled: uploadId !== null,
    refetchInterval: (query) => (isWorking(query.state.data?.status) ? POLL_MS : false),
  })
}

export function useCreateUpload() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['UploadCreateRequest']) => unwrap(api.POST('/api/uploads', { body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['uploads'] }),
  })
}

export function useCancelUpload() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (uploadId: number) =>
      unwrap(api.POST('/api/uploads/{upload_id}/cancel', { params: { path: { upload_id: uploadId } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['uploads'] }),
  })
}

export function useDeleteUpload() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (uploadId: number) =>
      unwrap(api.DELETE('/api/uploads/{upload_id}', { params: { path: { upload_id: uploadId } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['uploads'] }),
  })
}
