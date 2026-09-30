import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import { useCancelUpload, useDeleteUpload, WORKER_STATES, type UploadJob } from '@/api/hooks/uploads'
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

const FINAL_STATES = ['done', 'partial', 'failed', 'cancelled']

// Annulla (torna allo storico) ed elimina (con conferma, torna alla coda).
export function JobActions({ job }: { job: UploadJob }) {
  const navigate = useNavigate()
  const cancel = useCancelUpload()
  const remove = useDeleteUpload()
  const [confirmDelete, setConfirmDelete] = useState(false)
  const final = FINAL_STATES.includes(job.status)
  const working = WORKER_STATES.includes(job.status)
  return (
    <>
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
        {!working && (
          <Button
            className="bg-destructive text-white hover:bg-destructive/90"
            disabled={remove.isPending}
            onClick={() => setConfirmDelete(true)}
          >
            {t('upload.deleteJob')}
          </Button>
        )}
      </div>
      <Dialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('upload.deleteConfirmTitle')}</DialogTitle>
            <DialogDescription>{t('upload.deleteConfirmDescription')}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setConfirmDelete(false)}>
              {t('common.cancel')}
            </Button>
            <Button
              className="bg-destructive text-white hover:bg-destructive/90"
              disabled={remove.isPending}
              onClick={() =>
                remove
                  .mutateAsync(job.id)
                  .then(() => navigate('/upload'))
                  .catch((error: Error) => toast.error(error.message))
              }
            >
              {t('upload.deleteJob')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
