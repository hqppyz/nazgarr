import { ClockIcon, TriangleAlertIcon } from 'lucide-react'

import { t } from '@/lib/i18n'

// Perché un tracker pubblicato (target "done") non è ancora in seed, in
// ambra: il codice in error_message (seed_failed, no_client,
// seed_recheck_pending, seed_recheck_failed) tradotto, mai il codice grezzo
// in rosso. Il recheck in attesa non è un errore: un orologio, non un avviso.
export function TargetWarning({ code }: { code: string }) {
  const Icon = code === 'seed_recheck_pending' ? ClockIcon : TriangleAlertIcon
  return (
    <p className="flex items-start gap-1.5 text-xs text-amber-600 dark:text-amber-400">
      <Icon className="mt-0.5 size-3.5 shrink-0" />
      {t(`upload.result.warning.${code}`)}
    </p>
  )
}
