import { t } from '@/lib/i18n'

// La pagina di una voce di navigazione che non ne ha ancora una vera
// (App.tsx, overrides): oggi nessuna, ma una voce nuova senza pagina dice
// così invece di restare vuota.
export function ComingSoon({ title }: { title: string }) {
  return (
    <div className="flex h-full min-h-[50vh] flex-col items-center justify-center gap-1 text-center text-muted-foreground">
      <p className="text-lg font-medium text-foreground">{title}</p>
      <p className="text-sm">{t('common.workInProgressHint')}</p>
    </div>
  )
}
