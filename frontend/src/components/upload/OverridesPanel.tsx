import { ChevronRightIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { useUpdateOverrides, type UploadJob } from '@/api/hooks/uploads'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { t } from '@/lib/i18n'
import { cn } from '@/lib/utils'

// Stessi campi di app/upload_naming.py DETECTED_FIELDS, più l'anno.
const DETECTED_FIELDS = [
  'type', 'resolution', 'source', 'video_codec', 'audio_codec', 'hdr', 'service', 'edition', 'repack', 'group',
] as const

type Draft = Record<string, string | boolean>

function toDraft(overrides: Record<string, unknown>): Draft {
  const draft: Draft = {}
  for (const [key, value] of Object.entries(overrides)) draft[key] = typeof value === 'boolean' ? value : String(value)
  return draft
}

// Solo i quattro id sono sempre visibili (pagina di creazione): qui i valori
// rilevati dal nome della sorgente, ognuno con il suo valore come
// placeholder, da toccare solo dove è sbagliato. Salvando si rifanno i nomi
// proposti per ogni tracker.
export function OverridesPanel({ job }: { job: UploadJob }) {
  const analysis = (job.analysis ?? {}) as Record<string, unknown>
  const detected = (analysis.detected ?? {}) as Record<string, string | null>
  const nameSource = analysis.name_source as { name: string; origin: string } | undefined
  const [draft, setDraft] = useState<Draft>(() => toDraft(job.overrides))
  const save = useUpdateOverrides(job.id)
  const saved = toDraft(job.overrides)
  const dirty = JSON.stringify(draft) !== JSON.stringify(saved)
  const changed = DETECTED_FIELDS.filter((key) => draft[key]).length + (draft.year ? 1 : 0)

  const text = (key: string) => (typeof draft[key] === 'string' ? (draft[key] as string) : '')
  const set = (key: string, value: string | boolean) =>
    setDraft((prev) => {
      const next = { ...prev }
      if (value === '' || value === false) delete next[key]
      else next[key] = value
      return next
    })

  const field = (key: string, placeholder: string | null | undefined, className?: string) => (
    <div key={key} className={cn('grid gap-1', className)}>
      <Label htmlFor={`override-${key}`} className="text-xs">
        {t(`upload.overrides.field.${key}`)}
      </Label>
      <Input
        id={`override-${key}`}
        className={cn('h-8 font-mono text-xs', text(key) && 'border-primary ring-1 ring-primary/40')}
        placeholder={placeholder ?? '—'}
        value={text(key)}
        onChange={(e) => set(key, e.target.value)}
      />
    </div>
  )

  return (
    <Card>
      <Collapsible defaultOpen={changed > 0}>
        <CardHeader>
          <CollapsibleTrigger className="group flex items-center gap-2 text-left">
            <ChevronRightIcon className="size-4 transition-transform group-data-[panel-open]:rotate-90" />
            <CardTitle className="text-base">{t('upload.overrides.title')}</CardTitle>
            {changed > 0 && (
              <span className="rounded bg-primary/15 px-1.5 text-xs text-primary">
                {t('upload.overrides.changed', { count: changed })}
              </span>
            )}
          </CollapsibleTrigger>
          {nameSource && (
            <p className="min-w-0 truncate text-xs text-muted-foreground" title={nameSource.name}>
              {t(`upload.overrides.readFrom.${nameSource.origin}`)}{' '}
              <span className="font-mono">{nameSource.name}</span>
            </p>
          )}
          {/* Chiuso: i valori usati per il nome come tag, quelli cambiati a mano
              in evidenza. Aperto: i campi per correggerli. */}
          <div className="flex flex-wrap gap-1.5 pt-1">
            {[...DETECTED_FIELDS, 'year' as const].map((key) => {
              const override = typeof saved[key] === 'string' ? (saved[key] as string) : ''
              const value = override || (key === 'year' ? (job.year != null ? String(job.year) : null) : detected[key])
              if (!value) return null
              return (
                <span
                  key={key}
                  title={t(`upload.overrides.field.${key}`)}
                  className={cn(
                    'rounded border px-1.5 py-0.5 font-mono text-[11px]',
                    override ? 'border-primary/50 bg-primary/10 text-primary' : 'bg-muted text-muted-foreground',
                  )}
                >
                  {value}
                </span>
              )
            })}
          </div>
        </CardHeader>
        <CollapsibleContent>
          <CardContent className="grid gap-5">
            <CardDescription>{t('upload.overrides.description')}</CardDescription>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
              {DETECTED_FIELDS.map((key) => field(key, detected[key]))}
              {field('year', job.year != null ? String(job.year) : null)}
            </div>
            <Collapsible>
              <CollapsibleTrigger className="text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground">
                {t('upload.overrides.advanced')}
              </CollapsibleTrigger>
              <CollapsibleContent className="grid gap-4 pt-3 sm:grid-cols-2">
                {field('screenshot_count', t('upload.overrides.screenshotDefault'))}
                <div className="flex items-center gap-2 self-end pb-1.5">
                  <Switch
                    id="override-no_seed"
                    checked={draft.no_seed === true}
                    onCheckedChange={(checked) => set('no_seed', checked)}
                  />
                  <Label htmlFor="override-no_seed" className="text-xs">
                    {t('upload.overrides.noSeed')}
                  </Label>
                </div>
                <div className="grid gap-1 sm:col-span-2">
                  <Label htmlFor="override-notes" className="text-xs">
                    {t('upload.overrides.field.notes')}
                  </Label>
                  <Textarea
                    id="override-notes"
                    rows={3}
                    className="font-mono text-xs"
                    value={text('notes')}
                    onChange={(e) => set('notes', e.target.value)}
                  />
                </div>
              </CollapsibleContent>
            </Collapsible>
            <div className="flex gap-2">
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
              {dirty && (
                <Button size="sm" variant="ghost" onClick={() => setDraft(saved)}>
                  {t('upload.overrides.discard')}
                </Button>
              )}
            </div>
          </CardContent>
        </CollapsibleContent>
      </Collapsible>
    </Card>
  )
}
