import { FolderOpenIcon, HardDriveIcon, PencilIcon, PlusIcon, TrashIcon, ZapIcon } from 'lucide-react'
import { Fragment, useState } from 'react'
import { toast } from 'sonner'

import { useDisks } from '@/api/hooks/disks'
import {
  useAssociateDisk,
  useCreateTorrentClient,
  useDeleteTorrentClient,
  useDissociateDisk,
  useTestTorrentClient,
  useTorrentClientCategories,
  useTorrentClients,
  useUpdateTorrentClient,
} from '@/api/hooks/torrentClients'
import type { Schemas } from '@/api/client'
import { usePlugins } from '@/api/hooks/plugins'
import {
  AdapterConfigFields,
  configPayload,
  initialConfigValues,
  missingRequired,
  type ConfigValues,
} from '@/components/AdapterConfigFields'
import { ClientCategorySelect } from '@/components/ClientCategorySelect'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { SettingsHeader } from '@/components/SettingsHeader'
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { t } from '@/lib/i18n'
import { relativeFromNow } from '@/lib/time'
import { cn, selectLabel } from '@/lib/utils'
import { autosaveFeedback } from '@/lib/autosave'
import { PASSWORD_ONLY, torrentClientPayload, type TorrentClientForm } from '@/lib/torrentClientForm'
import { CLIENT_NAMES } from '@/lib/services'
import { ClientLogo } from '@/pages/config/ServiceIcons'
import { PathCheckButton } from '@/pages/config/ClientPathCheck'
import { DiskBrowserDialog } from '@/pages/config/DiskBrowserDialog'

type TorrentClient = Schemas['TorrentClientResponse']
type Disk = Schemas['DiskResponse']
type DiskAssociation = Schemas['DiskAssociationResponse']

const ADAPTER_TYPES = [
  { value: 'qbittorrent', label: 'qBittorrent' },
  { value: 'qui', label: t('torrentClients.quiLabel') },
  { value: 'deluge', label: 'Deluge' },
  { value: 'transmission', label: 'Transmission' },
  { value: 'rutorrent', label: t('torrentClients.rtorrentLabel') },
]

// Come lo raggiunge Nazgarr, per tipo: l'indirizzo di esempio e cosa scriverci.
const URL_PLACEHOLDERS: Record<string, string> = {
  qbittorrent: 'http://qbittorrent:8080',
  qui: 'http://qui:7476',
  deluge: 'http://deluge:8112',
  transmission: 'http://transmission:9091',
  rutorrent: 'http://rtorrent:8000/RPC2',
}
const TYPE_HELP: Record<string, string> = {
  deluge: t('torrentClients.typeHelp.deluge'),
  transmission: t('torrentClients.typeHelp.transmission'),
  rutorrent: t('torrentClients.typeHelp.rutorrent'),
}

// I client dei plugin, con i campi che dichiarano.
function usePluginClientTypes() {
  const { data } = usePlugins()
  return (data?.adapters ?? []).filter((a) => a.kind === 'torrent_client' && a.plugin)
}

function emptyForm(tc?: TorrentClient): TorrentClientForm {
  return {
    label: tc?.label ?? '',
    adapterType: tc?.adapter_type ?? 'qbittorrent',
    baseUrl: tc?.base_url ?? '',
    username: tc?.username ?? '',
    password: '',
    apiToken: '',
    quiInstanceId: tc?.qui_instance_id?.toString() ?? '',
  }
}

