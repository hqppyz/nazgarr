import { CheckIcon, CopyIcon } from 'lucide-react'
import { useEffect, useRef, useState, type ComponentProps, type ReactNode } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { copyText } from '@/lib/clipboard'
import { t } from '@/lib/i18n'

// Il tasto "copia" di tutta l'app: negli appunti anche su http:// in LAN e
// dentro un dialog (lib/clipboard.ts), la spunta per un attimo se è andata,
// un avviso con cosa fare a mano se no. children: un'etichetta accanto
// all'icona; label: il nome per lettori di schermo e tooltip.
export function CopyButton({
  text,
  label,
  successMessage,
  failMessage,
  children,
  variant = 'outline',
  size = 'icon-sm',
  disabled,
  ...props
}: Omit<ComponentProps<typeof Button>, 'onClick' | 'children'> & {
  text: string | null | undefined
  label?: string
  successMessage?: string
  failMessage?: string
  children?: ReactNode
}) {
  const [copied, setCopied] = useState(false)
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(timer.current), [])
  const name = label ?? t('common.copy')

  return (
    <Button
      variant={variant}
      size={size}
      title={name}
      aria-label={name}
      disabled={disabled || !text}
      {...props}
      onClick={(event) => {
        if (!text) return
        void copyText(text, event.currentTarget).then((ok) => {
          if (!ok) {
            toast.error(failMessage ?? t('common.copyFailed'))
            return
          }
          if (successMessage) toast.success(successMessage)
          setCopied(true)
          window.clearTimeout(timer.current)
          timer.current = window.setTimeout(() => setCopied(false), 1500)
        })
      }}
    >
      {copied ? <CheckIcon className="size-4" /> : <CopyIcon className="size-4" />}
      {children}
    </Button>
  )
}
