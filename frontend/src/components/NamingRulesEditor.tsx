import { useEffect, useRef, useState } from 'react'

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
const TEMPLATE_KEYS = ['default', 'REMUX', 'WEBDL', 'WEBRIP', 'ENCODE', 'HDTV', 'DVDRIP', 'BRRIP'] as const
// Stesso ordine di app/upload_naming.py VARIABLES.
const VARIABLE_NAMES = [
  'title', 'local_title', 'year', 'season', 'episode', 'edition', 'repack', 'resolution', 'source', 'type',
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
    <div className="grid gap-1">
      <Label className="text-xs">{label}</Label>
      <Input className="h-8 font-mono text-xs" value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
    </div>
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
  const setTemplate = (key: string, template: string) => {
    const next = { ...templates }
    if (template.trim()) next[key] = template
    else delete next[key]
    set({ templates: next })
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
        {TEMPLATE_KEYS.map((key) => {
          const own = templates[key] ?? ''
          const shown = preview?.names[key]
          return (
            <div key={key} className="grid gap-1">
              <Label htmlFor={`template-${key}`} className="text-xs">
                {t(`naming.template.${key}`)}
              </Label>
              <Input
                id={`template-${key}`}
                ref={(node) => {
                  inputs.current[key] = node
                }}
                className={cn('h-8 font-mono text-xs', focused === key && 'ring-1 ring-primary/40')}
                value={own}
                placeholder={key === 'default' ? '{title} ({year}) {season} {resolution} {source} {video_codec} {audio} {group}' : t('naming.usesDefault')}
                onFocus={() => setFocused(key)}
                onChange={(e) => setTemplate(key, e.target.value)}
              />
              {own && shown && <p className="truncate font-mono text-[11px] text-muted-foreground" title={shown}>→ {shown}</p>}
            </div>
          )
        })}
        {preview && (
          <p className="text-[11px] text-muted-foreground">
            {preview.sample.kind === 'job'
              ? t('naming.previewOnJob', { label: preview.sample.label })
              : t('naming.previewOnExample')}
          </p>
        )}
        {isError && <p className="text-[11px] text-destructive">{t('naming.previewFailed')}</p>}
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
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
        <TextOption
          label={t('naming.titleLanguage')}
          value={String(value.title_language ?? '')}
          placeholder="it"
          onChange={(language) => set({ title_language: language || null })}
        />
        <TextOption label={t('naming.separator')} value={String(value.separator ?? ' ')} onChange={(separator) => set({ separator: separator || ' ' })} />
        <OptionSelect
          label={t('naming.audioLanguages')}
          value={value.audio_languages?.style ?? 'none'}
          options={languageStyles}
          onChange={(style) => setLanguages('audio_languages', { style })}
        />
        <TextOption
          label={t('naming.primaryLanguage')}
          value={value.audio_languages?.primary ?? ''}
          placeholder="ITA"
          onChange={(primary) => {
            setLanguages('audio_languages', { primary: primary.toUpperCase() || undefined })
          }}
        />
        <TextOption
          label={t('naming.multiFrom')}
          value={value.audio_languages?.multi_from != null ? String(value.audio_languages.multi_from) : ''}
          placeholder="3"
          onChange={(raw) => setLanguages('audio_languages', { multi_from: /^\d+$/.test(raw) ? Number(raw) : undefined })}
        />
        <OptionSelect
          label={t('naming.subsLanguages')}
          value={value.subs_languages?.style ?? 'all'}
          options={languageStyles}
          onChange={(style) => setLanguages('subs_languages', { style, primary: value.audio_languages?.primary })}
        />
        <TextOption label={t('naming.subsLabel')} value={String(value.subs_label ?? '')} placeholder="SUBS" onChange={(label) => set({ subs_label: label || null })} />
        <TextOption label={t('naming.sdrLabel')} value={String(value.sdr_label ?? '')} placeholder="SDR" onChange={(label) => set({ sdr_label: label || null })} />
        <TextOption label={t('naming.groupSeparator')} value={String(value.group_separator ?? '-')} onChange={(separator) => set({ group_separator: separator || '-' })} />
      </div>

      <AudioCodecNames value={(value.audio_codecs as Record<string, string> | undefined) ?? {}} onChange={(audio_codecs) => set({ audio_codecs })} />
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
