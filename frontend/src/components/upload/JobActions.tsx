import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import { useCancelUpload, WORKER_STATES, type UploadJob } from '@/api/hooks/uploads'
import { DeleteUploadButton } from '@/components/upload/DeleteUploadButton'
import { Button } from '@/components/ui/button'
import { t } from '@/lib/i18n'

const FINAL_STATES = ['done', 'partial', 'failed', 'cancelled']

// Annulla (torna allo storico) ed elimina (con conferma, torna alla coda).
export function JobActions({ job }: { job: UploadJob }) {
  const navigate = useNavigate()
  const cancel = useCancelUpload()
  const final = FINAL_STATES.includes(job.status)
  const working = WORKER_STATES.includes(job.status)
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
      {!working && <DeleteUploadButton uploadId={job.id} onDeleted={() => navigate('/upload')} />}
    </div>
  )
}
