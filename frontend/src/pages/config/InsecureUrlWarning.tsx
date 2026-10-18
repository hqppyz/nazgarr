import { TriangleAlertIcon } from 'lucide-react'

import { t } from '@/lib/i18n'
import { cn } from '@/lib/utils'

// http:// verso un host pubblico: si salva, ma i segreti viaggiano in chiaro
// (decisione dell'utente, 2026-10-18). kind sceglie quali segreti nominare.
export function InsecureUrlWarning({ kind, className }: { kind: 'tracker' | 'client' | 'arr'; className?: string }) {
  return (
    <p role="note" className={cn('flex items-start gap-1.5 text-xs text-amber-700 dark:text-amber-300', className)}>
      <TriangleAlertIcon className="mt-0.5 size-3.5 shrink-0" aria-hidden />
      <span>{t(`config.insecureUrl.${kind}`)}</span>
    </p>
  )
}
