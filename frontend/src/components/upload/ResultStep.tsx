import { CircleAlertIcon, CircleCheckIcon, ExternalLinkIcon, RotateCcwIcon, TriangleAlertIcon } from 'lucide-react'
import { toast } from 'sonner'

import { useRetrySeed, type UploadJob } from '@/api/hooks/uploads'
import { ExecutionSteps } from '@/components/upload/ExecutionSteps'
import { canRetrySeed, currentRunEvents } from '@/components/upload/jobState'
import { RetryUploadButton } from '@/components/upload/RetryUploadButton'
import { TargetWarning } from '@/components/upload/TargetWarning'
import { ActionBadge } from '@/components/upload/TrackerCheckCard'
import { UploadStatusBadge } from '@/components/upload/UploadStatusBadge'
import { Button } from '@/components/ui/button'
import { Card, CardAction, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { t } from '@/lib/i18n'
import { eventMessage, executionSteps } from '@/lib/upload'
import { safeHref } from '@/lib/safeUrl'

// Esito finale, tracker per tracker: cosa è stato fatto, il link al
// torrent sul tracker e, se qualcosa è andato storto, perché (l'ultimo
// errore del registro eventi per quel tracker). Pubblicato ma non in seed:
// "Riprova il seed" rifà solo l'aggiunta al client, o dopo un recheck fallito
// (anche di un reseed) ne chiede un altro (canRetrySeed); "Riprova" in alto
// rimette in coda i tracker falliti prima di pubblicare.

export function ResultStep({ job }: { job: UploadJob }) {
  const retrySeed = useRetrySeed(job.id)
  const lastError = (targetId: number) =>
    [...job.events].reverse().find((event) => event.target_id === targetId && event.level === 'error')
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          {job.status === 'done' ? (
            <CircleCheckIcon className="size-5 text-emerald-500" />
          ) : (
            <TriangleAlertIcon className="size-5 text-amber-500" />
          )}
          {t(`upload.result.${job.status}`)}
        </CardTitle>
        <CardAction>
          <RetryUploadButton job={job} />
        </CardAction>
      </CardHeader>
      <CardContent className="grid gap-3">
        <ExecutionSteps steps={executionSteps({ ...job, events: currentRunEvents(job.events) })} />
        {job.targets.map((target) => {
          const error = lastError(target.id)
          return (
            <div key={target.id} className="grid gap-1 rounded-md border p-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{target.tracker_label}</span>
                {target.action && <ActionBadge action={target.action} />}
                <UploadStatusBadge status={target.status} />
                {target.remote_url && (
                  <a
                    href={safeHref(target.remote_url)}
                    target="_blank"
                    rel="noreferrer"
                    className="ml-auto inline-flex items-center gap-1 text-xs hover:underline"
                  >
                    {t('upload.result.openOnTracker')}
                    <ExternalLinkIcon className="size-3" />
                  </a>
                )}
              </div>
              {target.approved_name && <p className="font-mono text-xs break-all">{target.approved_name}</p>}
              {target.status === 'done' && target.error_message && <TargetWarning code={target.error_message} />}
              {canRetrySeed(target) && (
                <Button
                  variant="outline"
                  size="sm"
                  className="w-fit"
                  disabled={retrySeed.isPending}
                  onClick={() =>
                    retrySeed.mutate(target.id, {
                      // Dopo un recheck fallito il torrent è ancora nel client: se ne chiede un altro.
                      onSuccess: () => toast.success(t(target.error_message === 'seed_recheck_failed'
                        ? 'upload.result.recheckRetried' : 'upload.result.seedRetried')),
                      onError: (e) => toast.error(e.message),
                    })
                  }
                >
                  <RotateCcwIcon className="size-4" />
                  {t('upload.result.retrySeed')}
                </Button>
              )}
              {target.status === 'failed' && (
                <p className="flex items-start gap-1.5 text-xs text-red-600 dark:text-red-400">
                  <CircleAlertIcon className="mt-0.5 size-3.5 shrink-0" />
                  {error ? eventMessage(error) : target.error_message}
                </p>
              )}
            </div>
          )
        })}
      </CardContent>
    </Card>
  )
}
