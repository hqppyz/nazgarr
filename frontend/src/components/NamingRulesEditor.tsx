import { useEffect, useRef, useState, type ReactNode } from 'react'

import { useNamingPreview } from '@/api/hooks/trackers'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { t } from '@/lib/i18n'
import { cn } from '@/lib/utils'

export type NamingRules = Record<string, unknown> & {
  templates?: Record<string, string>
  audio_languages?: { style?: string; primary?: string; multi_from?: number }
  subs_languages?: { style?: string; primary?: string; multi_from?: number }
}

// Un template per tipo di release (le chiavi type_id dei profili); vuoto =
// usa quello di default.
// 'tv': il pattern per le serie (di solito senza anno), prima di quelli per tipo.
const TEMPLATE_KEYS = [
  'default', 'tv', 'REMUX', 'WEBDL', 'WEBRIP', 'WEBMUX', 'DLMUX', 'ENCODE', 'HDTV', 'DVDRIP', 'BRRIP',
] as const
// Stesse di app/upload_naming.py DEFAULT_TYPE_LABELS.
const DEFAULT_TYPE_LABELS: Record<string, string> = {
  REMUX: 'REMUX', WEBDL: 'WEB-DL', WEBRIP: 'WEBRip', WEBMUX: 'WEBMux', DLMUX: 'DLMux', ENCODE: '', HDTV: 'HDTV',
  DVDRIP: 'DVDRip', BRRIP: 'BRRip',
}
// Stesso ordine di app/upload_naming.py VARIABLES.
const VARIABLE_NAMES = [
  'title', 'local_title', 'year', 'season', 'episode', 'edition', 'repack', 'resolution', 'format', 'source', 'source_full', 'type',
  'service', 'video_codec', 'hdr', 'bit_depth', 'audio', 'audio_codec', 'audio_channels', 'audio_atmos',
  'audio_all', 'audio_languages', 'subs_languages', 'subs', 'group',
]

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(id)
  }, [value, ms])
  return debounced
}

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="grid gap-2 rounded-md border p-3">
      <legend className="px-1 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">{title}</legend>
      <div className="grid gap-3 sm:grid-cols-3">{children}</div>
    </fieldset>
  )
}

function OptionSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string
  options: { value: string; label: string }[]
  onChange: (value: string) => void
}) {
  return (
    <div className="grid gap-1">
      <Label className="text-xs">{label}</Label>
      <Select value={value} onValueChange={(v) => v != null && onChange(v)}>
        <SelectTrigger size="sm" className="w-full">
          <SelectValue>{(v: string | null) => options.find((o) => o.value === v)?.label ?? v}</SelectValue>
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

function TextOption({
  label,
  value,
  placeholder,
  onChange,
}: {
  label: string
  value: string
  placeholder?: string
  onChange: (value: string) => void
}) {
  return (
    <label className="grid gap-1">
      <span className="text-xs font-medium">{label}</span>
      <Input className="h-8 font-mono text-xs" value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
    </label>
  )
}

// Editor delle regole di naming di un tracker (docs/SPEC.md §9): le
// variabili sono le stesse per tutti i tracker, qui si scrive solo in che
// ordine e forma usarle. Un clic su una variabile la inserisce dove c'è il
// cursore; sotto ogni template il nome che ne esce, dal vivo.
export function NamingRulesEditor({
  trackerId,
  value,
  onChange,
}: {
  trackerId: number
  value: NamingRules
  onChange: (rules: NamingRules) => void
}) {
  const templates = value.templates ?? {}
  const inputs = useRef<Record<string, HTMLInputElement | null>>({})
  const [focused, setFocused] = useState<string>('default')
  const debounced = useDebounced(value, 400)
  const { data: preview, isError } = useNamingPreview(trackerId, debounced)

  const set = (patch: Partial<NamingRules>) => onChange({ ...value, ...patch })
  // Un pattern per tipo resta finché non lo si rimuove, anche se vuoto
  // mentre lo si scrive (vuoto = usa quello principale).
  const setTemplate = (key: string, template: string) => set({ templates: { ...templates, [key]: template } })
  const shownKeys = TEMPLATE_KEYS.filter((key) => key === 'default' || key in templates)
  const missingKeys = TEMPLATE_KEYS.filter((key) => key !== 'default' && !(key in templates))
  const addTemplate = (key: string) => {
    set({ templates: { ...templates, [key]: templates.default ?? '' } })
    setFocused(key)
  }
  const removeTemplate = (key: string) => {
    const next = { ...templates }
    delete next[key]
    set({ templates: next })
    if (focused === key) setFocused('default')
  }
  const typeLabels = (value.type_labels as Record<string, string> | undefined) ?? {}
  // Un'etichetta vuota nel campo = quella di default; per non scrivere il
  // tipo si lascia l'etichetta del profilo a "" (come fa ITT per gli encode).
  const setTypeLabel = (key: string, label: string) => {
    const next = { ...typeLabels }
    if (label) next[key] = label
    else delete next[key]
    set({ type_labels: next })
  }
  const setLanguages = (field: 'audio_languages' | 'subs_languages', patch: Record<string, unknown>) =>
    set({ [field]: { ...(value[field] ?? {}), ...patch } })

  function insert(variable: string) {
    const input = inputs.current[focused]
    const current = templates[focused] ?? ''
    const start = input?.selectionStart ?? current.length
    const end = input?.selectionEnd ?? current.length
    const token = `{${variable}}`
    const before = current.slice(0, start)
    const spaced = before && !before.endsWith(' ') ? ` ${token}` : token
    setTemplate(focused, `${before}${spaced}${current.slice(end)}`)
    requestAnimationFrame(() => {
      input?.focus()
      const caret = start + spaced.length
      input?.setSelectionRange(caret, caret)
    })
  }

  const languageStyles = [
    { value: 'none', label: t('naming.languages.none') },
    { value: 'all', label: t('naming.languages.all') },
    { value: 'primary_first', label: t('naming.languages.primary_first') },
  ]

  return (
    <div className="grid gap-4">
      <div className="grid gap-1.5">
        <p className="text-xs text-muted-foreground">{t('naming.variablesHelp')}</p>
        <div className="flex flex-wrap gap-1">
          {VARIABLE_NAMES.map((name) => (
            <button
              key={name}
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => insert(name)}
              title={preview?.variables[name] ?? t('naming.noValue')}
              className="rounded border bg-muted px-1.5 py-0.5 font-mono text-[11px] hover:border-primary hover:text-primary"
            >
              {`{${name}}`}
            </button>
          ))}
        </div>
      </div>

      <div className="grid gap-3">
        {shownKeys.map((key) => {
          const own = templates[key] ?? ''
          const shown = preview?.names[key]
          return (
            <div key={key} className="grid gap-1">
              <div className="flex items-center justify-between gap-2">
                <Label htmlFor={`template-${key}`} className="text-xs">
                  {key === 'default' ? t('naming.mainPattern') : t('naming.patternFor', { type: t(`naming.template.${key}`) })}
                </Label>
                {key !== 'default' && (
                  <button
                    type="button"
                    className="text-[11px] text-muted-foreground hover:text-destructive"
                    onClick={() => removeTemplate(key)}
                  >
                    {t('naming.removePattern')}
                  </button>
                )}
              </div>
              <Input
                id={`template-${key}`}
                ref={(node) => {
                  inputs.current[key] = node
                }}
                className={cn('h-8 font-mono text-xs', focused === key && 'ring-1 ring-primary/40')}
                value={own}
                placeholder={key === 'default' ? '{title} ({year}) {season} {resolution} {source} {video_codec} {audio} {group}' : ''}
                onFocus={() => setFocused(key)}
                onChange={(e) => setTemplate(key, e.target.value)}
              />
              {shown && <p className="font-mono text-[11px] break-all text-muted-foreground">→ {shown}</p>}
            </div>
          )
        })}
        {missingKeys.length > 0 && (
          <div className="flex items-center gap-2">
            <Select value={null} onValueChange={(key) => key && addTemplate(key)}>
              <SelectTrigger size="sm" className="w-auto">
                <SelectValue placeholder={t('naming.addPatternFor')}>{() => t('naming.addPatternFor')}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                {missingKeys.map((key) => (
                  <SelectItem key={key} value={key}>
                    {t(`naming.template.${key}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <span className="text-[11px] text-muted-foreground">{t('naming.addPatternHelp')}</span>
          </div>
        )}
        {preview && (
          <p className="text-[11px] break-words text-muted-foreground">
            {preview.sample.kind === 'job'
              ? t('naming.previewOnJob', { label: preview.sample.label })
              : t('naming.previewOnExample')}
          </p>
        )}
        {preview && (preview.examples?.length ?? 0) > 0 && (
          <div className="grid gap-2 rounded-md border bg-muted/30 p-3">
            <p className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
              {t('naming.examplesTitle')}
            </p>
            <ul className="grid gap-2">
              {preview.examples.map((example) => (
                <li key={example.key} className="grid gap-0.5">
                  <span className="text-[11px] text-muted-foreground">
                    {example.kind === 'job' ? t('naming.exampleJob', { label: example.label }) : example.label}
                  </span>
                  <span className="font-mono text-xs break-all">{example.name}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {isError && <p className="text-[11px] text-destructive">{t('naming.previewFailed')}</p>}
      </div>

      <Group title={t('naming.group.title')}>
        <OptionSelect
          label={t('naming.title')}
          value={String(value.title ?? 'original')}
          options={[
            { value: 'original', label: t('naming.titleOriginal') },
            { value: 'local', label: t('naming.titleLocal') },
            { value: 'local_original', label: t('naming.titleBoth') },
          ]}
          onChange={(title) => set({ title })}
        />
        <p className="text-[11px] text-muted-foreground sm:col-span-2">{t('naming.trackerLanguageNote')}</p>
      </Group>

      {(['audio_languages', 'subs_languages'] as const).map((field) => (
        <Group key={field} title={t(`naming.group.${field}`)}>
          <OptionSelect
            label={t('naming.languagesStyle')}
            value={value[field]?.style ?? (field === 'subs_languages' ? 'all' : 'none')}
            options={languageStyles}
            onChange={(style) => setLanguages(field, { style })}
          />
          <TextOption
            label={t('naming.multiFrom')}
            value={value[field]?.multi_from != null ? String(value[field]!.multi_from) : ''}
            placeholder="3"
            onChange={(raw) => setLanguages(field, { multi_from: /^\d+$/.test(raw) ? Number(raw) : undefined })}
          />
        </Group>
      ))}

      <Group title={t('naming.group.labels')}>
        <OptionSelect
          label={t('naming.subsStyle')}
          value={String(value.subs_style ?? 'format')}
          options={[
            { value: 'format', label: t('naming.subsStyleFormat') },
            { value: 'tracker_language', label: t('naming.subsStyleTrackerLanguage') },
          ]}
          onChange={(style) => set({ subs_style: style === 'format' ? null : style })}
        />
        <TextOption
          label={t('naming.subsFormat')}
          value={String(value.subs_format ?? value.subs_label ?? '')}
          placeholder="SUBS {subs_languages}"
          onChange={(format) => {
            const next: NamingRules = { ...value, subs_format: format || undefined }
            delete next.subs_label
            if (!format) delete next.subs_format
            onChange(next)
          }}
        />
        <TextOption label={t('naming.sdrLabel')} value={String(value.sdr_label ?? '')} placeholder="SDR" onChange={(label) => set({ sdr_label: label || null })} />
        <TextOption label={t('naming.separator')} value={String(value.separator ?? ' ')} onChange={(separator) => set({ separator: separator || ' ' })} />
        <TextOption label={t('naming.groupSeparator')} value={String(value.group_separator ?? '-')} onChange={(separator) => set({ group_separator: separator || '-' })} />
      </Group>

      <fieldset className="grid gap-3 rounded-md border p-3">
        <legend className="px-1 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
          {t('naming.group.formats')}
        </legend>
        <div className="grid gap-1">
          <Label className="text-xs">{t('naming.typeLabels')}</Label>
          <p className="text-[11px] text-muted-foreground">{t('naming.typeLabelsHelp')}</p>
          <div className="grid gap-2 sm:grid-cols-4">
            {TEMPLATE_KEYS.filter((key) => key !== 'default' && key !== 'tv').map((key) => (
              <TextOption
                key={key}
                label={t(`naming.template.${key}`)}
                value={typeLabels[key] ?? ''}
                placeholder={key in typeLabels ? t('naming.notWritten') : DEFAULT_TYPE_LABELS[key] || t('naming.notWritten')}
                onChange={(label) => setTypeLabel(key, label)}
              />
            ))}
          </div>
        </div>
        <AudioCodecNames value={(value.audio_codecs as Record<string, string> | undefined) ?? {}} onChange={(audio_codecs) => set({ audio_codecs })} />
      </fieldset>
    </div>
  )
}

// "Formato dei valori": come scrivere i codec audio (formato MediaInfo ->
// nome nel titolo), es. E-AC-3 -> DDP invece di DD+. Una riga per codec.
function AudioCodecNames({ value, onChange }: { value: Record<string, string>; onChange: (value: Record<string, string>) => void }) {
  const [draft, setDraft] = useState(() => Object.entries(value).map(([k, v]) => `${k} = ${v}`).join('\n'))
  return (
    <div className="grid gap-1">
      <Label className="text-xs">{t('naming.audioCodecNames')}</Label>
      <p className="text-[11px] text-muted-foreground">{t('naming.audioCodecNamesHelp')}</p>
      <Textarea
        rows={3}
        className="font-mono text-xs"
        placeholder={'E-AC-3 = DDP\nAC-3 = DD'}
        value={draft}
        onChange={(e) => {
          setDraft(e.target.value)
          const parsed: Record<string, string> = {}
          for (const line of e.target.value.split('\n')) {
            const [from, to] = line.split('=').map((part) => part?.trim())
            if (from && to) parsed[from] = to
          }
          onChange(parsed)
        }}
      />
    </div>
  )
}
