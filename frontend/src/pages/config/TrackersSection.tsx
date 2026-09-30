import { CheckIcon, FileUpIcon, PencilIcon, PlusIcon, TrashIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { useBundledUploadProfiles, useCreateTracker, useDeleteTracker, useTrackers, useUpdateTracker } from '@/api/hooks/trackers'
import type { Schemas } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useTorrentClients } from '@/api/hooks/torrentClients'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { t } from '@/lib/i18n'
import { TrackerLogo } from '@/pages/config/ServiceIcons'
import { cn, selectLabel } from '@/lib/utils'
import { UploadProfileDialog } from '@/pages/config/UploadProfileDialog'
import { autosaveFeedback } from '@/lib/autosave'

type Tracker = Schemas['TrackerResponse']

// Facoltativa e quasi sempre inutile: la chiave dei link di download viene
// appresa dalle risposte dell'API del tracker (app/adapters/tracker/base.py).
// Serve solo a riscrivere i link salvati da Sonarr/Radarr prima di un
// cambio di chiave, e mai restituita dall'API (has_rss_key).
function RssKeyField({
  id,
  value,
  onChange,
  placeholder,
}: {
  id: string
  value: string
  onChange: (value: string) => void
  placeholder: string
}) {
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id}>{t('trackers.rssKey')}</Label>
      <Input
        id={id}
        type="password"
        autoComplete="off"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
      <p className="text-xs text-muted-foreground">{t('trackers.rssKeyHelp')}</p>
    </div>
  )
}

const FIRST_ENABLED = 'first'
const NO_LANGUAGE = 'none'
// Le lingue che il naming sa scrivere (app/upload_naming.py LANG3), ISO 639-1.
const LANGUAGES = [
  'ar', 'cs', 'da', 'de', 'el', 'en', 'es', 'fi', 'fr', 'he', 'hi', 'hu', 'it', 'ja', 'ko', 'nl', 'no', 'pl', 'pt',
  'ro', 'ru', 'sv', 'th', 'tr', 'uk', 'zh',
]

function languageName(code: string) {
  try {
    return new Intl.DisplayNames(['en'], { type: 'language' }).of(code) ?? code
  } catch {
    return code
  }
}

