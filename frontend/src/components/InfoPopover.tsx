import { InfoIcon } from 'lucide-react'
import type { ReactNode } from 'react'

import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { opensOnHover } from '@/lib/pointer'
import { cn } from '@/lib/utils'

// Una spiegazione che prima stava solo in un title (visibile solo al
// passaggio del mouse): ora si apre anche al tocco, come ErrorsPopover.
export function InfoPopover({
  children,
  content,
  className,
  align = 'start',
}: {
  children: ReactNode
  content: ReactNode
  className?: string
  align?: 'start' | 'center' | 'end'
}) {
  if (!content) return <>{children}</>
  return (
    <Popover>
      <PopoverTrigger
        openOnHover={opensOnHover()}
        delay={250}
        render={<span role="button" tabIndex={0} />}
        // Sul touch un bersaglio più grande del testo (spesso un "—" o un "OK").
        className={cn('cursor-help pointer-coarse:-m-2 pointer-coarse:p-2', className)}
        onClick={(event) => event.stopPropagation()}
      >
        {children}
      </PopoverTrigger>
      {/* I click non risalgono alla riga sotto (gli eventi di React passano dai portali). */}
      <PopoverContent align={align} className="w-80 max-w-[calc(100vw-2rem)] text-xs break-words"
                      onClick={(event) => event.stopPropagation()}>
        {content}
      </PopoverContent>
    </Popover>
  )
}

// Un'icona "i" accanto a un titolo che apre la sua spiegazione: si vede che
// c'è, invece di doverla scoprire passando sul titolo.
export function InfoHint({ content, label }: { content: ReactNode; label: string }) {
  return (
    <InfoPopover content={content} className="inline-flex items-center text-muted-foreground hover:text-foreground">
      <InfoIcon className="size-3.5" aria-label={label} />
    </InfoPopover>
  )
}
