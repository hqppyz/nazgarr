import { type ReactNode } from 'react'

import { CopyButton } from '@/components/CopyButton'
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

// Un segreto che Nazgarr mostra una volta sola (API key, segreto di un
// webhook): da copiare subito.
export function OneTimeSecretDialog({
  secret,
  title,
  description,
  onClose,
  children,
}: {
  secret: string | null
  title: string
  description: string
  onClose: () => void
  children?: ReactNode
}) {
  return (
    <Dialog
      open={secret !== null}
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <div className="flex items-center gap-2">
          <code className="min-w-0 flex-1 rounded-md bg-muted px-3 py-2 font-mono text-xs break-all">{secret}</code>
          <CopyButton text={secret} label={t('security.apiKeyCopy')} failMessage={t('security.apiKeyCopyFailed')} />
        </div>
        {children}
        <DialogFooter>
          <Button onClick={onClose}>
            {t('security.apiKeyDone')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
