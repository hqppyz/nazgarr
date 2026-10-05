import { ArrowRightIcon, CircleCheckIcon, CircleIcon } from 'lucide-react'
import { Link } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { t } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { useOnboarding, useSetupStatus } from '@/onboarding/state'
import { isDone, visibleSteps } from '@/onboarding/steps'
import { tourStore } from '@/onboarding/tourStore'
import { tourFor } from '@/onboarding/tours'

// La checklist "Getting started" in cima alla dashboard, finché il tour è
// attivo. Ogni passo è fatto quando lo dice la configurazione reale (un disco
// aggiunto a mano conta), i facoltativi con dei default quando li hai visti.
export function GettingStartedCard() {
  const { state, save } = useOnboarding()
  const { data: status } = useSetupStatus()
  if (!state || state.status !== 'active' || !status) return null

  const steps = visibleSteps(state)
  const done = steps.filter((step) => isDone(step, status, state))
  const required = steps.filter((step) => !step.optional)
  const ready = required.every((step) => isDone(step, status, state))
  const next = steps.find((step) => !isDone(step, status, state) && !step.optional) ?? steps.find((s) => !isDone(s, status, state))
  const markSeen = (key: string) =>
    !state.seen.includes(key) && save({ ...state, seen: [...state.seen, key] })

  return (
    <Card data-tour="dashboard.getting-started">
      <CardHeader className="flex flex-wrap items-start justify-between gap-3">
        <div className="grid gap-1">
          <CardTitle>{t(ready ? 'onboarding.checklist.readyTitle' : 'onboarding.checklist.title')}</CardTitle>
          <CardDescription>{t(ready ? 'onboarding.checklist.readyDescription' : 'onboarding.checklist.description')}</CardDescription>
        </div>
        <div className="flex gap-1">
          {ready && (
            <Button variant="outline" size="sm" onClick={() => tourStore.start('views')}>
              {t('onboarding.step.views.title')}
            </Button>
          )}
          <Button variant="ghost" size="sm" onClick={() => save({ ...state, status: ready ? 'done' : 'dismissed' })}>
            {t(ready ? 'onboarding.checklist.finish' : 'onboarding.checklist.hide')}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="grid gap-3">
        <div className="flex items-center gap-3">
          <Progress value={(done.length / steps.length) * 100} className="flex-1" />
          <span className="font-mono text-xs text-muted-foreground tabular-nums">
            {done.length}/{steps.length}
          </span>
        </div>
        <ol className="grid gap-1 sm:grid-cols-2">
          {steps.map((step) => {
            const complete = isDone(step, status, state)
            return (
              <li key={step.key}>
                <Link
                  to={step.to}
                  onClick={(event) => {
                    if (step.from === 'seen') markSeen(step.key)
                    // Con un tour guidato, il tour porta lui alla schermata.
                    if (tourFor(step.key)) {
                      event.preventDefault()
                      tourStore.start(step.key)
                    }
                  }}
                  className={cn(
                    'group flex items-start gap-2 rounded-md p-2 hover:bg-muted/60',
                    next?.key === step.key && 'bg-primary/5 ring-1 ring-primary/30',
                  )}
                >
                  {complete ? (
                    <CircleCheckIcon className="mt-0.5 size-4 shrink-0 text-emerald-500" />
                  ) : (
                    <CircleIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                  )}
                  <span className="grid min-w-0 flex-1 gap-0.5">
                    <span className={cn('text-sm font-medium', complete && 'text-muted-foreground line-through')}>
                      {t(`onboarding.step.${step.key}.title`)}
                      {step.optional && (
                        <span className="ml-1.5 text-xs font-normal text-muted-foreground">{t('onboarding.checklist.optional')}</span>
                      )}
                    </span>
                    <span className="text-xs text-muted-foreground">{t(`onboarding.step.${step.key}.summary`)}</span>
                  </span>
                  {tourFor(step.key) ? (
                    <span className="mt-0.5 shrink-0 text-xs text-primary pointer-fine:opacity-0 pointer-fine:group-hover:opacity-100">
                      {t('onboarding.checklist.guide')}
                    </span>
                  ) : (
                    <ArrowRightIcon className="mt-0.5 size-3.5 shrink-0 text-muted-foreground pointer-fine:opacity-0 pointer-fine:group-hover:opacity-100" />
                  )}
                </Link>
              </li>
            )
          })}
        </ol>
      </CardContent>
    </Card>
  )
}
