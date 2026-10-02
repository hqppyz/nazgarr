import { CompassIcon } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { t } from '@/lib/i18n'
import { DEFAULT_STATE, useOnboarding } from '@/onboarding/state'
import { tourStore } from '@/onboarding/tourStore'

// Settings > Application: rilancia il tour (checklist attiva, passi visti
// azzerati, risposte del benvenuto tenute) e porta alla dashboard.
export function RestartTourCard() {
  const { state, save } = useOnboarding()
  const navigate = useNavigate()
  return (
    <Card>
      <CardHeader>
        <div className="flex w-full items-center justify-between gap-3">
          <CardTitle className="flex items-center gap-2">
            <CompassIcon className="size-4" />
            {t('onboarding.restart.title')}
          </CardTitle>
          <div className="flex flex-wrap gap-1.5">
            <Button variant="ghost" size="sm" onClick={() => tourStore.start('views')}>
              {t('onboarding.step.views.title')}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                save({ ...DEFAULT_STATE, answers: state?.answers ?? DEFAULT_STATE.answers })
                navigate('/dashboard')
              }}
            >
              {t('onboarding.restart.button')}
            </Button>
          </div>
        </div>
        <CardDescription>{t('onboarding.restart.description')}</CardDescription>
      </CardHeader>
    </Card>
  )
}
