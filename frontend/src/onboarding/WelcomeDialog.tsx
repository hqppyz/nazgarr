import { useState } from 'react'

import { RingLogo } from '@/components/RingLogo'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Switch } from '@/components/ui/switch'
import { t } from '@/lib/i18n'
import { DEFAULT_STATE, useOnboarding, useSetupStatus } from '@/onboarding/state'
import { tourStore } from '@/onboarding/tourStore'

// Il benvenuto del primo accesso: si apre da solo su un'istanza ancora da
// configurare (nessun tour mai visto e nessun disco). Due domande adattano il
// percorso; "Later" lo chiude e lo lascia rilanciabile dalle impostazioni.
export function WelcomeDialog() {
  const { state, isPending, save } = useOnboarding()
  const { data: status } = useSetupStatus()
  const [answers, setAnswers] = useState(DEFAULT_STATE.answers)
  const [closed, setClosed] = useState(false)
  const open = !closed && !isPending && state === null && status !== undefined && !status.steps.storage?.done

  const finish = (status: 'active' | 'dismissed') => {
    save({ ...DEFAULT_STATE, status, answers })
    setClosed(true)
    // "Start": subito il primo tour guidato, dai dischi.
    if (status === 'active') tourStore.start('storage')
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && finish('dismissed')}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <RingLogo size={32} />
            {t('onboarding.welcome.title')}
          </DialogTitle>
          <DialogDescription>{t('onboarding.welcome.description')}</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 text-sm">
          <p className="rounded-md border bg-muted/40 p-3 text-xs">{t('onboarding.welcome.approval')}</p>
          <div className="grid gap-1.5">
            <p className="font-medium">{t('onboarding.welcome.needTitle')}</p>
            <ul className="grid list-disc gap-1 pl-5 text-xs text-muted-foreground">
              <li>{t('onboarding.welcome.needPaths')}</li>
              <li>{t('onboarding.welcome.needClient')}</li>
              <li>{t('onboarding.welcome.needTmdb')}</li>
              <li>{t('onboarding.welcome.needTracker')}</li>
            </ul>
          </div>
          <div className="grid gap-2 border-t pt-3">
            {(['upload', 'arr'] as const).map((key) => (
              <label key={key} className="flex items-start justify-between gap-3">
                <span className="grid gap-0.5">
                  <span className="font-medium">{t(`onboarding.welcome.ask.${key}`)}</span>
                  <span className="text-xs text-muted-foreground">{t(`onboarding.welcome.ask.${key}Help`)}</span>
                </span>
                <Switch
                  checked={answers[key]}
                  onCheckedChange={(checked) => setAnswers((prev) => ({ ...prev, [key]: checked }))}
                />
              </label>
            ))}
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => finish('dismissed')}>
            {t('onboarding.welcome.later')}
          </Button>
          <Button onClick={() => finish('active')}>{t('onboarding.welcome.start')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
