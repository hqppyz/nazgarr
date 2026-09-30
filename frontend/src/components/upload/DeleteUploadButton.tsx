import { useState } from 'react'
import { toast } from 'sonner'

import { useDeleteUpload } from '@/api/hooks/uploads'
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

const DESTRUCTIVE = 'bg-destructive text-white hover:bg-destructive/90'

// Elimina un upload, sempre con la conferma; onDeleted decide dove andare
// dopo (la coda dalla pagina del job, niente dal drawer dello storico).
export function DeleteUploadButton({ uploadId, onDeleted }: { uploadId: number; onDeleted: () => void }) {
  const remove = useDeleteUpload()
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button className={DESTRUCTIVE} disabled={remove.isPending} onClick={() => setOpen(true)}>
        {t('upload.deleteJob')}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('upload.deleteConfirmTitle')}</DialogTitle>
            <DialogDescription>{t('upload.deleteConfirmDescription')}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button
              className={DESTRUCTIVE}
              disabled={remove.isPending}
              onClick={() =>
                remove
                  .mutateAsync(uploadId)
                  .then(() => {
                    setOpen(false)
                    onDeleted()
                  })
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
