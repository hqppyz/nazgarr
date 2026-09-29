import type { ReactNode } from 'react'

import { t } from '@/lib/i18n'
import { cn } from '@/lib/utils'

export interface Choice<T extends string> {
  value: T
  title: string
  description?: string
  preview?: ReactNode // anteprima sotto il testo (es. dimensioni di esempio, miniatura del tema)
}

// Scelta fra poche opzioni come schede cliccabili: quella attiva ha il bordo
// del colore primario e il segno "In use". Usata in Configuration > Interface
// (tema, vista della libreria, unità delle dimensioni).
export function ChoiceCards<T extends string>({
  label,
  choices,
  value,
  onSelect,
  disabled = false,
  className,
}: {
  label: string
  choices: Choice<T>[]
  value: T
  onSelect: (value: T, choice: Choice<T>) => void
  disabled?: boolean
  className?: string
}) {
  return (
    <div role="radiogroup" aria-label={label} className={cn('grid gap-3', className)}>
      {choices.map((choice) => {
        const selected = choice.value === value
        return (
          <button
            key={choice.value}
            type="button"
            role="radio"
            aria-checked={selected}
            disabled={disabled}
            onClick={() => !selected && onSelect(choice.value, choice)}
            className={cn(
              'grid content-start gap-2 rounded-lg border p-3 text-left transition-colors hover:bg-muted/50',
              selected && 'border-primary bg-primary/5 ring-1 ring-primary',
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium">{choice.title}</span>
              {selected && (
                <span className="rounded bg-primary px-1.5 py-0.5 text-[length:var(--text-xxs)] font-medium text-primary-foreground">
                  {t('interface.inUse')}
                </span>
              )}
            </div>
            {choice.description && <span className="text-xs text-muted-foreground">{choice.description}</span>}
            {choice.preview}
          </button>
        )
      })}
    </div>
  )
}
