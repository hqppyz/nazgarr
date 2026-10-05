import { Popover, PopoverContent, PopoverHeader, PopoverTitle, PopoverTrigger } from '@/components/ui/popover'
import { t } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { opensOnHover } from '@/lib/pointer'

// Il numero di errori resta compatto nelle tabelle; il dettaglio si apre al
// passaggio del mouse o al click (Popover e non Tooltip: funziona anche al
// tocco, il testo si può selezionare e copiare, e regge messaggi lunghi).
export function ErrorsPopover({
  count,
  messages,
  title = t('common.errorsTitle', { count }),
  className,
}: {
  count: number
  messages: string[]
  title?: string
  className?: string
}) {
  if (count === 0) return <span className={cn('text-xs text-muted-foreground tabular-nums', className)}>0</span>
  return (
    <Popover>
      <PopoverTrigger
        openOnHover={opensOnHover()}
        delay={150}
        className={cn(
          'inline-flex min-w-6 cursor-pointer items-center justify-center rounded-md bg-destructive/10 px-1.5 py-0.5 font-mono text-xs font-medium text-destructive tabular-nums hover:bg-destructive/20',
          className,
        )}
        aria-label={title}
      >
        {count}
      </PopoverTrigger>
      <PopoverContent align="end" className="w-96 max-w-[calc(100vw-2rem)]">
        <PopoverHeader>
          <PopoverTitle>{title}</PopoverTitle>
        </PopoverHeader>
        {messages.length === 0 ? (
          <p className="text-xs text-muted-foreground">{t('common.errorsNoDetail')}</p>
        ) : (
          <ul className="grid max-h-72 gap-1.5 overflow-y-auto">
            {messages.map((message, i) => (
              <li key={i} className="rounded bg-muted/60 px-2 py-1 font-mono text-xs break-words whitespace-pre-wrap select-text">
                {message}
              </li>
            ))}
          </ul>
        )}
        {count > messages.length && messages.length > 0 && (
          <p className="text-xs text-muted-foreground">{t('common.errorsMoreInLogs', { count: count - messages.length })}</p>
        )}
      </PopoverContent>
    </Popover>
  )
}
