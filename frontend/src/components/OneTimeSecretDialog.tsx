import { CheckIcon, CopyIcon } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { toast } from 'sonner'

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
  const [copied, setCopied] = useState(false)
  return (
    <Dialog
      open={secret !== null}
      onOpenChange={(open) => {
        if (!open) {
          setCopied(false)
          onClose()
        }
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <div className="flex items-center gap-2">
          <code className="min-w-0 flex-1 rounded-md bg-muted px-3 py-2 font-mono text-xs break-all">{secret}</code>
          <Button
            variant="outline"
            size="icon-sm"
            title={t('security.apiKeyCopy')}
            onClick={() =>
              secret &&
              navigator.clipboard.writeText(secret).then(
                () => setCopied(true),
                () => toast.error(t('security.apiKeyCopyFailed')),
              )
            }
          >
            {copied ? <CheckIcon className="size-4" /> : <CopyIcon className="size-4" />}
          </Button>
        </div>
        {children}
        <DialogFooter>
          <Button
            onClick={() => {
              setCopied(false)
              onClose()
            }}
          >
            {t('security.apiKeyDone')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
