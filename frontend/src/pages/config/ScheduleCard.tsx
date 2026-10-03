import { useState } from 'react'
import { toast } from 'sonner'

import { useSchedule, useSetSchedule } from '@/api/hooks/schedule'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { ToggleGroupItem, ToggleGroupSingle } from '@/components/ui/toggle-group'
import { t } from '@/lib/i18n'

// Le scansioni automatiche (cron, nazgarr/scheduler.py). Stava in fondo alla
// pagina Reseeding, dove non si trovava: qui, con le altre impostazioni del
// reseeding, con qualche scelta pronta e il cron libero per il resto.
const PRESETS = [
  { key: 'off', cron: '' },
  { key: 'every6h', cron: '0 */6 * * *' },
  { key: 'every12h', cron: '0 */12 * * *' },
  { key: 'daily', cron: '0 3 * * *' },
] as const

export function ScheduleCard() {
  const { data: schedule } = useSchedule()
  const setSchedule = useSetSchedule()
  const [draft, setDraft] = useState<string | null>(null)
  const cron = draft ?? schedule?.cron ?? ''
  const preset = PRESETS.find((p) => p.cron === cron)?.key ?? 'custom'

  function save(value: string) {
    setSchedule.mutate(value || null, {
      onSuccess: () => {
        toast.success(value ? t('reseeding.scheduleSet') : t('reseeding.scheduleDisabled'))
        setDraft(null)
      },
      onError: (error) => toast.error(t('common.saveFailed', { message: error.message })),
    })
  }

  return (
    <Card data-tour="reseeding.schedule">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {t('misc.schedule')}
          <Badge variant={schedule?.enabled ? 'default' : 'secondary'}>
            {schedule?.enabled ? t('reseeding.scheduleActive') : t('reseeding.scheduleInactive')}
          </Badge>
        </CardTitle>
        <CardDescription>{t('reseeding.scheduleDescription')}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        <ToggleGroupSingle
          value={preset}
          variant="outline"
          size="sm"
          className="flex-wrap gap-1.5"
          disabled={setSchedule.isPending}
          onValueChange={(value) => {
            const chosen = PRESETS.find((p) => p.key === value)
            if (chosen) save(chosen.cron)
            else if (value === 'custom') setDraft(cron || '0 */6 * * *')
          }}
        >
          {[...PRESETS.map((p) => p.key), 'custom'].map((key) => (
            <ToggleGroupItem key={key} value={key} className="flex-none rounded-md px-3 whitespace-nowrap">
              {t(`reseeding.schedulePreset.${key}`)}
            </ToggleGroupItem>
          ))}
        </ToggleGroupSingle>
        <div className="flex flex-wrap items-center gap-2">
          <Input
            value={cron}
            placeholder="0 */6 * * *"
            onChange={(e) => setDraft(e.target.value)}
            className="max-w-xs font-mono"
            aria-label="cron"
          />
          <Button variant="outline" disabled={draft === null || setSchedule.isPending} onClick={() => save(cron)}>
            {t('common.save')}
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          {t('reseeding.cronHintPre')}
          <code>0 */6 * * *</code>
          {t('reseeding.cronHintPost')}
        </p>
      </CardContent>
    </Card>
  )
}
