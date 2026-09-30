import type { UploadTarget } from '@/api/hooks/uploads'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { ToggleGroupItem, ToggleGroupSingle } from '@/components/ui/toggle-group'
import { t } from '@/lib/i18n'
import { editDraft, type TargetDraft } from '@/lib/upload'

const FLAGS = ['anonymous', 'personal_release', 'internal', 'stream'] as const

function IdSelect({
  label,
  map,
  value,
  onChange,
}: {
  label: string
  map: Record<string, number>
  value: number | null
  onChange: (value: number | null) => void
}) {
  const entries = Object.entries(map)
  const current = value != null ? String(value) : null
  // Più chiavi possono avere lo stesso id (1440p e 1080p su ITT): nel
  // selettore si mostrano insieme.
  const byId = new Map<number, string[]>()
  for (const [key, id] of entries) byId.set(id, [...(byId.get(id) ?? []), key])
  return (
    <div className="grid gap-1">
      <Label className="text-xs">{label}</Label>
      <Select value={current} onValueChange={(v) => onChange(v == null ? null : Number(v))}>
        <SelectTrigger size="sm" className="w-full">
          <SelectValue placeholder={t('upload.decision.choose')}>
            {(v: string | null) => (v == null ? t('upload.decision.choose') : `${byId.get(Number(v))?.join(' / ') ?? '?'} (${v})`)}
          </SelectValue>
        </SelectTrigger>
        <SelectContent>
          {[...byId.entries()].map(([id, keys]) => (
            <SelectItem key={id} value={String(id)}>
              {keys.join(' / ')} ({id})
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

// La decisione per un tracker: azione, e per un upload nome, id del
// profilo e flag; per un reseed il torrent identico da rimettere in seed.
export function TargetDecisionForm({
  target,
  draft,
  onChange,
  disabled,
}: {
  target: UploadTarget
  draft: TargetDraft
  onChange: (draft: TargetDraft) => void
  disabled: boolean
}) {
  const identical = (target.dupes as unknown as { torrent_id_remote: string; name: string; verdict: string }[]).filter(
    (d) => d.verdict === 'identical',
  )
  const set = (patch: Partial<Omit<TargetDraft, 'touched'>>) => onChange(editDraft(draft, patch))

  return (
    <div className="grid min-w-0 gap-4 rounded-md border bg-muted/30 p-3">
      <div className="flex flex-wrap items-center gap-3">
        <ToggleGroupSingle
          aria-label={t('upload.decision.action')}
          value={draft.action}
          onValueChange={(value) => set({ action: value as TargetDraft['action'] })}
          variant="outline"
          disabled={disabled}
        >
          <ToggleGroupItem value="upload" className="min-w-24 px-4">{t('upload.action.upload')}</ToggleGroupItem>
          <ToggleGroupItem value="reseed" className="min-w-24 px-4" disabled={identical.length === 0}>
            {t('upload.action.reseed')}
          </ToggleGroupItem>
          <ToggleGroupItem value="skip" className="min-w-24 px-4">{t('upload.action.skip')}</ToggleGroupItem>
        </ToggleGroupSingle>
      </div>

      {draft.action === 'upload' && (
        <>
          <div className="grid min-w-0 gap-1">
            <Label htmlFor={`name-${target.id}`} className="text-xs">
              {t('upload.decision.name')}
            </Label>
            <Input
              id={`name-${target.id}`}
              className="font-mono text-xs"
              value={draft.name}
              disabled={disabled}
              onChange={(e) => set({ name: e.target.value })}
            />
            {draft.touched.includes('name') && draft.name !== target.proposed_name && (
              <button
                type="button"
                className="w-fit text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground"
                onClick={() => onChange({ ...draft, name: target.proposed_name ?? '', touched: draft.touched.filter((k) => k !== 'name') })}
              >
                {t('upload.decision.useProposed')}
              </button>
            )}
          </div>
          <div className="grid gap-3 sm:grid-cols-3 lg:max-w-3xl">
            <IdSelect
              label={t('upload.decision.category')}
              map={target.category_id_map}
              value={draft.category_id}
              onChange={(category_id) => set({ category_id })}
            />
            <IdSelect
              label={t('upload.decision.type')}
              map={target.type_id_map}
              value={draft.type_id}
              onChange={(type_id) => set({ type_id })}
            />
            <IdSelect
              label={t('upload.decision.resolution')}
              map={target.resolution_id_map}
              value={draft.resolution_id}
              onChange={(resolution_id) => set({ resolution_id })}
            />
          </div>
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
            {target.freeleech_options.length > 0 && (
              <div className="flex items-center gap-2">
                <Label className="text-xs">{t('upload.decision.freeleech')}</Label>
                <Select
                  value={String(draft.freeleech)}
                  onValueChange={(v) => v != null && set({ freeleech: Number(v) })}
                  disabled={disabled}
                >
                  <SelectTrigger size="sm" className="w-24">
                    <SelectValue>{(v: string | null) => (v === '0' || v == null ? t('upload.decision.noFreeleech') : `${v}%`)}</SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {[0, ...target.freeleech_options].map((value) => (
                      <SelectItem key={value} value={String(value)}>
                        {value === 0 ? t('upload.decision.noFreeleech') : `${value}%`}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
            {FLAGS.map((flag) => (
              <div key={flag} className="flex items-center gap-2">
                <Switch
                  id={`${flag}-${target.id}`}
                  size="sm"
                  checked={draft.flags[flag] ?? false}
                  disabled={disabled}
                  onCheckedChange={(checked) => set({ flags: { ...draft.flags, [flag]: checked } })}
                />
                <Label htmlFor={`${flag}-${target.id}`} className="text-xs">
                  {t(`upload.decision.flag.${flag}`)}
                </Label>
              </div>
            ))}
          </div>
        </>
      )}

      {draft.action === 'reseed' && (
        <div className="grid gap-1">
          <Label className="text-xs">{t('upload.decision.reseedTorrent')}</Label>
          <Select value={draft.reseed_torrent_id} onValueChange={(v) => v != null && set({ reseed_torrent_id: v })}>
            <SelectTrigger size="sm" className="w-full">
              <SelectValue placeholder={t('upload.decision.choose')}>
                {(v: string | null) => identical.find((d) => d.torrent_id_remote === v)?.name ?? t('upload.decision.choose')}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {identical.map((d) => (
                <SelectItem key={d.torrent_id_remote} value={d.torrent_id_remote}>
                  {d.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">{t('upload.decision.reseedHelp')}</p>
        </div>
      )}
    </div>
  )
}
