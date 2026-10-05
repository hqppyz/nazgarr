import { TriangleAlertIcon } from 'lucide-react'

import { useUpdateOverrides, type UploadJob } from '@/api/hooks/uploads'
import { t } from '@/lib/i18n'
import { packMixed, packMixedConfirmed } from '@/lib/pack'

// Un pack di episodi scelti a mano con release diverse (nazgarr/upload/pack.py):
// cosa cambia fra gli episodi, e la conferma senza cui l'upload non parte.
export function PackMixedCard({ job }: { job: UploadJob }) {
  const save = useUpdateOverrides(job.id)
  const mixed = packMixed(job)
  if (!mixed) return null
  const confirmed = packMixedConfirmed(job)
  return (
    <div role="alert" className="grid gap-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 text-sm">
      <div className="flex gap-3">
        <TriangleAlertIcon className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400" />
        <div className="grid gap-1">
          <p className="font-medium">{t('pack.mixedTitle')}</p>
          <p className="text-muted-foreground">{t('pack.mixedDescription')}</p>
        </div>
      </div>
      <dl className="grid gap-1 pl-7 text-xs sm:grid-cols-[auto_1fr] sm:gap-x-4">
        {Object.entries(mixed).map(([field, values]) => (
          <div key={field} className="contents">
            <dt className="font-medium">{t(`pack.mixedField.${field}`)}</dt>
            <dd className="font-mono break-all text-muted-foreground">{values.join(' · ')}</dd>
          </div>
        ))}
      </dl>
      <label className="flex w-fit items-center gap-2 pl-7 font-medium">
        <input
          type="checkbox"
          className="size-4 accent-primary"
          checked={confirmed}
          disabled={save.isPending || job.status !== 'awaiting_decision'}
          onChange={(e) => save.mutate({ ...job.overrides, pack_mixed_confirmed: e.target.checked })}
        />
        {t('pack.mixedConfirm')}
      </label>
    </div>
  )
}
