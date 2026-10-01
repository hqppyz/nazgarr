import { useState } from 'react'

import type { Schemas } from '@/api/client'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { t } from '@/lib/i18n'
import { selectLabel } from '@/lib/utils'

type Tracker = Schemas['TrackerResponse']
type Patch = Pick<Schemas['TrackerUpdateRequest'], 'min_seed_time_seconds' | 'min_ratio' | 'seed_rule'>

const UNITS = { hours: 3600, days: 86_400 } as const
type Unit = keyof typeof UNITS

function initialUnit(seconds: number | null | undefined): Unit {
  return seconds != null && seconds % UNITS.days === 0 ? 'days' : 'hours'
}

function parsed(raw: string): number | null | undefined {
  const value = raw.trim().replace(',', '.')
  if (value === '') return null
  const number = Number(value)
  return Number.isFinite(number) && number >= 0 ? number : undefined // undefined = non valido
}

// Il requisito di seed del tracker (hit and run): seedtime minimo e ratio
// minimo, entrambi facoltativi. Nella vista Not imported dice quali vecchi
// torrent si possono togliere senza rischi. Si salva uscendo dal campo.
export function TrackerSeedRequirement({ tracker, onChange }: { tracker: Tracker; onChange: (patch: Patch) => void }) {
  const [unit, setUnit] = useState<Unit>(initialUnit(tracker.min_seed_time_seconds))
  const toText = (seconds: number | null | undefined, u: Unit) =>
    seconds == null ? '' : String(Math.round((seconds / UNITS[u]) * 100) / 100)
  const [seedTime, setSeedTime] = useState(toText(tracker.min_seed_time_seconds, unit))
  const [ratio, setRatio] = useState(tracker.min_ratio == null ? '' : String(tracker.min_ratio))

  const saveSeedTime = (text: string, u: Unit) => {
    const value = parsed(text)
    if (value === undefined) return setSeedTime(toText(tracker.min_seed_time_seconds, u))
    const seconds = value == null ? null : Math.round(value * UNITS[u])
    if (seconds !== (tracker.min_seed_time_seconds ?? null)) onChange({ min_seed_time_seconds: seconds })
  }
  const saveRatio = () => {
    const value = parsed(ratio)
    if (value === undefined) return setRatio(tracker.min_ratio == null ? '' : String(tracker.min_ratio))
    if (value !== (tracker.min_ratio ?? null)) onChange({ min_ratio: value })
  }
  const enter = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter') event.currentTarget.blur()
  }
  const units = (Object.keys(UNITS) as Unit[]).map((u) => ({ value: u, label: t(`trackers.seedRequirement.${u}`) }))
  const rules = [
    { value: 'any', label: t('trackers.seedRequirement.any') },
    { value: 'all', label: t('trackers.seedRequirement.all') },
  ]

  return (
    <span className="flex flex-wrap items-center gap-1.5">
      <Input
        className="h-7 w-16 px-2 font-mono text-xs"
        inputMode="decimal"
        aria-label={t('trackers.seedRequirement.seedTime')}
        placeholder="—"
        value={seedTime}
        onChange={(e) => setSeedTime(e.target.value)}
        onBlur={() => saveSeedTime(seedTime, unit)}
        onKeyDown={enter}
      />
      <Select
        value={unit}
        onValueChange={(v) => {
          if (v == null) return
          setUnit(v as Unit)
          saveSeedTime(seedTime, v as Unit)
        }}
      >
        <SelectTrigger size="sm" className="h-7 w-20">
          <SelectValue>{(v: string | null) => selectLabel(units, v, (o) => o.value, (o) => o.label, '')}</SelectValue>
        </SelectTrigger>
        <SelectContent>
          {units.map((o) => (
            <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
          ))}
        </SelectContent>
      </Select>
      <span className="text-muted-foreground">{t('trackers.seedRequirement.ratioLabel')}</span>
      <Input
        className="h-7 w-14 px-2 font-mono text-xs"
        inputMode="decimal"
        aria-label={t('trackers.seedRequirement.ratio')}
        placeholder="—"
        value={ratio}
        onChange={(e) => setRatio(e.target.value)}
        onBlur={saveRatio}
        onKeyDown={enter}
      />
      {tracker.min_seed_time_seconds != null && tracker.min_ratio != null && (
        <Select value={tracker.seed_rule} onValueChange={(v) => v && v !== tracker.seed_rule && onChange({ seed_rule: v as 'any' | 'all' })}>
          <SelectTrigger size="sm" className="h-7 w-36" aria-label={t('trackers.seedRequirement.rule')}>
            <SelectValue>{(v: string | null) => selectLabel(rules, v, (o) => o.value, (o) => o.label, '')}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            {rules.map((o) => (
              <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
    </span>
  )
}
