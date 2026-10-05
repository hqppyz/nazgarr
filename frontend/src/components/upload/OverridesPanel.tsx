import { TriangleAlertIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { useUpdateOverrides, type UploadJob } from '@/api/hooks/uploads'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { t } from '@/lib/i18n'
import { sourceMissing } from '@/lib/upload'
import { cn } from '@/lib/utils'

// Stessi campi di nazgarr/upload/naming.py DETECTED_FIELDS, più l'anno.
const DETECTED_FIELDS = [
  'type', 'resolution', 'source', 'video_codec', 'audio', 'audio_languages', 'hdr', 'service', 'edition', 'repack', 'hybrid',
  'group',
] as const

type Draft = Record<string, string | boolean>

function toDraft(overrides: Record<string, unknown>): Draft {
  const draft: Draft = {}
  for (const [key, value] of Object.entries(overrides)) draft[key] = typeof value === 'boolean' ? value : String(value)
  return draft
}

// Solo i quattro id sono sempre visibili (pagina di creazione): qui i valori
// rilevati per il nome. Chiuso: i valori come tag. Aperto: una riga per
// campo, etichetta e valore, con il valore rilevato come placeholder; si
// scrive solo dove è sbagliato. Salvando si rifanno i nomi proposti.
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
  const changed = [...DETECTED_FIELDS, 'year'].filter((key) => saved[key]).length

  const text = (key: string) => (typeof draft[key] === 'string' ? (draft[key] as string) : '')
  const set = (key: string, value: string | boolean) =>
    setDraft((prev) => {
      const next = { ...prev }
      if (value === '' || value === false) delete next[key]
      else next[key] = value
      return next
    })
  const missingSource = sourceMissing(job)
  const detectedOf = (key: string) => (key === 'year' ? (job.year != null ? String(job.year) : null) : detected[key])

  const row = (key: string, placeholder: string | null | undefined) => (
    <label key={key} className="grid min-w-0 grid-cols-[7rem_minmax(0,1fr)] items-center gap-2">
      <span className="truncate text-xs text-muted-foreground">{t(`upload.overrides.field.${key}`)}</span>
      <Input
        id={`override-${key}`}
        className={cn(
          'h-7 px-2 font-mono text-xs pointer-coarse:h-9', // più alto al tocco (il font sale già a 16px)
          text(key) ? 'border-primary/60 bg-primary/5' : 'border-transparent bg-muted/60 shadow-none',
          key === 'source' && missingSource && !text(key) && 'border-amber-500/70',
        )}
        placeholder={placeholder ?? (key === 'source' && missingSource ? t('upload.overrides.sourcePlaceholder') : '—')}
        value={text(key)}
        onChange={(e) => set(key, e.target.value)}
        list={options[key]?.length ? `override-options-${key}` : undefined}
      />
      {options[key]?.length ? (
        <datalist id={`override-options-${key}`}>
          {options[key].map((value) => (
            <option key={value} value={value} />
          ))}
        </datalist>
      ) : null}
    </label>
  )

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
                return (
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
