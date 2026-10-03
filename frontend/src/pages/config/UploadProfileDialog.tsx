import { RotateCcwIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import {
  useBundledUploadProfiles,
  useCreateUploadProfile,
  useDeleteUploadProfile,
  useRestoreUploadProfile,
  useUpdateNamingFromBundled,
  useUpdateUploadProfile,
  useUploadProfile,
} from '@/api/hooks/trackers'
import { NamingRulesEditor, type NamingRules } from '@/components/NamingRulesEditor'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { FreeleechField, Section } from '@/pages/config/UploadProfileParts'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { t } from '@/lib/i18n'
import { selectLabel } from '@/lib/utils'
import { autosaveFeedback } from '@/lib/autosave'

// L'host senza www., per riconoscere il profilo incluso di un tracker.
function hostOf(url: string | null | undefined): string {
  try {
    return new URL(url ?? '').hostname.toLowerCase().replace(/^www\./, '')
  } catch {
    return ''
  }
}

function jsonField(value: Record<string, number>) {
  return JSON.stringify(value, null, 2)
}

export function UploadProfileDialog({
  trackerId,
  trackerLabel,
  trackerBaseUrl = '',
  open,
  onOpenChange,
}: {
  trackerId: number
  trackerLabel: string
  trackerBaseUrl?: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { data: profile, isPending } = useUploadProfile(trackerId)
  const { data: bundled } = useBundledUploadProfiles()
  const createProfile = useCreateUploadProfile(trackerId)
  const updateProfile = useUpdateUploadProfile(trackerId)
  const deleteProfile = useDeleteUploadProfile(trackerId)

  // null = l'utente non ha ancora modificato il campo in questa sessione
  // del dialog: mostra il valore caricato dal profilo. Evita di
  // sincronizzare profile->stato locale con un effect (derivabile
  // direttamente durante il render).
  const [categoryMapDraft, setCategoryMapDraft] = useState<string | null>(null)
  const [typeMapDraft, setTypeMapDraft] = useState<string | null>(null)
  const [resolutionMapDraft, setResolutionMapDraft] = useState<string | null>(null)
  const [descriptionTemplateDraft, setDescriptionTemplateDraft] = useState<string | null>(null)
  const [namingRulesDraft, setNamingRulesDraft] = useState<NamingRules | null>(null)
  const updateNaming = useUpdateNamingFromBundled(trackerId)
  const restoreProfile = useRestoreUploadProfile(trackerId)
  const [restores, setRestores] = useState(0) // l'editor delle regole riparte dalle regole ripristinate
  const [bundledKeyDraft, setBundledKeyDraft] = useState<string | null>(null)
  // Di partenza: il profilo da cui è nato, o quello incluso dello stesso indirizzo.
  const matching = bundled?.find((p) => p.base_url && hostOf(p.base_url) === hostOf(trackerBaseUrl))?.key
  const bundledKey = bundledKeyDraft ?? profile?.source_profile_key ?? matching ?? ''
  const setBundledKey = (key: string) => setBundledKeyDraft(key)

  const categoryMap = categoryMapDraft ?? (profile ? jsonField(profile.category_id_map) : '{}')
  const typeMap = typeMapDraft ?? (profile ? jsonField(profile.type_id_map) : '{}')
  const resolutionMap = resolutionMapDraft ?? (profile ? jsonField(profile.resolution_id_map) : '{}')
  const descriptionTemplate = descriptionTemplateDraft ?? profile?.description_template ?? ''
  const namingRules: NamingRules =
    namingRulesDraft ??
    (profile?.naming_rules as NamingRules | null | undefined) ??
    (profile?.naming_convention ? { templates: { default: profile.naming_convention } } : {})

  function parseOrToast(label: string, raw: string): Record<string, number> | null {
    try {
      return JSON.parse(raw) as Record<string, number>
    } catch {
      toast.error(t('trackers.invalidJson', { label }))
      return null
    }
  }

  function save() {
    const category_id_map = parseOrToast('category_id_map', categoryMap)
    const type_id_map = parseOrToast('type_id_map', typeMap)
    const resolution_id_map = parseOrToast('resolution_id_map', resolutionMap)
    if (!category_id_map || !type_id_map || !resolution_id_map) return
    // Solo se toccate: salvarle le segna come modificate (niente più
    // aggiornamenti automatici dal codice).
    const naming_rules = namingRulesDraft ?? undefined
    updateProfile.mutate(
      { category_id_map, type_id_map, resolution_id_map, description_template: descriptionTemplate, naming_rules },
      {
        onSuccess: () => {
          toast.success(t('trackers.profileSaved'))
          onOpenChange(false)
          setCategoryMapDraft(null)
          setTypeMapDraft(null)
          setResolutionMapDraft(null)
          setDescriptionTemplateDraft(null)
          setNamingRulesDraft(null)
        },
        onError: (error) => toast.error(t('common.saveFailed', { message: error.message })),
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-5xl">
        <DialogHeader>
          <DialogTitle>{t('trackers.uploadProfileTitle', { trackerLabel })}</DialogTitle>
        </DialogHeader>

        {isPending && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}

        {!isPending && !profile && (
          <div className="grid gap-3">
            <p className="text-sm text-muted-foreground">{t('trackers.noProfileYet')}</p>
            <div className="flex items-center gap-2">
              <Select value={bundledKey} onValueChange={setBundledKey}>
                <SelectTrigger className="flex-1">
                  <SelectValue placeholder={t('trackers.bundledProfilePlaceholder')}>
                    {(v: string | null) =>
                      selectLabel(bundled, v, (p) => p.key, (p) => p.label, t('trackers.bundledProfilePlaceholder'))
                    }
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {bundled?.map((p) => (
                    <SelectItem key={p.key} value={p.key}>
                      {p.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button disabled={!bundledKey} onClick={() => createProfile.mutate({ profile_key: bundledKey })}>
                {t('trackers.useProfile')}
              </Button>
            </div>
            <Button variant="outline" onClick={() => createProfile.mutate({ profile_key: null })}>
              {t('trackers.emptyCustomProfile')}
            </Button>
          </div>
        )}

        {!isPending && profile && (
          <div className="grid gap-5">
            <div className="grid gap-2 rounded-md border p-3">
              <p className="text-xs text-muted-foreground">
                {profile.source_profile_key
                  ? t('trackers.copiedFromBundled', { key: profile.source_profile_key })
                  : t('trackers.restoreHelpCustom')}
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <Select value={bundledKey} onValueChange={(v) => setBundledKey(String(v ?? ''))}>
                  <SelectTrigger className="min-w-56 flex-1 sm:flex-none">
                    <SelectValue placeholder={t('trackers.bundledProfilePlaceholder')}>
                      {(v: string | null) =>
                        selectLabel(bundled, v, (p) => p.key, (p) => p.label, t('trackers.bundledProfilePlaceholder'))
                      }
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {bundled?.map((p) => (
                      <SelectItem key={p.key} value={p.key}>
                        {p.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  variant="outline"
                  disabled={!bundledKey || restoreProfile.isPending}
                  onClick={() => {
                    const label = bundled?.find((p) => p.key === bundledKey)?.label ?? bundledKey
                    if (!window.confirm(t('trackers.restoreConfirm', { profile: label }))) return
                    restoreProfile.mutate(bundledKey, {
                      onSuccess: () => {
                        toast.success(t('trackers.restored', { profile: label }))
                        setCategoryMapDraft(null)
                        setTypeMapDraft(null)
                        setResolutionMapDraft(null)
                        setDescriptionTemplateDraft(null)
                        setNamingRulesDraft(null)
                        setRestores((n) => n + 1)
                      },
                      onError: (error) => toast.error(error.message),
                    })
                  }}
                >
                  <RotateCcwIcon className="size-4" />
                  {t('trackers.restoreProfile')}
                </Button>
              </div>
            </div>

            <Section title={t('trackers.section.naming')}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs text-muted-foreground">{t('trackers.namingRulesHelp')}</p>
                {profile.naming_version != null && (
                  <span className="text-xs text-muted-foreground">
                    {t('trackers.namingVersion', { version: profile.naming_version })}
                    {profile.naming_customized && ` · ${t('trackers.namingCustomized')}`}
                  </span>
                )}
              </div>
              {profile.naming_update_available != null && (
                <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-xs">
                  <span>{t('trackers.namingUpdateAvailable', { version: profile.naming_update_available })}</span>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={updateNaming.isPending}
                    onClick={() =>
                      updateNaming.mutate(undefined, {
                        onSuccess: () => setNamingRulesDraft(null),
                        onError: (error) => toast.error(error.message),
                      })
                    }
                  >
                    {t('trackers.namingUseNew')}
                  </Button>
                </div>
              )}
              <NamingRulesEditor
                key={`${profile.naming_version ?? 0}-${restores}`}
                trackerId={trackerId}
                value={namingRules}
                onChange={setNamingRulesDraft}
              />
            </Section>

            <Section title={t('trackers.section.description')}>
              <Textarea
                rows={5}
                className="font-mono text-xs"
                value={descriptionTemplate}
                onChange={(e) => setDescriptionTemplateDraft(e.target.value)}
              />
            </Section>

            <Section title={t('trackers.section.defaults')}>
              <div className="flex flex-wrap gap-x-8 gap-y-3">
                <label className="flex items-center gap-2 text-sm">
                  <Switch
                    checked={profile.default_anonymous}
                    onCheckedChange={(v) =>
                      updateProfile.mutate({ default_anonymous: v }, autosaveFeedback(t('trackers.defaultAnonymous')))
                    }
                  />
                  {t('trackers.defaultAnonymous')}
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <Switch
                    checked={profile.default_personal_release}
                    onCheckedChange={(v) =>
                      updateProfile.mutate(
                        { default_personal_release: v },
                        autosaveFeedback(t('trackers.defaultPersonalRelease')),
                      )
                    }
                  />
                  {t('trackers.defaultPersonalRelease')}
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <Switch
                    checked={profile.default_internal}
                    onCheckedChange={(v) =>
                      updateProfile.mutate({ default_internal: v }, autosaveFeedback(t('trackers.defaultInternal')))
                    }
                  />
                  {t('trackers.defaultInternal')}
                </label>
              </div>
              <FreeleechField
                options={profile.freeleech_options}
                defaultValue={profile.default_freeleech ?? 0}
                onChange={(body) => updateProfile.mutate(body, autosaveFeedback(t('trackers.freeleech')))}
              />
            </Section>

            <Collapsible>
              <CollapsibleTrigger className="text-sm font-medium hover:underline">
                {t('trackers.section.advanced')}
              </CollapsibleTrigger>
              <CollapsibleContent className="grid gap-3 pt-3">
                <p className="text-xs text-muted-foreground">{t('trackers.advancedHelp')}</p>
                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="grid gap-1.5">
                    <Label>category_id_map</Label>
                    <Textarea rows={5} className="font-mono text-xs" value={categoryMap} onChange={(e) => setCategoryMapDraft(e.target.value)} />
                  </div>
                  <div className="grid gap-1.5">
                    <Label>type_id_map</Label>
                    <Textarea rows={5} className="font-mono text-xs" value={typeMap} onChange={(e) => setTypeMapDraft(e.target.value)} />
                  </div>
                  <div className="grid gap-1.5">
                    <Label>resolution_id_map</Label>
                    <Textarea rows={5} className="font-mono text-xs" value={resolutionMap} onChange={(e) => setResolutionMapDraft(e.target.value)} />
                  </div>
                </div>
              </CollapsibleContent>
            </Collapsible>

            <div className="flex justify-between">
              <Button variant="destructive" onClick={() => deleteProfile.mutate()}>
                {t('trackers.deleteProfile')}
              </Button>
              <Button onClick={save} disabled={updateProfile.isPending}>
                {t('common.save')}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
