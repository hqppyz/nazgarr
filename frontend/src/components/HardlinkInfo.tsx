import { InfoIcon } from 'lucide-react'

import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { t } from '@/lib/i18n'

// Hover (o tocco) sull'icona per vedere con quali altri path questo file
// condivide l'hardlink (relazione seed_file.media_file_id, già stabilita dal
// motore di matching — mai un nuovo scan degli inode solo per questo).
// Popover e non Tooltip: un tooltip al tocco non si apre.
export function HardlinkInfo({ linkedPaths }: { linkedPaths: string[] }) {
  if (linkedPaths.length === 0) return null

  return (
    <Popover>
      <PopoverTrigger
        openOnHover
        delay={150}
        // Su touch un'area più grande dell'icona: a 14 px il dito la manca.
        className="shrink-0 rounded text-muted-foreground hover:text-foreground pointer-coarse:-m-1.5 pointer-coarse:p-1.5"
        aria-label={t('library.hardlink')}
        onClick={(e) => e.stopPropagation()}  // la riga apre la scheda: l'icona mostra solo i percorsi
      >
        <InfoIcon className="size-3.5" />
      </PopoverTrigger>
      <PopoverContent side="right" align="start" className="w-auto max-w-[min(24rem,calc(100vw-2rem))] text-xs" onClick={(e) => e.stopPropagation()}>
        <div className="grid gap-0.5">
          <span className="font-medium">
            {t('library.hardlink')} ({linkedPaths.length})
          </span>
          {linkedPaths.map((path) => (
            <span key={path} className="font-mono text-[11px] break-all opacity-90">
              {path}
            </span>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  )
}
