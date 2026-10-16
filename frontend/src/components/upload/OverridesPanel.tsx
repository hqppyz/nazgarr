import { RotateCcwIcon, TriangleAlertIcon, XIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { useUpdateOverrides, type UploadJob } from '@/api/hooks/uploads'
import { InfoPopover } from '@/components/InfoPopover'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { t } from '@/lib/i18n'
import { CLEARABLE_FIELDS, sourceMissing } from '@/lib/upload'
import { cn } from '@/lib/utils'

// Stessi campi di nazgarr/upload/naming.py DETECTED_FIELDS, più l'anno.
const DETECTED_FIELDS = [
  'type', 'resolution', 'source', 'video_codec', 'audio', 'audio_languages', 'hdr', 'service', 'edition', 'repack', 'hybrid',
  'group',
] as const

// cleared: i campi tolti dal nome (nazgarr/upload/naming.py CLEARABLE_FIELDS).
type Draft = Record<string, string | boolean | string[]>

function toDraft(overrides: Record<string, unknown>): Draft {
  const draft: Draft = {}
  for (const [key, value] of Object.entries(overrides)) {
    draft[key] = typeof value === 'boolean' ? value : Array.isArray(value) ? value.map(String) : String(value)
  }
  return draft
}

const clearable = (key: string) => (CLEARABLE_FIELDS as readonly string[]).includes(key)

type TypeBasis = { type: string; source: string | null; evidence: string[]; encoder: string | null }

// Perché il tipo (REMUX, ENCODE...) e la sorgente sono quelli rilevati
// (nazgarr/upload/naming.py release_values): nel popover del tag del tipo,
// niente in più a schermo.
function TypeBasisText({ basis }: { basis: TypeBasis }) {
  return (
    <div className="grid gap-1.5">
      <p>
        {basis.type === 'encoder' && !basis.encoder
          ? t('upload.typeBasis.type.encoderSettings') // solo le impostazioni di encoding, senza la libreria
          : t(`upload.typeBasis.type.${basis.type}`, { encoder: basis.encoder ?? '' })}
      </p>
      {basis.source && <p>{t(`upload.typeBasis.source.${basis.source}`)}</p>}
      {basis.evidence.length > 0 && (
        <div>
          <p className="text-muted-foreground">{t('upload.typeBasis.evidence')}</p>
          <ul className="list-disc pl-4">
            {basis.evidence.map((code) => (
              <li key={code}>{t(`upload.typeBasis.signal.${code}`)}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

// Solo i quattro id sono sempre visibili (pagina di creazione): qui i valori
// rilevati per il nome. Chiuso: i valori come tag. Aperto: una riga per
// campo, etichetta e valore, con il valore rilevato come placeholder; si
// scrive solo dove è sbagliato, e la X toglie un valore rilevato per sbaglio
// (un campo vuoto torna a quello rilevato). Salvando si rifanno i nomi proposti.
// open/onOpenChange: aperto da fuori (l'avviso della sorgente mancante
// sopra il nome o nella conferma); senza, lo gestisce da solo.
export function OverridesPanel({
  job,
  open: openProp,
  onOpenChange,
}: {
  job: UploadJob
  open?: boolean
  onOpenChange?: (open: boolean) => void
}) {
  const analysis = (job.analysis ?? {}) as Record<string, unknown>
  const detected = (analysis.detected ?? {}) as Record<string, string | null>
  // I valori che i tracker del job accettano (nazgarr/upload/decision.py
  // field_options): un menu nel campo, che resta libero.
  const options = (analysis.field_options ?? {}) as Record<string, string[]>
  const nameSource = analysis.name_source as { name: string; origin: string } | undefined
  const typeBasis = analysis.type_basis as TypeBasis | undefined
  const [draft, setDraft] = useState<Draft>(() => toDraft(job.overrides))
  const [openState, setOpenState] = useState(false)
  const open = openProp ?? openState
  const setOpen = (next: boolean) => {
    setOpenState(next)
    onOpenChange?.(next)
  }
  const save = useUpdateOverrides(job.id)
  const saved = toDraft(job.overrides)
  const dirty = JSON.stringify(draft) !== JSON.stringify(saved)
  const savedCleared = (saved.cleared as string[] | undefined) ?? []
  const changed = [...DETECTED_FIELDS, 'year'].filter((key) => saved[key] || savedCleared.includes(key)).length
  const cleared = (draft.cleared as string[] | undefined) ?? []

  const text = (key: string) => (typeof draft[key] === 'string' ? (draft[key] as string) : '')
  // Un valore scritto in un campo tolto lo rimette nel nome.
  const withCleared = (next: Draft, keys: string[]) => {
    if (keys.length) next.cleared = keys
    else delete next.cleared
    return next
  }
  const set = (key: string, value: string | boolean) =>
    setDraft((prev) => {
      const next = { ...prev }
      if (value === '' || value === false) delete next[key]
      else next[key] = value
      const keys = ((prev.cleared as string[] | undefined) ?? []).filter((k) => k !== key || value === '')
      return withCleared(next, keys)
    })
  const setCleared = (key: string, on: boolean) =>
    setDraft((prev) => {
      const next = { ...prev }
      delete next[key]
      const keys = ((prev.cleared as string[] | undefined) ?? []).filter((k) => k !== key)
      return withCleared(next, on ? [...keys, key] : keys)
    })
  const missingSource = sourceMissing(job)
  const detectedOf = (key: string) => (key === 'year' ? (job.year != null ? String(job.year) : null) : detected[key])

  const row = (key: string, placeholder: string | null | undefined) => {
    const isCleared = cleared.includes(key)
    const field = t(`upload.overrides.field.${key}`)
    return (
      <div key={key} className="grid min-w-0 grid-cols-[7rem_minmax(0,1fr)_auto] items-center gap-2">
        <label htmlFor={`override-${key}`} className="truncate text-xs text-muted-foreground">{field}</label>
        <Input
          id={`override-${key}`}
          className={cn(
            'h-7 px-2 font-mono text-xs pointer-coarse:h-9', // più alto al tocco (il font sale già a 16px)
            text(key) || isCleared ? 'border-primary/60 bg-primary/5' : 'border-transparent bg-muted/60 shadow-none',
            isCleared && 'placeholder:text-primary/80 placeholder:italic',
            key === 'source' && missingSource && !text(key) && 'border-amber-500/70',
          )}
          placeholder={
            isCleared
              ? t('upload.overrides.none')
              : (placeholder ?? (key === 'source' && missingSource ? t('upload.overrides.sourcePlaceholder') : '—'))
          }
          value={text(key)}
          onChange={(e) => set(key, e.target.value)}
          list={options[key]?.length ? `override-options-${key}` : undefined}
        />
        {clearable(key) &&
          (isCleared ? (
            <Button
              type="button"
              size="icon-xs"
              variant="ghost"
              aria-label={t('upload.overrides.restore', { field })}
              title={t('upload.overrides.restoreHelp')}
              onClick={() => setCleared(key, false)}
            >
              <RotateCcwIcon />
            </Button>
          ) : (
            <Button
              type="button"
              size="icon-xs"
              variant="ghost"
              aria-label={t('upload.overrides.clear', { field })}
              title={t('upload.overrides.clearHelp')}
              disabled={!text(key) && !placeholder}
              onClick={() => setCleared(key, true)}
            >
              <XIcon />
            </Button>
          ))}
        {options[key]?.length ? (
          <datalist id={`override-options-${key}`}>
            {options[key].map((value) => (
              <option key={value} value={value} />
            ))}
          </datalist>
        ) : null}
      </div>
    )
  }

  return (
    <Card id="upload-overrides" className="min-w-0 scroll-mt-20">
      <Collapsible open={open} onOpenChange={setOpen}>
        <CardHeader className="grid gap-2">
          <CollapsibleTrigger className="flex items-center gap-2 text-left">
            <CardTitle className="text-base">{t('upload.overrides.title')}</CardTitle>
            {changed > 0 && (
              <span className="rounded bg-primary/15 px-1.5 text-xs text-primary">
                {t('upload.overrides.changed', { count: changed })}
              </span>
            )}
            <span className="ml-auto text-xs text-muted-foreground hover:text-foreground">
              {open ? t('upload.overrides.close') : t('upload.overrides.edit')}
            </span>
          </CollapsibleTrigger>
          {nameSource && (
            <p className="min-w-0 truncate text-xs text-muted-foreground" title={nameSource.name}>
              {t(`upload.overrides.readFrom.${nameSource.origin}`)}{' '}
              <span className="font-mono">{nameSource.name}</span>
            </p>
          )}
          {missingSource && (
            <div className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-xs">
              <TriangleAlertIcon className="mt-0.5 size-3.5 shrink-0 text-amber-500" />
              <span className="min-w-0 flex-1">{t('upload.overrides.missingSource')}</span>
              {!open && (
                <button type="button" className="shrink-0 font-medium underline" onClick={() => setOpen(true)}>
                  {t('upload.overrides.setSource')}
                </button>
              )}
            </div>
          )}
          {!open && (
            <div className="flex flex-wrap gap-1.5">
              {[...DETECTED_FIELDS, 'year' as const].map((key) => {
                const override = typeof saved[key] === 'string' ? (saved[key] as string) : ''
                const value = override || detectedOf(key)
                if (!value) return null
                // Tolto a mano: il valore rilevato barrato, fuori dal nome.
                if (savedCleared.includes(key)) {
                  return (
                    <span
                      key={key}
                      title={t('upload.overrides.clearedTag', { field: t(`upload.overrides.field.${key}`) })}
                      className="rounded-md border border-primary/50 bg-primary/10 px-2 py-1 font-mono text-xs text-primary/80 line-through"
                    >
                      {value}
                    </span>
                  )
                }
                const tag = (
                  <span
                    key={key}
                    title={t(`upload.overrides.field.${key}`)}
                    className={cn(
                      'rounded-md border px-2 py-1 font-mono text-xs',
                      override ? 'border-primary/50 bg-primary/10 text-primary' : 'bg-muted text-muted-foreground',
                    )}
                  >
                    {value}
                  </span>
                )
                // Il tipo rilevato (non uno scritto a mano) spiega da dove viene.
                if (key === 'type' && typeBasis && !override) {
                  return (
                    <InfoPopover key={key} content={<TypeBasisText basis={typeBasis} />} className="pointer-coarse:m-0 pointer-coarse:p-0">
                      {tag}
                    </InfoPopover>
                  )
                }
                return tag
              })}
            </div>
          )}
        </CardHeader>
        <CollapsibleContent>
          <CardContent className="grid gap-4">
            <p className="text-xs text-muted-foreground">{t('upload.overrides.description')}</p>
            <div className="grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
              {DETECTED_FIELDS.map((key) => row(key, detected[key]))}
              {row('year', job.year != null ? String(job.year) : null)}
            </div>
            <div className="grid gap-1.5 border-t pt-3">
              <p className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
                {t('upload.overrides.advanced')}
              </p>
              <div className="grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
                {row('screenshot_count', t('upload.overrides.screenshotDefault'))}
                <label className="grid grid-cols-[7rem_minmax(0,1fr)] items-center gap-2">
                  <span className="truncate text-xs text-muted-foreground">{t('upload.overrides.noSeed')}</span>
                  <Switch size="sm" checked={draft.no_seed === true} onCheckedChange={(checked) => set('no_seed', checked)} />
                </label>
              </div>
              <Textarea
                rows={2}
                className="font-mono text-xs"
                placeholder={t('upload.overrides.field.notes')}
                value={text('notes')}
                onChange={(e) => set('notes', e.target.value)}
              />
            </div>
            <div className="flex justify-end gap-2">
              {dirty && (
                <Button size="sm" variant="ghost" onClick={() => setDraft(saved)}>
                  {t('upload.overrides.discard')}
                </Button>
              )}
              <Button
                size="sm"
                disabled={!dirty || save.isPending}
                onClick={() =>
                  save.mutate(draft, {
                    onSuccess: () => toast.success(t('upload.overrides.saved')),
                    onError: (error) => toast.error(error.message),
                  })
                }
              >
                {t('upload.overrides.save')}
              </Button>
            </div>
          </CardContent>
        </CollapsibleContent>
      </Collapsible>
    </Card>
  )
}
