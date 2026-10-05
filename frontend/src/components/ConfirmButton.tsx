import { useState, type ReactElement } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { t } from '@/lib/i18n'

// Un'azione da confermare (eliminare un client, un tracker, un disco...):
// il pulsante di sempre apre una conferma invece di agire subito. Su un
// telefono un tocco sbagliato non cancella più niente (2026-10-05).
export function ConfirmButton({
  trigger,
  title,
  description,
  confirmLabel = t('common.delete'),
  onConfirm,
  pending = false,
}: {
  trigger: ReactElement
  title: string
  description?: string
  confirmLabel?: string
  onConfirm: () => void
  pending?: boolean
}) {
  const [open, setOpen] = useState(false)
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={trigger} />
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="pr-6 break-words">{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>{t('common.cancel')}</Button>
          <Button
            className="bg-destructive text-white hover:bg-destructive/90"
            disabled={pending}
            onClick={() => {
              onConfirm()
              setOpen(false)
            }}
          >
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
