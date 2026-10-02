import { FileIcon, FolderIcon } from 'lucide-react'
import { useTheme } from 'next-themes'
import { useMemo } from 'react'

import { useSetSetting, useSetting } from '@/api/hooks/settings'
import { ChoiceCards, type Choice } from '@/components/ChoiceCards'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { pushActivity } from '@/lib/activity'
import { autosaveFeedback } from '@/lib/autosave'
import { currentLocale, LOCALE_NAMES, LOCALES, setLocale, t, type Locale } from '@/lib/i18n'
import { formatBytes, type SizeUnits } from '@/lib/library-filters'
import { LIBRARY_VIEW_SETTING, libraryViewOf, type LibraryView } from '@/lib/library-view'
import { cn } from '@/lib/utils'

// Configuration > Interface. Tema e vista della libreria come schede con
// anteprima, come le unità delle dimensioni; il layout a due colonne lo dà
// la pagina (PAIRS in ConfigurationPage).

// --- Tema ------------------------------------------------------------------

type Theme = 'system' | 'light' | 'dark'

// Una finestrella in miniatura con i colori del tema: barra laterale, righe
// di testo, un accento. "system" è metà chiara e metà scura.
function ThemePreview({ theme }: { theme: Theme }) {
  const pane = (dark: boolean) => (
    <div className={cn('flex h-full flex-1 gap-1.5 p-1.5', dark ? 'bg-zinc-900' : 'bg-white')}>
      <div className={cn('w-1/4 rounded-sm', dark ? 'bg-zinc-800' : 'bg-zinc-100')} />
      <div className="grid flex-1 content-start gap-1">
        <div className={cn('h-1.5 w-3/4 rounded-full', dark ? 'bg-zinc-600' : 'bg-zinc-300')} />
        <div className={cn('h-1.5 w-1/2 rounded-full', dark ? 'bg-zinc-700' : 'bg-zinc-200')} />
        <div className="h-1.5 w-1/3 rounded-full bg-amber-400" />
      </div>
    </div>
  )
  return (
    <div className="flex h-16 overflow-hidden rounded-md border">
      {theme === 'dark' ? pane(true) : theme === 'light' ? pane(false) : (
        <>
          {pane(false)}
          {pane(true)}
        </>
      )}
    </div>
  )
}

const THEME_CHOICES: Choice<Theme>[] = [
  { value: 'system', title: t('interface.themeSystem'), preview: <ThemePreview theme="system" /> },
  { value: 'light', title: t('interface.themeLight'), preview: <ThemePreview theme="light" /> },
  { value: 'dark', title: t('interface.themeDark'), preview: <ThemePreview theme="dark" /> },
]

function ThemeCard({ className }: { className?: string }) {
  const { theme, setTheme } = useTheme()
  const current: Theme = theme === 'light' || theme === 'dark' ? theme : 'system'
  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>{t('interface.themeTitle')}</CardTitle>
        <CardDescription>{t('interface.themeDescription')}</CardDescription>
      </CardHeader>
      <CardContent>
        <ChoiceCards
          label={t('interface.themeTitle')}
          choices={THEME_CHOICES}
          value={current}
          className="sm:grid-cols-3"
          onSelect={(value, choice) => {
            setTheme(value)
            // Il tema resta in questo browser (next-themes, localStorage): stessa
            // notifica dei salvataggi sul server, per coerenza.
            pushActivity({ status: 'success', title: t('activity.saved'), detail: choice.title })
          }}
        />
      </CardContent>
    </Card>
  )
}

// --- Vista della libreria ------------------------------------------------------

function FolderPreview() {
  return (
    <div className="grid h-16 content-center gap-1 rounded-md border px-2 text-muted-foreground">
      {[0, 1, 1].map((depth, i) => (
        <div key={i} className="flex items-center gap-1" style={{ paddingLeft: depth * 10 }}>
          {depth === 0 ? <FolderIcon className="size-3 text-primary" /> : <FileIcon className="size-3" />}
          <div className="h-1.5 w-16 rounded-full bg-muted-foreground/30" />
        </div>
      ))}
    </div>
  )
}

function PosterPreview() {
  return (
    <div className="grid h-16 grid-cols-4 gap-1 rounded-md border p-1.5">
      {['from-amber-500/60', 'from-sky-500/60', 'from-emerald-500/60', 'from-rose-500/60'].map((color) => (
        <div key={color} className={cn('rounded-sm bg-gradient-to-b to-muted', color)} />
      ))}
    </div>
  )
}

const LIBRARY_CHOICES: Choice<LibraryView>[] = [
  { value: 'folder', title: t('library.folderView'), preview: <FolderPreview /> },
  { value: 'poster', title: t('library.posterView'), preview: <PosterPreview /> },
]

