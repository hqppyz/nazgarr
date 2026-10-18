import { Popover as PopoverPrimitive } from '@base-ui/react/popover'
import { InfoIcon } from 'lucide-react'

import type { InfoPopoverHandle } from '@/lib/popupHandles'
import { t } from '@/lib/i18n'
import { opensOnHover } from '@/lib/pointer'

// Hover (o tocco) sull'icona per vedere con quali altri path questo file
// condivide l'hardlink (relazione seed_file.media_file_id, già stabilita dal
// motore di matching — mai un nuovo scan degli inode solo per questo).
// Popover e non Tooltip: un tooltip al tocco non si apre. Si apre nel popover
// condiviso dell'albero (InfoPopoverHost): uno per file era troppo caro.
export function HardlinkInfo({ linkedPaths, handle }: { linkedPaths: string[]; handle: InfoPopoverHandle }) {
  if (linkedPaths.length === 0) return null

  const content = (
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
  )
  return (
    <PopoverPrimitive.Trigger
      handle={handle}
      payload={{ content, side: 'right', align: 'start', className: 'w-auto max-w-[min(24rem,calc(100vw-2rem))] text-xs' }}
      openOnHover={opensOnHover()}
      delay={150}
      // Su touch un'area più grande dell'icona: a 14 px il dito la manca.
      className="shrink-0 rounded text-muted-foreground hover:text-foreground pointer-coarse:-m-1.5 pointer-coarse:p-1.5"
      aria-label={t('library.hardlink')}
      onClick={(e) => e.stopPropagation()}  // la riga apre la scheda: l'icona mostra solo i percorsi
    >
      <InfoIcon className="size-3.5" />
    </PopoverPrimitive.Trigger>
  )
}
