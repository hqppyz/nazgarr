import { useMemo } from 'react'

import { useSetSetting, useSetting } from '@/api/hooks/settings'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { t } from '@/lib/i18n'
import { formatBytes, type SizeUnits } from '@/lib/library-filters'
import { cn } from '@/lib/utils'
import { autosaveFeedback } from '@/lib/autosave'

const DATE_FORMATS = ['YYYY-MM-DD', 'DD/MM/YYYY', 'MM/DD/YYYY'] as const

// Le impostazioni si salvano davvero (stesso app_settings key/value di
// tmdb_api_key ecc.), ma per ora nessuna pagina le legge ancora per
// formattare le date che già mostra — vedi timeLanguage.notYetAppliedNote.
function SettingSelectField({
  settingKey,
  label,
  description,
  options,
  defaultValue,
}: {
  settingKey: string
  label: string
  description?: string
  options: { value: string; label: string }[]
  defaultValue: string
}) {
  const { data } = useSetting(settingKey)
  const setSetting = useSetSetting(settingKey)
  const value = data?.value || defaultValue

  return (
    <div className="grid gap-1.5">
      <Label>{label}</Label>
      {description && <p className="text-xs text-muted-foreground">{description}</p>}
      <Select value={value} onValueChange={(v) => setSetting.mutate(v, autosaveFeedback(label))}>
        <SelectTrigger>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

// Dimensioni tipiche (un film 4K, un episodio, un file piccolo) per far
// vedere come cambia la stessa dimensione con le due unità.
const SIZE_SAMPLES = [58_300_000_000, 1_460_000_000, 350_000_000]

const SIZE_UNIT_OPTIONS: { value: SizeUnits; title: string; description: string }[] = [
  { value: 'decimal', title: t('timeLanguage.sizeUnitsDecimalTitle'), description: t('timeLanguage.sizeUnitsDecimalHelp') },
  { value: 'binary', title: t('timeLanguage.sizeUnitsBinaryTitle'), description: t('timeLanguage.sizeUnitsBinaryHelp') },
]

function SizeUnitsField() {
  const { data } = useSetting('size_units')
  const setSetting = useSetSetting('size_units')
  const current: SizeUnits = data?.value === 'binary' ? 'binary' : 'decimal'

  return (
    <div role="radiogroup" aria-label={t('timeLanguage.sizeUnitsTitle')} className="grid gap-3 sm:grid-cols-2">
      {SIZE_UNIT_OPTIONS.map((option) => {
        const selected = option.value === current
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            disabled={setSetting.isPending}
            onClick={() => !selected && setSetting.mutate(option.value, autosaveFeedback(option.title))}
            className={cn(
              'grid gap-2 rounded-lg border p-3 text-left transition-colors hover:bg-muted/50',
              selected && 'border-primary bg-primary/5 ring-1 ring-primary',
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium">{option.title}</span>
              {selected && (
                <span className="rounded bg-primary px-1.5 py-0.5 text-[length:var(--text-xxs)] font-medium text-primary-foreground">
                  {t('timeLanguage.sizeUnitsCurrent')}
                </span>
              )}
            </div>
            <span className="text-xs text-muted-foreground">{option.description}</span>
            <span className="font-mono text-xs">
              {SIZE_SAMPLES.map((bytes) => formatBytes(bytes, option.value)).join(' · ')}
            </span>
          </button>
        )
      })}
    </div>
  )
}

export function TimeLanguageSection() {
  const browserTimeZone = useMemo(() => Intl.DateTimeFormat().resolvedOptions().timeZone, [])
  const timeZones = useMemo(() => {
    const supported =
      'supportedValuesOf' in Intl ? Intl.supportedValuesOf('timeZone') : [browserTimeZone]
    return ['UTC', ...supported.filter((tz) => tz !== 'UTC')].sort((a, b) => (a === 'UTC' ? -1 : a.localeCompare(b)))
  }, [browserTimeZone])

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>{t('timeLanguage.languageTitle')}</CardTitle>
          <CardDescription>{t('timeLanguage.languageDescription')}</CardDescription>
        </CardHeader>
        <CardContent>
          <Select value="en" disabled>
            <SelectTrigger className="w-56">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="en">English</SelectItem>
            </SelectContent>
          </Select>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t('timeLanguage.timeZoneTitle')}</CardTitle>
          <CardDescription>{t('timeLanguage.timeZoneDescription')}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <SettingSelectField
            settingKey="ui_timezone"
            label={t('timeLanguage.timeZoneTitle')}
            options={timeZones.map((tz) => ({ value: tz, label: tz }))}
            defaultValue={browserTimeZone}
          />
          <div className="grid gap-4 sm:grid-cols-2">
            <SettingSelectField
              settingKey="ui_date_format"
              label={t('timeLanguage.dateFormatTitle')}
              options={DATE_FORMATS.map((format) => ({ value: format, label: format }))}
              defaultValue="YYYY-MM-DD"
            />
            <SettingSelectField
              settingKey="ui_time_format"
              label={t('timeLanguage.timeFormatTitle')}
              options={[
                { value: '24h', label: t('timeLanguage.timeFormat24h') },
                { value: '12h', label: t('timeLanguage.timeFormat12h') },
              ]}
              defaultValue="24h"
            />
          </div>
          <p className="text-xs text-muted-foreground">{t('timeLanguage.notYetAppliedNote')}</p>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>{t('timeLanguage.sizeUnitsTitle')}</CardTitle>
          <CardDescription>{t('timeLanguage.sizeUnitsDescription')}</CardDescription>
        </CardHeader>
        <CardContent>
          <SizeUnitsField />
        </CardContent>
      </Card>
    </>
  )
}