function LibraryViewCard({ className }: { className?: string }) {
  const { data } = useSetting(LIBRARY_VIEW_SETTING)
  const setSetting = useSetSetting(LIBRARY_VIEW_SETTING)
  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>{t('interface.libraryViewTitle')}</CardTitle>
        <CardDescription>{t('interface.libraryViewDescription')}</CardDescription>
      </CardHeader>
      <CardContent>
        <ChoiceCards
          label={t('interface.libraryViewTitle')}
          choices={LIBRARY_CHOICES}
          value={libraryViewOf(data?.value)}
          disabled={setSetting.isPending}
          className="grid-cols-2"
          onSelect={(value, choice) => setSetting.mutate(value, autosaveFeedback(choice.title))}
        />
      </CardContent>
    </Card>
  )
}

// --- Lingua e regione --------------------------------------------------------

const DATE_FORMATS = ['YYYY-MM-DD', 'DD/MM/YYYY', 'MM/DD/YYYY'] as const

function SettingSelect({
  settingKey,
  label,
  options,
  defaultValue,
}: {
  settingKey: string
  label: string
  options: { value: string; label: string }[]
  defaultValue: string
}) {
  const { data } = useSetting(settingKey)
  const setSetting = useSetSetting(settingKey)
  return (
    <div className="grid gap-1.5">
      <Label>{label}</Label>
      <Select value={data?.value || defaultValue} onValueChange={(v) => setSetting.mutate(v as string, autosaveFeedback(label))}>
        <SelectTrigger className="w-full">
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

function LanguageRegionCard({ className }: { className?: string }) {
  const browserTimeZone = useMemo(() => Intl.DateTimeFormat().resolvedOptions().timeZone, [])
  const timeZones = useMemo(() => {
    const supported = 'supportedValuesOf' in Intl ? Intl.supportedValuesOf('timeZone') : [browserTimeZone]
    return ['UTC', ...supported.filter((tz) => tz !== 'UTC')]
  }, [browserTimeZone])
  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>{t('interface.languageRegionTitle')}</CardTitle>
        <CardDescription>{t('timeLanguage.timeZoneDescription')}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="grid gap-1.5">
          <Label>{t('timeLanguage.languageTitle')}</Label>
          {/* Salvata nel browser; si ricarica la pagina perché molte etichette
              si calcolano una volta sola (lib/i18n.ts). */}
          <Select
            value={currentLocale()}
            onValueChange={(value) => {
              if (!value || value === currentLocale()) return
              setLocale(value as Locale)
              window.location.reload()
            }}
          >
            <SelectTrigger className="w-full">
              <SelectValue>{(v: string | null) => LOCALE_NAMES[(v ?? 'en') as Locale]}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              {LOCALES.map((locale) => (
                <SelectItem key={locale} value={locale}>
                  {LOCALE_NAMES[locale]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">{t('timeLanguage.languageDescription')}</p>
        </div>
        <SettingSelect
          settingKey="ui_timezone"
          label={t('timeLanguage.timeZoneTitle')}
          options={timeZones.map((tz) => ({ value: tz, label: tz }))}
          defaultValue={browserTimeZone}
        />
        <div className="grid gap-4 sm:grid-cols-2">
          <SettingSelect
            settingKey="ui_date_format"
            label={t('timeLanguage.dateFormatTitle')}
            options={DATE_FORMATS.map((format) => ({ value: format, label: format }))}
            defaultValue="YYYY-MM-DD"
          />
          <SettingSelect
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
  )
}

// --- Dimensioni dei file --------------------------------------------------------

// Dimensioni tipiche (un film 4K, un episodio, un file piccolo) per far vedere
// come cambia la stessa dimensione con le due unità.
const SIZE_SAMPLES = [58_300_000_000, 1_460_000_000, 350_000_000]

const SIZE_CHOICES: Choice<SizeUnits>[] = (['decimal', 'binary'] as const).map((units) => ({
  value: units,
  title: units === 'decimal' ? t('timeLanguage.sizeUnitsDecimalTitle') : t('timeLanguage.sizeUnitsBinaryTitle'),
  description: units === 'decimal' ? t('timeLanguage.sizeUnitsDecimalHelp') : t('timeLanguage.sizeUnitsBinaryHelp'),
  preview: <span className="font-mono text-xs">{SIZE_SAMPLES.map((b) => formatBytes(b, units)).join(' · ')}</span>,
}))

function FileSizesCard({ className }: { className?: string }) {
  const { data } = useSetting('size_units')
  const setSetting = useSetSetting('size_units')
  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>{t('timeLanguage.sizeUnitsTitle')}</CardTitle>
        <CardDescription>{t('timeLanguage.sizeUnitsDescription')}</CardDescription>
      </CardHeader>
      <CardContent>
        <ChoiceCards
          label={t('timeLanguage.sizeUnitsTitle')}
          choices={SIZE_CHOICES}
          value={data?.value === 'binary' ? 'binary' : 'decimal'}
          disabled={setSetting.isPending}
          className="sm:grid-cols-2"
          onSelect={(value, choice) => setSetting.mutate(value, autosaveFeedback(choice.title))}
        />
      </CardContent>
    </Card>
  )
}

export function InterfaceSection() {
  return (
    <>
      <LanguageRegionCard />
      <ThemeCard />
      <FileSizesCard />
      <LibraryViewCard />
    </>
  )
}
