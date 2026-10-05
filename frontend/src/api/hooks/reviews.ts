import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap } from '@/api/client'
import { pushActivity, updateActivity } from '@/lib/activity'
import { trackVerification } from '@/lib/verification'
import { t } from '@/lib/i18n'

export function useReviews() {
  return useQuery({
    queryKey: ['reviews'],
    queryFn: () => unwrap(api.GET('/api/reviews')),
  })
}

export function useApproveReview() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => unwrap(api.POST('/api/reviews/{review_id}/approve', { params: { path: { review_id: id } } })),
    // Feedback in basso a destra: l'approvazione crea hardlink e aggiunge il
    // torrent al client, può durare qualche secondo; poi il recheck lo segue
    // SeedJobWatcher, che avvisa quando finisce.
    onMutate: () => ({ activityId: pushActivity({ status: 'running', title: t('activity.approving') }) }),
    onError: (error, _id, context) => {
      if (context) updateActivity(context.activityId, { status: 'error', title: t('activity.approveFailed'), detail: error.message })
    },
    onSuccess: (review, _id, context) => {
      if (context && review.verify_status === 'verifying' && review.verify_check_id) {
        // Prima il controllo completo: la notifica la aggiorna il watcher in
        // ActivityStack fino all'esito (ed eventuale aggiunta al client).
        updateActivity(context.activityId, { title: t('activity.verifyQueued'), detail: review.candidate_name, progress: 0 })
        trackVerification(review.verify_check_id, context.activityId)
      } else if (context) {
        const job = review.seed_job
        updateActivity(context.activityId, job?.final_status === 'failed'
          ? { status: 'error', title: t('activity.executionFailed'), detail: job.error_message ?? review.candidate_name }
          : job
            ? { status: 'success', title: t('activity.addedRecheckPending'), detail: review.candidate_name }
            : { status: 'info', title: t('activity.approvedNoClient'), detail: review.candidate_name })
      }
      queryClient.invalidateQueries({ queryKey: ['reviews'] })
      queryClient.invalidateQueries({ queryKey: ['reviews', 'failed'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      queryClient.invalidateQueries({ queryKey: ['library'] })
    },
  })
}

export function useRejectReview() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => unwrap(api.POST('/api/reviews/{review_id}/reject', { params: { path: { review_id: id } } })),
    onError: (error) => {
      pushActivity({ status: 'error', title: t('activity.rejectFailed'), detail: error.message })
    },
    onSuccess: (review) => {
      pushActivity({ status: 'info', title: t('activity.rejected'), detail: review.candidate_name })
      queryClient.invalidateQueries({ queryKey: ['reviews'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      queryClient.invalidateQueries({ queryKey: ['library'] })
    },
  })
}

export function useFailedSeedJobs() {
  return useQuery({
    queryKey: ['reviews', 'failed'],
    queryFn: () => unwrap(api.GET('/api/reviews/failed')),
  })
}

export function useRetryFailed() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (seedJobId: number) =>
      unwrap(api.POST('/api/reviews/failed/{seed_job_id}/retry', { params: { path: { seed_job_id: seedJobId } } })),
    // ['reviews'] copre anche l'elenco delle esecuzioni (seed-jobs/recent).
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['reviews'] }),
  })
}

export function useDeleteSeedJob() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (seedJobId: number) =>
      unwrap(api.DELETE('/api/reviews/seed-jobs/{seed_job_id}', { params: { path: { seed_job_id: seedJobId } } })),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reviews'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      queryClient.invalidateQueries({ queryKey: ['library'] })
    },
  })
}

export function useCandidateAudit(mediaItemId: number | null) {
  return useQuery({
    queryKey: ['reviews', 'candidates', mediaItemId],
    queryFn: () =>
      unwrap(api.GET('/api/reviews/candidates/{media_item_id}', { params: { path: { media_item_id: mediaItemId! } } })),
    enabled: mediaItemId !== null,
  })
}

export function useReconcileNow() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.POST('/api/reviews/seed-jobs/reconcile')),
    onMutate: () => ({ activityId: pushActivity({ status: 'running', title: t('activity.checkingRechecks') }) }),
    onError: (error, _v, context) => {
      if (context) updateActivity(context.activityId, { status: 'error', title: t('activity.checkFailed'), detail: error.message })
    },
    onSuccess: (result, _v, context) => {
      // L'esito dei singoli seed job lo annuncia SeedJobWatcher; qui solo il controllo.
      if (context) updateActivity(context.activityId, { status: 'info', title: t('activity.checked', { count: result.reconciled }) })
      queryClient.invalidateQueries({ queryKey: ['library'] })
      queryClient.invalidateQueries({ queryKey: ['reviews'] })
    },
  })
}

// Ultime esecuzioni, per SeedJobWatcher: ogni 10s mentre qualcuna è in
// attesa del recheck, altrimenti ogni minuto (un seed può partire anche
// da un'altra scheda o da una run).
export function useRecentSeedJobs() {
  return useQuery({
    queryKey: ['reviews', 'seed-jobs', 'recent'],
    // Le stesse 200 righe servono al watcher dei recheck e all'elenco
    // delle esecuzioni in Reseeding.
    queryFn: () => unwrap(api.GET('/api/reviews/seed-jobs/recent', { params: { query: { limit: 200 } } })),
    refetchInterval: (query) =>
      query.state.data?.some((job) => job.final_status === 'in_progress') ? 10_000 : 60_000,
  })
}

// Categoria e tag nel client scelti a mano per un reseed, come per un
// upload: null torna ai default del client, "" vuol dire nessuno.
export function useSetReviewClientLabels(reviewId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { client_category: string | null; client_tags: string | null }) =>
      unwrap(api.PUT('/api/reviews/{review_id}/client-labels', { params: { path: { review_id: reviewId } }, body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['reviews'] }),
  })
}
