import { ListChecksIcon, PackageIcon, XIcon } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import { t } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { packProblem, packUploadTarget, type PackFile, type PackSelection } from '@/lib/pack'

// Il pulsante che accende la selezione per un pack.
export function PackSelectButton({ selection }: { selection: PackSelection }) {
  return (
    // Giallo solo nei bordi: si nota, ma non diventa l'azione principale.
    <Button
      size="sm"
      variant="outline"
      aria-pressed={selection.active}
      onClick={() => selection.setActive(!selection.active)}
      title={t('pack.selectHelp')}
      data-tour="views.pack"
      className={cn(
        'border-amber-500/70 text-amber-700 hover:bg-amber-500/10 hover:text-amber-800 dark:border-amber-400/60 dark:text-amber-300 dark:hover:text-amber-200',
        selection.active && 'bg-amber-500/15',
      )}
    >
      <PackageIcon className="size-4" />
      {selection.active ? t('pack.selectStop') : t('pack.select')}
    </Button>
  )
}

// In fondo alla vista mentre si scelgono gli episodi: quanti sono e "Crea
// pack", che porta al nuovo upload con la lista. Con shown (i video che i
// filtri mostrano) anche "Scegli tutti i mostrati": su touch non c'è SHIFT+clic.
export function PackBar({ selection, tmdb, shown }: { selection: PackSelection; tmdb?: string; shown?: PackFile[] }) {
  const navigate = useNavigate()
  if (!selection.active) return null
  const problem = packProblem(selection.files)
  const allShown = shown != null && shown.length > 0 && shown.every((f) => selection.has(f))
  return (
    <div className="sticky bottom-3 z-20 flex flex-wrap items-center gap-3 rounded-lg border bg-background/95 p-3 shadow-lg backdrop-blur">
      <PackageIcon className="size-4 shrink-0 text-primary" />
      <div className="grid min-w-0 flex-1 gap-0.5 text-sm">
        <span className="font-medium">{t('pack.selected', { count: selection.files.length })}</span>
        <span className="text-xs text-muted-foreground">
          {problem ? t(`pack.problem.${problem}`) : t('pack.ready')}
        </span>
      </div>
      {shown != null && shown.length > 0 && (
        <Button size="sm" variant="outline" onClick={() => selection.setMany(shown, !allShown)}>
          <ListChecksIcon className="size-4" />
          {allShown ? t('library.packDeselectShown') : t('library.packSelectShown', { count: shown.length })}
        </Button>
      )}
      <Button size="sm" variant="ghost" onClick={() => selection.setActive(false)}>
        <XIcon className="size-4" />
        {t('common.cancel')}
      </Button>
      <Button
        size="sm"
        disabled={problem !== null}
        onClick={() => {
          const target = packUploadTarget(selection.files, tmdb)
          navigate(target.to, { state: target.state })
        }}
      >
        {t('pack.create')}
      </Button>
    </div>
  )
}