// La lingua del tracker: per i nomi degli upload (titolo localizzato, lingua
// messa per prima, SUB/SUBS con la lingua).
function TrackerLanguageSelect({ value, onChange }: { value: string | null; onChange: (code: string | null) => void }) {
  const options = [
    { value: NO_LANGUAGE, label: t('trackers.noLanguage') },
    ...LANGUAGES.map((code) => ({ value: code, label: `${languageName(code)} (${code})` })).sort((a, b) =>
      a.label.localeCompare(b.label),
    ),
  ]
  const current = value ?? NO_LANGUAGE
  return (
    <Select value={current} onValueChange={(v) => onChange(v === NO_LANGUAGE || v == null ? null : v)}>
      <SelectTrigger size="sm" className="w-44">
        <SelectValue>
          {(v: string | null) => selectLabel(options, v, (o) => o.value, (o) => o.label, t('trackers.noLanguage'))}
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

// In quale client aggiungere i torrent di questo tracker quando si ricrea
// un seed (es. l'istanza dei tracker privati). "First enabled" = il primo
// client abilitato, il comportamento di sempre.
function TrackerClientSelect({ value, onChange }: { value: number | null; onChange: (id: number | null) => void }) {
  const { data: clients } = useTorrentClients()
  const options = [
    { value: FIRST_ENABLED, label: t('trackers.firstEnabledClient') },
    ...(clients ?? []).map((c) => ({ value: String(c.id), label: c.label })),
  ]
  const current = value == null ? FIRST_ENABLED : String(value)
  return (
    <Select value={current} onValueChange={(v) => onChange(v === FIRST_ENABLED || v == null ? null : Number(v))}>
      <SelectTrigger size="sm" className="w-44">
        <SelectValue>
          {(v: string | null) => selectLabel(options, v, (o) => o.value, (o) => o.label, t('trackers.firstEnabledClient'))}
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

function AddTrackerDialog() {
  const [open, setOpen] = useState(false)
  const [presetKey, setPresetKey] = useState('')
  const [label, setLabel] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [apiToken, setApiToken] = useState('')
  const [announceUrl, setAnnounceUrl] = useState('')
  const [rssKey, setRssKey] = useState('')
  const createTracker = useCreateTracker()
  const { data: bundled } = useBundledUploadProfiles()

  function applyPreset(key: string) {
    setPresetKey(key)
    const preset = bundled?.find((p) => p.key === key)
    if (!preset) return
    if (!label) setLabel(preset.label)
    if (preset.base_url) setBaseUrl(preset.base_url)
  }

  function reset() {
    setPresetKey('')
    setLabel('')
    setBaseUrl('')
    setApiToken('')
    setAnnounceUrl('')
    setRssKey('')
  }

  function submit() {
    createTracker.mutate(
      {
        label,
        adapter_type: 'unit3d',
        base_url: baseUrl,
        api_token: apiToken,
        announce_url: announceUrl || undefined,
        rss_key: rssKey || undefined,
      },
      {
        onSuccess: () => {
          setOpen(false)
          reset()
        },
        onError: (error) => toast.error(t('trackers.createFailed', { message: error.message })),
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button><PlusIcon className="size-4" />{t('trackers.addTracker')}</Button>} />
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('trackers.addTracker')}</DialogTitle>
        </DialogHeader>
        <div className="grid gap-3">
          <div className="grid gap-1.5">
            <Label>{t('trackers.preset')}</Label>
            <Select value={presetKey} onValueChange={applyPreset}>
              <SelectTrigger>
                <SelectValue placeholder={t('trackers.presetPlaceholder')}>
                  {(v: string | null) =>
                    selectLabel(bundled, v, (p) => p.key, (p) => p.label, t('trackers.presetPlaceholder'))
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
            <p className="text-xs text-muted-foreground">{t('trackers.presetHelp')}</p>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="t-label">{t('trackers.label')}</Label>
            <Input id="t-label" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="mytracker" />
          </div>
          <div className="grid gap-1.5">
            <Label>{t('trackers.type')}</Label>
            <Input value="unit3d" disabled />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="t-base-url">{t('trackers.apiUrl')}</Label>
            <Input
              id="t-base-url"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://mytracker.example"
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="t-api-token">{t('trackers.apiToken')}</Label>
            <Input id="t-api-token" value={apiToken} onChange={(e) => setApiToken(e.target.value)} />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="t-announce-url">{t('trackers.announceUrl')}</Label>
            <Input
              id="t-announce-url"
              value={announceUrl}
              onChange={(e) => setAnnounceUrl(e.target.value)}
              placeholder="https://mytracker.example/announce/passkey"
            />
          </div>
          <RssKeyField id="t-rss-key" value={rssKey} onChange={setRssKey} placeholder={t('trackers.rssKeyPlaceholder')} />
        </div>
        <DialogFooter>
          <Button onClick={submit} disabled={!label || !baseUrl || !apiToken || createTracker.isPending}>
            {t('trackers.create')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function EditTrackerDialog({ tracker }: { tracker: Tracker }) {
  const [open, setOpen] = useState(false)
  const [label, setLabel] = useState(tracker.label)
  const [baseUrl, setBaseUrl] = useState(tracker.base_url)
  const [apiToken, setApiToken] = useState('')
  const [announceUrl, setAnnounceUrl] = useState('')
  const [rateLimit, setRateLimit] = useState(tracker.rate_limit_per_min?.toString() ?? '')
  const [rssKey, setRssKey] = useState('')
  const updateTracker = useUpdateTracker()

  function submit() {
    updateTracker.mutate(
      {
        id: tracker.id,
        body: {
          label,
          base_url: baseUrl,
          api_token: apiToken || undefined,
          announce_url: announceUrl || undefined,
          rate_limit_per_min: rateLimit ? Number(rateLimit) : undefined,
          rss_key: rssKey || undefined,
        },
      },
      {
        onSuccess: () => {
          setOpen(false)
          setApiToken('')
          setAnnounceUrl('')
          setRssKey('')
        },
        onError: (error) => toast.error(t('common.saveFailed', { message: error.message })),
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button variant="ghost" size="icon-sm" title={t('common.edit')}><PencilIcon className="size-4" /></Button>} />
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('trackers.editTracker')}</DialogTitle>
          <DialogDescription>{t('trackers.editTypeLocked')}</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor="t-edit-label">{t('trackers.label')}</Label>
            <Input id="t-edit-label" value={label} onChange={(e) => setLabel(e.target.value)} />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="t-edit-base-url">{t('trackers.apiUrl')}</Label>
            <Input id="t-edit-base-url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="t-edit-api-token">{t('trackers.apiToken')}</Label>
            <Input
              id="t-edit-api-token"
              value={apiToken}
              onChange={(e) => setApiToken(e.target.value)}
              placeholder={t('common.leaveBlank')}
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="t-edit-announce-url">{t('trackers.announceUrl')}</Label>
            <Input
              id="t-edit-announce-url"
              value={announceUrl}
              onChange={(e) => setAnnounceUrl(e.target.value)}
              placeholder={tracker.has_announce_url ? t('trackers.announceUrlKnown') : undefined}
            />
          </div>
          <RssKeyField
            id="t-edit-rss-key"
            value={rssKey}
            onChange={setRssKey}
            placeholder={tracker.has_rss_key ? t('trackers.rssKeyKnown') : t('trackers.rssKeyPlaceholder')}
          />
          <div className="grid gap-1.5">
            <Label htmlFor="t-edit-rate-limit">{t('trackers.rateLimit')}</Label>
            <Input
              id="t-edit-rate-limit"
              type="number"
              value={rateLimit}
              onChange={(e) => setRateLimit(e.target.value)}
            />
          </div>
        </div>
        <DialogFooter>
          <Button onClick={submit} disabled={!label || !baseUrl || updateTracker.isPending}>
            {t('common.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// Announce URL e chiave RSS contengono la passkey: la tabella dice solo se
// ci sono, l'API non le restituisce mai (has_announce_url, has_rss_key).
function SecretPresence({ present }: { present: boolean }) {
  return present ? (
    <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
      <CheckIcon className="size-3.5 text-emerald-500" />
      {t('trackers.secretSet')}
    </span>
  ) : (
    <span className="text-xs text-muted-foreground">—</span>
  )
}

export function TrackersSection() {
  const { data: trackers, isPending } = useTrackers()
  const updateTracker = useUpdateTracker()
  const deleteTracker = useDeleteTracker()
  const [profileTrackerId, setProfileTrackerId] = useState<number | null>(null)

  return (
    <div className="grid content-start gap-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">{t('trackers.title')}</h2>
        <AddTrackerDialog />
      </div>
      {isPending && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}
      {trackers?.length === 0 && (
        <Card>
          <CardContent className="py-6 text-center text-sm text-muted-foreground">{t('trackers.noTrackers')}</CardContent>
        </Card>
      )}
      {/* Una scheda per tracker: icona del sito, indirizzi e chiavi, client
          su cui seedano i suoi torrent, profilo di upload e azioni. */}
      <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
        {trackers?.map((tracker) => {
          const profile = tracker.upload_profile
          return (
            <Card key={tracker.id} className={cn('min-w-0', !tracker.enabled && 'opacity-70')}>
              <CardHeader className="flex flex-row items-center gap-3">
                <TrackerLogo trackerId={tracker.id} />
                <div className="grid min-w-0 flex-1 gap-0.5">
                  <CardTitle className="truncate text-base">{tracker.label}</CardTitle>
                  <span className="truncate font-mono text-xs text-muted-foreground" title={tracker.base_url}>
                    {tracker.base_url}
                  </span>
                </div>
                <Switch
                  checked={tracker.enabled}
                  title={t('trackers.enabled')}
                  onCheckedChange={(enabled) =>
                    updateTracker.mutate(
                      { id: tracker.id, body: { enabled } },
                      autosaveFeedback(`${tracker.label} · ${t('trackers.enabled')}`),
                    )
                  }
                />
              </CardHeader>
              <CardContent className="grid min-w-0 gap-3 text-sm">
                <div className="grid grid-cols-[auto_1fr] items-center gap-x-3 gap-y-2 text-xs">
                  <span className="text-muted-foreground">{t('trackers.announceUrlColumn')}</span>
                  <SecretPresence present={tracker.has_announce_url} />
                  <span className="text-muted-foreground">{t('trackers.rssKeyColumn')}</span>
                  <SecretPresence present={tracker.has_rss_key} />
                  <span className="text-muted-foreground">{t('trackers.clientColumn')}</span>
                  <TrackerClientSelect
                    value={tracker.torrent_client_id ?? null}
                    onChange={(torrentClientId) =>
                      updateTracker.mutate(
                        { id: tracker.id, body: { torrent_client_id: torrentClientId } },
                        autosaveFeedback(`${tracker.label} · ${t('trackers.clientColumn')}`),
                      )
                    }
                  />
                  <span className="text-muted-foreground" title={t('trackers.languageHelp')}>
                    {t('trackers.languageColumn')}
                  </span>
                  <TrackerLanguageSelect
                    value={tracker.language ?? null}
                    onChange={(language) =>
                      updateTracker.mutate(
                        { id: tracker.id, body: { language } },
                        autosaveFeedback(`${tracker.label} · ${t('trackers.languageColumn')}`),
                      )
                    }
                  />
                  <span className="text-muted-foreground">{t('trackers.uploadProfile')}</span>
                  <span className="flex flex-wrap items-center gap-1.5">
                    {profile ? (
                      <>
                        <Badge variant="secondary">{profile.source_profile_key ?? t('trackers.customProfile')}</Badge>
                        {profile.naming_version != null && (
                          <span className="text-muted-foreground">
                            {t('trackers.namingVersion', { version: profile.naming_version })}
                          </span>
                        )}
                        {profile.naming_update_available != null && (
                          <Badge variant="outline" className="border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300">
                            {t('trackers.namingUpdateBadge')}
                          </Badge>
                        )}
                        {profile.freeleech_options.length > 0 && (
                          <span className="text-muted-foreground">FL {profile.freeleech_options.join('/')}%</span>
                        )}
                      </>
                    ) : (
                      <span className="text-muted-foreground">{t('trackers.noUploadProfile')}</span>
                    )}
                  </span>
                </div>
                <div className="flex justify-end gap-1 border-t pt-3">
                  <Button variant="ghost" size="sm" onClick={() => setProfileTrackerId(tracker.id)}>
                    <FileUpIcon className="size-4" />
                    {t('trackers.uploadProfile')}
                  </Button>
                  <EditTrackerDialog tracker={tracker} />
                  <Button variant="ghost" size="icon-sm" title={t('common.delete')} onClick={() => deleteTracker.mutate(tracker.id)}>
                    <TrashIcon className="size-4" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>

      {profileTrackerId !== null && (
        <UploadProfileDialog
          trackerId={profileTrackerId}
          trackerLabel={trackers?.find((t) => t.id === profileTrackerId)?.label ?? ''}
          open
          onOpenChange={(open) => !open && setProfileTrackerId(null)}
        />
      )}
    </div>
  )
}
