import { Popover as PopoverPrimitive } from '@base-ui/react/popover'
import { InfoIcon } from 'lucide-react'
import type { ReactNode, SyntheticEvent } from 'react'

import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import type { InfoPopoverHandle } from '@/lib/popupHandles'
import { opensOnHover } from '@/lib/pointer'
import { cn } from '@/lib/utils'

const stop = (event: SyntheticEvent) => event.stopPropagation()

const CONTENT_CLASS = 'w-80 max-w-[calc(100vw-2rem)] text-xs break-words'

// Un popover per tutte le righe di una lista lunga (lib/popupHandles.ts): i
// trigger (InfoPopover con `handle`, HardlinkInfo) gli passano il loro contenuto.
export function InfoPopoverHost({ handle }: { handle: InfoPopoverHandle }) {
  return (
    <PopoverPrimitive.Root handle={handle}>
      {({ payload }) =>
        payload && (
          // I click non risalgono alla riga sotto (gli eventi di React passano dai portali).
          <PopoverContent align={payload.align ?? 'start'} side={payload.side} className={payload.className ?? CONTENT_CLASS}
                          onClick={stop}>
            {payload.content}
          </PopoverContent>
        )
      }
    </PopoverPrimitive.Root>
  )
}

// Una spiegazione che prima stava solo in un title (visibile solo al
// passaggio del mouse): ora si apre anche al tocco, come ErrorsPopover.
// Con `handle` si apre nel popover condiviso della lista (InfoPopoverHost).
export function InfoPopover({
  children,
  content,
  className,
  align = 'start',
  handle,
}: {
  children: ReactNode
  content: ReactNode
  className?: string
  align?: 'start' | 'center' | 'end'
  handle?: InfoPopoverHandle
}) {
  if (!content) return <>{children}</>
  const triggerProps = {
    openOnHover: opensOnHover(),
    delay: 250,
    render: <span role="button" tabIndex={0} />,
    // Sul touch un bersaglio più grande del testo (spesso un "—" o un "OK").
    className: cn('cursor-help pointer-coarse:-m-2 pointer-coarse:p-2', className),
    onClick: stop,
  }
  if (handle) {
    return (
      <PopoverPrimitive.Trigger handle={handle} payload={{ content, align }} {...triggerProps}>
        {children}
      </PopoverPrimitive.Trigger>
    )
  }
  return (
    <Popover>
      <PopoverTrigger {...triggerProps}>{children}</PopoverTrigger>
      <PopoverContent align={align} className={CONTENT_CLASS} onClick={stop}>
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