// Aggiungere (senza tc) o modificare un client: gli stessi campi. Il tipo si
// sceglie solo creando; modificando, i segreti vuoti restano quelli salvati.
function TorrentClientDialog({ tc }: { tc?: TorrentClient }) {
  const editing = tc != null
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState<TorrentClientForm>(() => emptyForm(tc))
  const set = (field: keyof TorrentClientForm) => (value: string) => setForm((f) => ({ ...f, [field]: value }))
  const pluginTypes = usePluginClientTypes()
  const pluginSpec = pluginTypes.find((a) => a.adapter_type === form.adapterType)
  const secretsSet = editing ? ((tc.config as { secrets_set?: string[] }).secrets_set ?? []) : []
  const [config, setConfig] = useState<ConfigValues | null>(null)
  const configValues =
    config ??
    (pluginSpec
      ? initialConfigValues(pluginSpec.config_fields, editing ? (tc.config as { values?: Record<string, unknown> }).values : undefined)
      : {})
  const typeOptions = [
    ...ADAPTER_TYPES,
    ...pluginTypes.map((a) => ({ value: a.adapter_type, label: `${a.label} · ${a.plugin}` })),
  ]
  const createTorrentClient = useCreateTorrentClient()
  const updateTorrentClient = useUpdateTorrentClient()
  const pending = createTorrentClient.isPending || updateTorrentClient.isPending
  const isQui = form.adapterType === 'qui'
  const passwordOnly = PASSWORD_ONLY.has(form.adapterType)
  const keepPlaceholder = editing ? t('torrentClients.leaveEmptyToKeep') : undefined
  const idPrefix = editing ? 'tc-edit' : 'tc'

  function close() {
    setOpen(false)
    // Creato: un modulo vuoto per il prossimo. Modificato: restano i valori
    // salvati, senza i segreti appena digitati.
    setForm((f) => (editing ? { ...f, password: '', apiToken: '' } : emptyForm()))
    setConfig(null)
  }

  function submit() {
    const payload = torrentClientPayload(form, pluginSpec ? configPayload(pluginSpec.config_fields, configValues) : undefined)
    if (editing) {
      updateTorrentClient.mutate(
        { id: tc.id, body: payload },
        { onSuccess: close, onError: (error) => toast.error(t('common.saveFailed', { message: error.message })) },
      )
    } else {
      createTorrentClient.mutate(
        { ...payload, adapter_type: form.adapterType },
        { onSuccess: close, onError: (error) => toast.error(t('torrentClients.creationFailed', { message: error.message })) },
      )
    }
  }

  const canSubmit =
    form.label &&
    form.baseUrl &&
    (pluginSpec
      ? !missingRequired(pluginSpec.config_fields, configValues, secretsSet)
      : isQui && !editing
        ? form.apiToken && form.quiInstanceId
        : true)

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          editing ? (
            <Button variant="ghost" size="icon-sm" title={t('common.edit')}><PencilIcon className="size-4" /></Button>
          ) : (
            <Button data-tour="clients.add"><PlusIcon className="size-4" />{t('torrentClients.addClient')}</Button>
          )
        }
      />
      <DialogContent data-tour="clients.dialog">
        <DialogHeader>
          <DialogTitle>{t(editing ? 'torrentClients.editTorrentClient' : 'torrentClients.addTorrentClient')}</DialogTitle>
          {editing && <DialogDescription>{t('torrentClients.typeNotEditable', { type: tc.adapter_type })}</DialogDescription>}
        </DialogHeader>
        <div className="grid gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor={`${idPrefix}-label`}>{t('torrentClients.label')}</Label>
            <Input id={`${idPrefix}-label`} value={form.label} onChange={(e) => set('label')(e.target.value)} placeholder={editing ? undefined : 'qbit'} />
          </div>
          {!editing && (
            <div className="grid gap-1.5" data-tour="clients.dialog.type">
              <Label>{t('torrentClients.type')}</Label>
              <Select
                value={form.adapterType}
                onValueChange={(v) => {
                  if (v == null) return
                  set('adapterType')(v)
                  const spec = pluginTypes.find((a) => a.adapter_type === v)
                  setConfig(spec ? initialConfigValues(spec.config_fields, undefined) : {})
                }}
              >
                <SelectTrigger>
                  <SelectValue>
                    {(v: string | null) => selectLabel(typeOptions, v, (a) => a.value, (a) => a.label, 'qBittorrent')}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {typeOptions.map((a) => (
                    <SelectItem key={a.value} value={a.value}>
                      {a.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {TYPE_HELP[form.adapterType] ? (
                <p className="text-xs text-muted-foreground">{TYPE_HELP[form.adapterType]}</p>
              ) : null}
            </div>
          )}
          <div className="grid gap-1.5" data-tour="clients.dialog.url">
            <Label htmlFor={`${idPrefix}-base-url`}>{t('torrentClients.url')}</Label>
            <Input
              id={`${idPrefix}-base-url`}
              value={form.baseUrl}
              onChange={(e) => set('baseUrl')(e.target.value)}
              placeholder={editing ? undefined : (URL_PLACEHOLDERS[form.adapterType] ?? 'http://client:8080')}
            />
          </div>
          {pluginSpec ? (
            <AdapterConfigFields
              idPrefix={editing ? `tc-edit-config-${tc.id}` : 'tc-config'}
              fields={pluginSpec.config_fields}
              values={configValues}
              secretsSet={editing ? secretsSet : undefined}
              onChange={setConfig}
            />
          ) : isQui ? (
            <div className="grid gap-3" data-tour="clients.dialog.credentials">
              <div className="grid gap-1.5">
                <Label htmlFor={`${idPrefix}-api-token`}>{t('torrentClients.apiKey')}</Label>
                <Input
                  id={`${idPrefix}-api-token`}
                  type="password"
                  value={form.apiToken}
                  onChange={(e) => set('apiToken')(e.target.value)}
                  placeholder={keepPlaceholder ?? t('torrentClients.apiKeyPlaceholder')}
                />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor={`${idPrefix}-qui-instance-id`}>{t('torrentClients.instance')}</Label>
                <Input
                  id={`${idPrefix}-qui-instance-id`}
                  type="number"
                  value={form.quiInstanceId}
                  onChange={(e) => set('quiInstanceId')(e.target.value)}
                  placeholder={editing ? undefined : t('torrentClients.instanceIdPlaceholder')}
                />
                {!editing && <p className="text-xs text-muted-foreground">{t('torrentClients.instanceHelp')}</p>}
              </div>
            </div>
          ) : (
            <div className="grid gap-3" data-tour="clients.dialog.credentials">
              {passwordOnly ? null : (
                <div className="grid gap-1.5">
                  <Label htmlFor={`${idPrefix}-username`}>{t('torrentClients.username')}</Label>
                  <Input id={`${idPrefix}-username`} value={form.username} onChange={(e) => set('username')(e.target.value)} />
                </div>
              )}
              <div className="grid gap-1.5">
                <Label htmlFor={`${idPrefix}-password`}>{t('torrentClients.password')}</Label>
                <Input
                  id={`${idPrefix}-password`}
                  type="password"
                  value={form.password}
                  onChange={(e) => set('password')(e.target.value)}
                  placeholder={keepPlaceholder}
                />
              </div>
            </div>
          )}
        </div>
        <DialogFooter>
          <Button data-tour="clients.dialog.create" onClick={submit} disabled={!canSubmit || pending}>
            {t(editing ? 'common.save' : 'torrentClients.create')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function TestButton({ id }: { id: number }) {
  const test = useTestTorrentClient()
  return (
    <Button
      variant="outline"
      size="sm"
      data-tour="clients.test"
      disabled={test.isPending}
      onClick={() =>
        test.mutate(id, {
          onSuccess: (result) => {
            if (result.status === 'ok') toast.success(t('torrentClients.connectedSuccess', { count: result.torrents_found }))
            else toast.error(result.error ?? t('torrentClients.connectionFailed'))
          },
          // La richiesta stessa fallita (rete, Nazgarr irraggiungibile): prima non si vedeva niente.
          onError: (error) => toast.error(error.message || t('torrentClients.connectionFailed')),
        })
      }
    >
      <ZapIcon className="size-4" />
      {t('torrentClients.testConnection')}
    </Button>
  )
}

// Un disco per questo client: acceso o no e, se il client lo vede altrove,
// la corrispondenza fra una cartella del disco (vuota = la radice) e la
// cartella vista dal client (nazgarr/torrents/client_paths.py), es. Nazgarr
// /data/qbittorrent = qBittorrent /download.
function DiskAssociationRow({
  torrentClientId,
  disk,
  association,
}: {
  torrentClientId: number
  disk: Disk
  association: DiskAssociation | undefined
}) {
  const [clientRoot, setClientRoot] = useState(association?.torrent_client_root_path ?? '')
  const [localRel, setLocalRel] = useState(association?.local_rel_path ?? '')
  const [browserOpen, setBrowserOpen] = useState(false)
  const associate = useAssociateDisk()
  const dissociate = useDissociateDisk()
  const enabled = association !== undefined
  const save = (feedback?: ReturnType<typeof autosaveFeedback>) =>
    associate.mutate(
      { torrentClientId, diskId: disk.id, torrentClientRootPath: clientRoot, localRelPath: localRel },
      feedback ?? { onError: (error) => toast.error(error.message), onSuccess: () => toast.success(t('torrentClients.mappingSaved')) },
    )
  const nazgarrSide = `${disk.root_path.replace(/\/$/, '')}${localRel ? `/${localRel}` : ''}`

  return (
    <div className="grid min-w-0 gap-3 rounded-md border px-3 py-2.5">
      <div className="flex min-w-0 items-center justify-between gap-2">
        <span className="font-medium">{disk.label}</span>
        <span className="min-w-0 flex-1 truncate font-mono text-xs text-muted-foreground" title={disk.root_path}>
          {disk.root_path}
        </span>
        <Switch
          checked={enabled}
          onCheckedChange={(checked) => {
            const feedback = autosaveFeedback(disk.label)
            if (checked) save(feedback)
            else dissociate.mutate({ torrentClientId, diskId: disk.id }, feedback)
          }}
        />
      </div>
      {enabled && (
        <div className="grid gap-2">
          {/* Una riga: cartella del disco = la stessa vista dal client. */}
          <div className="grid items-end gap-2 sm:grid-cols-[1fr_auto_1fr]">
            <div className="grid gap-1">
              <Label className="text-xs text-muted-foreground">{t('torrentClients.mappingNazgarrFolder')}</Label>
              <div className="flex gap-1">
                <Input className="h-8 font-mono text-xs" value={localRel} onChange={(e) => setLocalRel(e.target.value)}
                       placeholder={t('torrentClients.mappingDiskRoot')} />
                <Button variant="outline" size="sm" className="h-8 px-2" title={t('torrentClients.mappingBrowse')}
                        onClick={() => setBrowserOpen(true)}>
                  <FolderOpenIcon className="size-4" />
                </Button>
              </div>
            </div>
            <span className="hidden pb-1.5 text-muted-foreground sm:block">=</span>
            <div className="grid gap-1">
              <Label className="text-xs text-muted-foreground">{t('torrentClients.mappingClientFolder')}</Label>
              <Input className="h-8 font-mono text-xs" value={clientRoot} onChange={(e) => setClientRoot(e.target.value)}
                     placeholder="/downloads" />
            </div>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs text-muted-foreground">
              {clientRoot ? (
                <>
                  {t('torrentClients.mappingPreview')} <code className="font-mono">{nazgarrSide}</code> →{' '}
                  <code className="font-mono">{clientRoot}</code>
                </>
              ) : (
                t('torrentClients.mappingSameExplained')
              )}
            </p>
            <Button variant="outline" size="sm" disabled={associate.isPending} onClick={() => save()}>
              {t('common.save')}
            </Button>
          </div>
          <DiskBrowserDialog diskId={disk.id} open={browserOpen} onOpenChange={setBrowserOpen}
                             title={t('torrentClients.mappingNazgarrFolder')} onSelect={(path) => setLocalRel(path)} />
        </div>
      )}
    </div>
  )
}

function DisksDialog({ torrentClientId, disks: associations }: { torrentClientId: number; disks: DiskAssociation[] }) {
  const [open, setOpen] = useState(false)
  const { data: disks } = useDisks()

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          <Button
            variant="ghost"
            size="icon-sm"
            title={t('torrentClients.enabledDisks')}
            data-tour="clients.disks"
            data-tour-filled={associations.length > 0 ? 'true' : undefined}
          >
            <HardDriveIcon className="size-4" />
          </Button>
        }
      />
      <DialogContent data-tour="clients.disks-dialog" className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('torrentClients.enabledDisksForClient')}</DialogTitle>
          <DialogDescription>{t('torrentClients.rootPathOverrideHelp')}</DialogDescription>
        </DialogHeader>
        {/* I tre casi tipici (retrospettiva del tutorial, 2026-10-05): cartella del disco = come la vede il client. */}
        <div className="grid gap-1.5 rounded-md bg-muted/40 p-3 text-xs">
          <p className="font-medium">{t('torrentClients.mappingExamples.title')}</p>
          {(['same', 'subfolder', 'unraid'] as const).map((key) => (
            <div key={key} className="grid gap-0.5 sm:grid-cols-[1fr_auto]">
              <span className="text-muted-foreground">{t(`torrentClients.mappingExamples.${key}`)}</span>
              <code className="font-mono">{t(`torrentClients.mappingExamples.${key}Value`)}</code>
            </div>
          ))}
          <p className="text-muted-foreground">{t('torrentClients.mappingExamples.check')}</p>
        </div>
        <div className="grid min-w-0 gap-2">
          {disks?.map((disk) => (
            <DiskAssociationRow
              key={disk.id}
              torrentClientId={torrentClientId}
              disk={disk}
              association={associations.find((a) => a.disk_id === disk.id)}
            />
          ))}
          {disks?.length === 0 && <p className="text-sm text-muted-foreground">{t('torrentClients.noDisksConfigured')}</p>}
        </div>
      </DialogContent>
    </Dialog>
  )
}

type LabelField = 'category_movie' | 'category_tv' | 'category_anime' | 'tags_upload' | 'tags_reseed'

// Tag separati da virgola: si salvano uscendo dal campo, se cambiati.
function TagsField({ tc, field, label }: { tc: TorrentClient; field: LabelField; label: string }) {
  const updateTorrentClient = useUpdateTorrentClient()
  const saved = (tc[field] as string | null | undefined) ?? ''
  const [value, setValue] = useState(saved)
  return (
    <>
      <Label htmlFor={`tc-${tc.id}-${field}`} className="text-xs font-normal text-muted-foreground">
        {label}
      </Label>
      <Input
        id={`tc-${tc.id}-${field}`}
        className="h-7 w-44 text-xs"
        value={value}
        placeholder={t('torrentClients.noTags')}
        onChange={(e) => setValue(e.target.value)}
        onBlur={() =>
          value.trim() !== saved &&
          updateTorrentClient.mutate({ id: tc.id, body: { [field]: value } }, autosaveFeedback(`${tc.label} · ${label}`))
        }
      />
    </>
  )
}

// Categoria e tag dei torrent che Nazgarr aggiunge a questo client (solo
// etichette: i file non si spostano). Le categorie sono quelle del client;
// senza categorie nel client, niente scelta.
function ClientLabels({ tc }: { tc: TorrentClient }) {
  const updateTorrentClient = useUpdateTorrentClient()
  const { data } = useTorrentClientCategories(tc.id)
  const categories = data?.status === 'ok' ? data.categories : []
  const setCategory = (field: LabelField, label: string) => (category: string | null) =>
    updateTorrentClient.mutate({ id: tc.id, body: { [field]: category } }, autosaveFeedback(`${tc.label} · ${label}`))
  const rows: [LabelField, string, string | undefined][] = [
    ['category_movie', t('torrentClients.categoryMovie'), undefined],
    ['category_tv', t('torrentClients.categoryTv'), undefined],
    ['category_anime', t('torrentClients.categoryAnime'), t('torrentClients.animeSameAs')],
  ]
  return (
    <div className="grid gap-2 border-t pt-3">
      <p className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase" title={t('torrentClients.labelsHelp')}>
        {t('torrentClients.labelsTitle')}
      </p>
      <div className="grid grid-cols-[auto_1fr] items-center gap-x-3 gap-y-1.5 text-xs">
        {categories.length > 0 || rows.some(([field]) => tc[field]) ? (
          rows.map(([field, label, noneLabel]) => (
            <Fragment key={field}>
              <span className="text-muted-foreground">{label}</span>
              <ClientCategorySelect
                categories={categories}
                value={(tc[field] as string | null | undefined) ?? null}
                noneLabel={noneLabel}
                onChange={setCategory(field, label)}
              />
            </Fragment>
          ))
        ) : (
          <>
            <span className="text-muted-foreground">{t('torrentClients.categories')}</span>
            <span className="text-muted-foreground">
              {data?.status === 'error' ? t('torrentClients.categoriesUnavailable') : t('torrentClients.noCategories')}
            </span>
          </>
        )}
        <TagsField tc={tc} field="tags_upload" label={t('torrentClients.tagsUpload')} />
        <TagsField tc={tc} field="tags_reseed" label={t('torrentClients.tagsReseed')} />
      </div>
    </div>
  )
}

export function TorrentClientsSection() {
  const { data: torrentClients, isPending } = useTorrentClients()
  const { data: disks } = useDisks()
  const updateTorrentClient = useUpdateTorrentClient()
  const deleteTorrentClient = useDeleteTorrentClient()

  const diskLabel = (id: number) => disks?.find((d) => d.id === id)?.label ?? `#${id}`

  return (
    <div className="grid content-start gap-4">
      <SettingsHeader title={t('config.tabClients')} description={t('torrentClients.sectionDescription')} action={<TorrentClientDialog />} />
      {isPending && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}
      {torrentClients?.length === 0 && (
        <Card>
          <CardContent className="py-6 text-center text-sm text-muted-foreground">
            {t('torrentClients.noClientsConfigured')}
          </CardContent>
        </Card>
      )}
      {/* Una scheda per client: tipo con il suo logo, indirizzo, dischi, quanti
          torrent ha nell'indice dell'ultima scan, e le azioni. */}
      <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
        {torrentClients?.map((tc) => (
          <Card key={tc.id} data-tour="clients.card" className={cn('min-w-0', !tc.enabled && 'opacity-70')}>
            <CardHeader className="flex flex-row items-center gap-3">
              <ClientLogo type={tc.adapter_type} />
              <div className="grid min-w-0 flex-1 gap-0.5">
                <CardTitle className="truncate text-base">{tc.label}</CardTitle>
                <span className="text-xs text-muted-foreground">
                  {CLIENT_NAMES[tc.adapter_type] ?? tc.adapter_type}
                  {tc.adapter_type === 'qui' && tc.qui_instance_id !== null ? ` · #${tc.qui_instance_id}` : ''}
                </span>
              </div>
              <Switch
                checked={tc.enabled}
                title={t('torrentClients.enabled')}
                onCheckedChange={(enabled) =>
                  updateTorrentClient.mutate({ id: tc.id, body: { enabled } }, autosaveFeedback(tc.label))
                }
              />
            </CardHeader>
            <CardContent className="grid min-w-0 gap-3 text-sm">
              <p className="truncate font-mono text-xs text-muted-foreground" title={tc.base_url}>
                {tc.base_url}
              </p>
              <div className="grid grid-cols-[auto_1fr] items-center gap-x-3 gap-y-1.5 text-xs">
                <span className="text-muted-foreground">{t('torrentClients.disks')}</span>
                <span className="flex flex-wrap gap-1">
                  {tc.disks.length === 0 && <span className="text-muted-foreground">{t('torrentClients.none')}</span>}
                  {tc.disks.map((assoc) => (
                    <Badge key={assoc.disk_id} variant="secondary">
                      {diskLabel(assoc.disk_id)}
                    </Badge>
                  ))}
                </span>
                <span className="text-muted-foreground">{t('torrentClients.torrents')}</span>
                <span className="tabular-nums">
                  {t('torrentClients.torrentCount', { count: tc.torrent_count })}
                  {tc.last_polled_at && (
                    <span className="text-muted-foreground"> · {t('torrentClients.lastScan', { when: relativeFromNow(tc.last_polled_at) })}</span>
                  )}
                </span>
              </div>
              <div data-tour="clients.labels">
                <ClientLabels tc={tc} />
              </div>
              <div className="flex flex-wrap items-center gap-1 border-t pt-3">
                <TestButton id={tc.id} />
                <PathCheckButton clientId={tc.id} clientLabel={tc.label} />
                <span className="flex-1" />
                <DisksDialog torrentClientId={tc.id} disks={tc.disks} />
                <TorrentClientDialog tc={tc} />
                <Button variant="ghost" size="icon-sm" title={t('common.delete')} onClick={() => deleteTorrentClient.mutate(tc.id)}>
                  <TrashIcon className="size-4" />
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
