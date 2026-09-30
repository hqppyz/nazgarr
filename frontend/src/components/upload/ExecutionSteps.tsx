import { CircleCheckIcon, CircleDashedIcon, CircleMinusIcon, CircleXIcon, LoaderCircleIcon } from 'lucide-react'
import { Fragment } from 'react'

import { t } from '@/lib/i18n'
import type { ExecutionStep, ExecutionStepState } from '@/lib/upload'
import { cn } from '@/lib/utils'

const ICONS: Record<ExecutionStepState, typeof CircleCheckIcon> = {
  pending: CircleDashedIcon,
  active: LoaderCircleIcon,
  done: CircleCheckIcon,
  failed: CircleXIcon,
  skipped: CircleMinusIcon,
}

const STYLES: Record<ExecutionStepState, string> = {
  pending: 'text-muted-foreground',
  active: 'border-primary bg-primary/10 text-primary',
  done: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
  failed: 'border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-300',
  skipped: 'text-muted-foreground line-through',
}

// La barra degli step dell'esecuzione: uno per passaggio, quelli conclusi
// restano con la spunta invece di essere sostituiti dal passaggio in corso.
export function ExecutionSteps({ steps }: { steps: ExecutionStep[] }) {
  return (
    <ol className="flex flex-wrap items-center gap-y-2" aria-label={t('upload.progress.stepsLabel')}>
      {steps.map((step, i) => {
        const Icon = ICONS[step.state]
        return (
          <Fragment key={step.key}>
            {i > 0 && (
              <li aria-hidden className={cn('h-px w-6 bg-border', step.state !== 'pending' && 'bg-primary/40')} />
            )}
            <li
              className={cn('flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium', STYLES[step.state])}
              title={t(`upload.steps.${step.state}`)}
            >
              <Icon className={cn('size-3.5 shrink-0', step.state === 'active' && 'animate-spin')} />
              <span>{step.label}</span>
              <span className="sr-only">({t(`upload.steps.${step.state}`)})</span>
            </li>
          </Fragment>
        )
      })}
    </ol>
  )
}
