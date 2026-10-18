import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import { useCancelUpload, useResumeUpload, WORKER_STATES, type UploadJob } from '@/api/hooks/uploads'
import { DeleteUploadButton } from '@/components/upload/DeleteUploadButton'
import { isBusy } from '@/components/upload/jobState'
import { Button } from '@/components/ui/button'
import { t } from '@/lib/i18n'

const FINAL_STATES = ['done', 'partial', 'failed', 'cancelled']

// Annulla (torna allo storico), riprendi un annullato (da dove si era
// fermato) ed elimina (con conferma, torna alla coda).
export function JobActions({ job }: { job: UploadJob }) {
  const navigate = useNavigate()
  const cancel = useCancelUpload()
  const resume = useResumeUpload()
  const final = FINAL_STATES.includes(job.status)
  const working = WORKER_STATES.includes(job.status)
  // Annullato, ma con un tracker ancora in invio: né riprendere né eliminare finché non finisce.
  const busy = isBusy(job)
  return (
    <div className="flex shrink-0 gap-2">
      {!final && (
        <Button
          variant="outline"
          disabled={cancel.isPending}
          onClick={() =>
            cancel
              .mutateAsync(job.id)
              .then(() => navigate('/upload?tab=history'))
              .catch((error: Error) => toast.error(error.message))
          }
        >
          {t('upload.cancelJob')}
        </Button>
      )}
      {job.status === 'cancelled' && (
        <Button
          disabled={resume.isPending || busy}
          title={busy ? t('upload.busy') : undefined}
          onClick={() =>
            resume
              .mutateAsync(job.id)
              .then(() => toast.success(t('upload.resumed')))
              .catch((error: Error) => toast.error(error.message))
          }
        >
          {t('upload.resumeJob')}
        </Button>
      )}
      {!working && <DeleteUploadButton uploadId={job.id} busy={busy} onDeleted={() => navigate('/upload')} />}
    </div>
  )
}
