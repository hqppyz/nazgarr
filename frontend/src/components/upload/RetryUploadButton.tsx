import { RotateCwIcon, TriangleAlertIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { useRetryUpload, type UploadJob } from '@/api/hooks/uploads'
import { needsConfirmation, retryableTargets } from '@/components/upload/jobState'
import { ActionBadge } from '@/components/upload/TrackerCheckCard'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { t } from '@/lib/i18n'

// "Riprova" su un upload fallito o fatto a metà (richiesta dell'utente,
// 2026-10-18): i tracker falliti prima di pubblicare tornano in coda con la
// decisione di allora, senza ripassare dal match. La conferma dice quali; un
// invio interrotto (non si sa se il tracker l'ha ricevuto) chiede prima di
// controllare sul tracker.
export function RetryUploadButton({ job, size = 'sm' }: { job: UploadJob; size?: 'sm' | 'default' }) {
  const retry = useRetryUpload(job.id)
  const [open, setOpen] = useState(false)
  const targets = retryableTargets(job)
  if (targets.length === 0) return null
  const unsure = targets.filter(needsConfirmation)

  function send() {
    retry
      .mutateAsync(unsure.length > 0)
      .then(() => {
        setOpen(false)
        toast.success(t('upload.retry.queued'))
      })
      .catch((error: Error) => toast.error(error.message))
  }

  return (
    <>
      <Button variant="outline" size={size} disabled={retry.isPending} onClick={() => setOpen(true)}>
        <RotateCwIcon className="size-4" />
        {t('upload.retry.button')}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('upload.retry.title')}</DialogTitle>
            <DialogDescription>{t('upload.retry.description')}</DialogDescription>
          </DialogHeader>
          <ul className="grid gap-1.5 text-sm">
            {targets.map((target) => (
              <li key={target.id} className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{target.tracker_label}</span>
                {target.action && <ActionBadge action={target.action} />}
                {target.action === 'upload' && target.approved_name && (
                  <span className="min-w-0 truncate font-mono text-xs text-muted-foreground">{target.approved_name}</span>
                )}
              </li>
            ))}
          </ul>
          {unsure.length > 0 && (
            <p
              role="alert"
              className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-xs text-amber-700 dark:text-amber-300"
            >
              <TriangleAlertIcon className="mt-0.5 size-3.5 shrink-0" />
              {t('upload.retry.interrupted', { trackers: unsure.map((target) => target.tracker_label).join(', ') })}
            </p>
          )}
          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button disabled={retry.isPending} onClick={send}>
              {unsure.length > 0 ? t('upload.retry.confirmInterrupted') : t('upload.retry.confirm')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
