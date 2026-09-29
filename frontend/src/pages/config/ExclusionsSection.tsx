import { useQueryClient } from '@tanstack/react-query'
import { InfoIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { useExclusionPresets, useSetSetting, useSetting } from '@/api/hooks/settings'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { t } from '@/lib/i18n'
import { autosaveFeedback } from '@/lib/autosave'

// Stesse chiavi app_settings che app/api/library.py già legge
// (_load_exclusions): i preset come elenco di chiavi separate da virgola,
// i pattern personalizzati uno per riga — nessun formato nuovo lato backend.
const PRESETS_KEY = 'exclusion_presets'
const PATTERNS_KEY = 'exclusion_patterns'

function parsePresetKeys(raw: string | null | undefined): string[] {
  return (raw ?? '')
    .split(',')
    .map((key) => key.trim())
    .filter(Boolean)
}

// Lo stato "excluded" di ogni file è calcolato a ogni richiesta dalle API
// della libreria, non salvato: basta invalidarle perché le viste ad albero
// riflettano subito le nuove esclusioni, senza un nuovo scan.
function useInvalidateLibrary() {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries({ queryKey: ['library'] })
}

function PresetsCard() {
  const { data: presets } = useExclusionPresets()
  const { data: setting } = useSetting(PRESETS_KEY)
  const setSetting = useSetSetting(PRESETS_KEY)
  const invalidateLibrary = useInvalidateLibrary()
  // Mai salvato (null): valgono i preset attivi di default lato backend
  // (app/exclusions.py DEFAULT_ENABLED_PRESETS), la UI deve mostrare gli stessi.
  const enabled =
    setting?.value == null
      ? (presets ?? []).filter((p) => p.enabled_by_default).map((p) => p.key)
      : parsePresetKeys(setting.value)

  const toggle = (key: string, on: boolean) => {
    const next = on ? [...enabled.filter((k) => k !== key), key] : enabled.filter((k) => k !== key)
    setSetting.mutate(next.join(','), {
      onSuccess: () => {
        invalidateLibrary()
        autosaveFeedback(t(`exclusions.preset.${key}`)).onSuccess()
      },
      onError: autosaveFeedback(t(`exclusions.preset.${key}`)).onError,
    })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('exclusions.presetsTitle')}</CardTitle>
        <CardDescription>{t('exclusions.presetsDescription')}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        {presets?.map((preset) => (
          <div key={preset.key} className="flex items-start gap-3">
            <Switch
              id={`preset-${preset.key}`}
              checked={enabled.includes(preset.key)}
              onCheckedChange={(on) => toggle(preset.key, on)}
              disabled={setSetting.isPending}
              className="mt-0.5"
            />
            <div className="grid min-w-0 gap-1.5">
              <Label htmlFor={`preset-${preset.key}`}>{t(`exclusions.preset.${preset.key}`)}</Label>
              <div className="flex flex-wrap gap-1">
                {preset.patterns.map((pattern) => (
                  <code key={pattern} className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">
                    {pattern}
                  </code>
                ))}
              </div>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

function CustomPatternsCard() {
  const { data } = useSetting(PATTERNS_KEY)
  const setSetting = useSetSetting(PATTERNS_KEY)
  const invalidateLibrary = useInvalidateLibrary()
  const [draft, setDraft] = useState<string | null>(null)
  const value = draft ?? data?.value ?? ''

  const save = () => {
    // Righe vuote e spazi ai bordi scartati come fa già il backend
    // (parse_custom_patterns), così il valore salvato è quello effettivo.
    const normalized = value
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      .join('\n')
    setSetting.mutate(normalized, {
      onSuccess: () => {
        setDraft(null)
        invalidateLibrary()
        toast.success(t('exclusions.saved'))
      },
      onError: (error) => toast.error(t('common.saveFailed', { message: error.message })),
    })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('exclusions.customTitle')}</CardTitle>
        <CardDescription>{t('exclusions.customDescription')}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        <Textarea
          rows={8}
          className="font-mono text-xs"
          value={value}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={'*.srt\nextras/*\n*-trailer.*'}
          aria-label={t('exclusions.customTitle')}
        />
        <p className="flex gap-1.5 text-xs text-muted-foreground">
          <InfoIcon className="mt-0.5 size-3.5 shrink-0" />
          {t('exclusions.stillUsedNote')}
        </p>
      </CardContent>
      <CardFooter className="justify-end">
        <Button size="sm" onClick={save} disabled={draft === null || setSetting.isPending}>
          {t('exclusions.save')}
        </Button>
      </CardFooter>
    </Card>
  )
}

export function ExclusionsSection() {
  return (
    <>
      <PresetsCard />
      <CustomPatternsCard />
    </>
  )
}
