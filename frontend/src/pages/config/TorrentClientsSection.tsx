import { HardDriveIcon, PencilIcon, PlusIcon, TrashIcon, ZapIcon } from 'lucide-react'
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
import { CLIENT_NAMES } from '@/lib/services'
import { ClientLogo } from '@/pages/config/ServiceIcons'

type TorrentClient = Schemas['TorrentClientResponse']
type Disk = Schemas['DiskResponse']
type DiskAssociation = Schemas['DiskAssociationResponse']

const ADAPTER_TYPES = [
  { value: 'qbittorrent', label: 'qBittorrent' },
  { value: 'qui', label: t('torrentClients.quiLabel') },
]

// I client dei plugin, con i campi che dichiarano.
function usePluginClientTypes() {
  const { data } = usePlugins()
  return (data?.adapters ?? []).filter((a) => a.kind === 'torrent_client' && a.plugin)
}

function AddTorrentClientDialog() {
  const [open, setOpen] = useState(false)
  const [label, setLabel] = useState('')
  const [adapterType, setAdapterType] = useState<string>('qbittorrent')
  const pluginTypes = usePluginClientTypes()
  const pluginSpec = pluginTypes.find((a) => a.adapter_type === adapterType)
  const [config, setConfig] = useState<ConfigValues>({})
  const typeOptions = [
    ...ADAPTER_TYPES,
    ...pluginTypes.map((a) => ({ value: a.adapter_type, label: `${a.label} · ${a.plugin}` })),
  ]
  const [baseUrl, setBaseUrl] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [apiToken, setApiToken] = useState('')
  const [quiInstanceId, setQuiInstanceId] = useState('')
  const createTorrentClient = useCreateTorrentClient()
  const isQui = adapterType === 'qui'

  function reset() {
    setLabel('')
    setBaseUrl('')
    setUsername('')
    setPassword('')
    setApiToken('')
    setQuiInstanceId('')
    setConfig({})
  }

  function submit() {
    createTorrentClient.mutate(
      {
        label,
        adapter_type: adapterType,
        base_url: baseUrl,
        username: isQui ? undefined : username || undefined,
        password: isQui ? undefined : password || undefined,
        api_token: isQui ? apiToken || undefined : undefined,
        qui_instance_id: isQui && quiInstanceId ? Number(quiInstanceId) : undefined,
        ...(pluginSpec ? { username: undefined, password: undefined, config: configPayload(pluginSpec.config_fields, config) } : {}),
      },
      {
        onSuccess: () => {
          setOpen(false)
          reset()
        },
        onError: (error) => toast.error(t('torrentClients.creationFailed', { message: error.message })),
      },
    )
  }

  const canSubmit =
    label &&
    baseUrl &&
    (pluginSpec ? !missingRequired(pluginSpec.config_fields, config) : isQui ? apiToken && quiInstanceId : true)

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button data-tour="clients.add"><PlusIcon className="size-4" />{t('torrentClients.addClient')}</Button>} />
      <DialogContent data-tour="clients.dialog">
        <DialogHeader>
          <DialogTitle>{t('torrentClients.addTorrentClient')}</DialogTitle>
        </DialogHeader>
        <div className="grid gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor="tc-label">{t('torrentClients.label')}</Label>
            <Input id="tc-label" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="qbit" />
          </div>
          <div className="grid gap-1.5" data-tour="clients.dialog.type">
            <Label>{t('torrentClients.type')}</Label>
            <Select
              value={adapterType}
              onValueChange={(v) => {
                if (v == null) return
                setAdapterType(v)
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
            <p className="text-xs text-muted-foreground">{t('torrentClients.plannedAdapters')}</p>
          </div>
          <div className="grid gap-1.5" data-tour="clients.dialog.url">
            <Label htmlFor="tc-base-url">{t('torrentClients.url')}</Label>
            <Input
              id="tc-base-url"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder={isQui ? 'http://qui:7476' : 'http://qbittorrent:8080'}
            />
          </div>
          {pluginSpec ? (
            <AdapterConfigFields idPrefix="tc-config" fields={pluginSpec.config_fields} values={config} onChange={setConfig} />
          ) : isQui ? (
            <div className="grid gap-3" data-tour="clients.dialog.credentials">
              <div className="grid gap-1.5">
                <Label htmlFor="tc-api-token">{t('torrentClients.apiKey')}</Label>
                <Input
                  id="tc-api-token"
                  type="password"
                  value={apiToken}
                  onChange={(e) => setApiToken(e.target.value)}
                  placeholder={t('torrentClients.apiKeyPlaceholder')}
                />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="tc-qui-instance-id">{t('torrentClients.instance')}</Label>
                <Input
                  id="tc-qui-instance-id"
                  type="number"
                  value={quiInstanceId}
                  onChange={(e) => setQuiInstanceId(e.target.value)}
                  placeholder={t('torrentClients.instanceIdPlaceholder')}
                />
                <p className="text-xs text-muted-foreground">{t('torrentClients.instanceHelp')}</p>
              </div>
            </div>
          ) : (
            <div className="grid gap-3" data-tour="clients.dialog.credentials">
              <div className="grid gap-1.5">
                <Label htmlFor="tc-username">{t('torrentClients.username')}</Label>
                <Input id="tc-username" value={username} onChange={(e) => setUsername(e.target.value)} />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="tc-password">{t('torrentClients.password')}</Label>
                <Input id="tc-password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
              </div>
            </div>
          )}
        </div>
        <DialogFooter>
          <Button data-tour="clients.dialog.create" onClick={submit} disabled={!canSubmit || createTorrentClient.isPending}>
            {t('torrentClients.create')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function EditTorrentClientDialog({ tc }: { tc: TorrentClient }) {
  const [open, setOpen] = useState(false)
  const [label, setLabel] = useState(tc.label)
  const [baseUrl, setBaseUrl] = useState(tc.base_url)
  const [username, setUsername] = useState(tc.username ?? '')
  const [password, setPassword] = useState('')
  const [apiToken, setApiToken] = useState('')
  const [quiInstanceId, setQuiInstanceId] = useState(tc.qui_instance_id?.toString() ?? '')
  const updateTorrentClient = useUpdateTorrentClient()
  const isQui = tc.adapter_type === 'qui'
  const pluginSpec = usePluginClientTypes().find((a) => a.adapter_type === tc.adapter_type)
  const secretsSet = (tc.config as { secrets_set?: string[] }).secrets_set ?? []
  const [config, setConfig] = useState<ConfigValues | null>(null)
  const configValues =
    config ?? (pluginSpec ? initialConfigValues(pluginSpec.config_fields, (tc.config as { values?: Record<string, unknown> }).values) : {})

  function submit() {
    updateTorrentClient.mutate(
      {
        id: tc.id,
        body: {
          label,
          base_url: baseUrl,
          username: isQui ? undefined : username || undefined,
          password: isQui ? undefined : password || undefined,
          api_token: isQui ? apiToken || undefined : undefined,
          qui_instance_id: isQui && quiInstanceId ? Number(quiInstanceId) : undefined,
          ...(pluginSpec
            ? { username: undefined, password: undefined, config: configPayload(pluginSpec.config_fields, configValues) }
            : {}),
        },
      },
      {
        onSuccess: () => {
          setOpen(false)
          setPassword('')
          setApiToken('')
          setConfig(null)
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
          <DialogTitle>{t('torrentClients.editTorrentClient')}</DialogTitle>
          <DialogDescription>{t('torrentClients.typeNotEditable', { type: tc.adapter_type })}</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor="tc-edit-label">{t('torrentClients.label')}</Label>
            <Input id="tc-edit-label" value={label} onChange={(e) => setLabel(e.target.value)} />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="tc-edit-base-url">{t('torrentClients.url')}</Label>
            <Input id="tc-edit-base-url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
          </div>
          {pluginSpec ? (
            <AdapterConfigFields
              idPrefix={`tc-edit-config-${tc.id}`}
              fields={pluginSpec.config_fields}
              values={configValues}
              secretsSet={secretsSet}
              onChange={setConfig}
            />
          ) : isQui ? (
            <>
              <div className="grid gap-1.5">
                <Label htmlFor="tc-edit-api-token">{t('torrentClients.apiKey')}</Label>
                <Input
                  id="tc-edit-api-token"
                  type="password"
                  value={apiToken}
                  onChange={(e) => setApiToken(e.target.value)}
                  placeholder={t('torrentClients.leaveEmptyToKeep')}
                />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="tc-edit-qui-instance-id">{t('torrentClients.instance')}</Label>
                <Input
                  id="tc-edit-qui-instance-id"
                  type="number"
                  value={quiInstanceId}
                  onChange={(e) => setQuiInstanceId(e.target.value)}
                />
              </div>
            </>
          ) : (
            <>
              <div className="grid gap-1.5">
                <Label htmlFor="tc-edit-username">{t('torrentClients.username')}</Label>
                <Input id="tc-edit-username" value={username} onChange={(e) => setUsername(e.target.value)} />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="tc-edit-password">{t('torrentClients.password')}</Label>
                <Input
                  id="tc-edit-password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={t('torrentClients.leaveEmptyToKeep')}
                />
              </div>
            </>
          )}
        </div>
        <DialogFooter>
          <Button
            onClick={submit}
            disabled={
              !label ||
              !baseUrl ||
              updateTorrentClient.isPending ||
              (pluginSpec != null && missingRequired(pluginSpec.config_fields, configValues, secretsSet))
            }
          >
            {t('common.save')}
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
      variant="ghost"
      size="icon-sm"
      data-tour="clients.test"
      title={t('torrentClients.testConnection')}
      onClick={() =>
        test.mutate(id, {
          onSuccess: (result) => {
            if (result.status === 'ok') toast.success(t('torrentClients.connectedSuccess', { count: result.torrents_found }))
            else toast.error(result.error ?? t('torrentClients.connectionFailed'))
          },
        })
      }
    >
      <ZapIcon className="size-4" />
    </Button>
  )
}

function DiskAssociationRow({
  torrentClientId,
  disk,
  association,
}: {
  torrentClientId: number
  disk: Disk
  association: DiskAssociation | undefined
}) {
  const [draft, setDraft] = useState(association?.torrent_client_root_path ?? '')
  const associate = useAssociateDisk()
  const dissociate = useDissociateDisk()
  const enabled = association !== undefined

  return (
    <div className="grid gap-1.5 rounded border px-3 py-2">
      <div className="flex items-center justify-between">
        <span className="text-sm">{disk.label}</span>
        <Switch
          checked={enabled}
          onCheckedChange={(checked) => {
            const feedback = autosaveFeedback(disk.label)
            if (checked) associate.mutate({ torrentClientId, diskId: disk.id, torrentClientRootPath: draft }, feedback)
            else dissociate.mutate({ torrentClientId, diskId: disk.id }, feedback)
          }}
        />
      </div>
      {enabled && (
        <div className="flex items-center gap-2">
          <Input
            className="h-8 font-mono text-xs"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={t('torrentClients.rootPathOverridePlaceholder')}
          />
          <Button
            variant="outline"
            size="sm"
            disabled={associate.isPending}
            onClick={() => associate.mutate({ torrentClientId, diskId: disk.id, torrentClientRootPath: draft })}
          >
            {t('common.save')}
          </Button>
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
      <DialogContent data-tour="clients.disks-dialog">
        <DialogHeader>
          <DialogTitle>{t('torrentClients.enabledDisksForClient')}</DialogTitle>
          <DialogDescription>{t('torrentClients.rootPathOverrideHelp')}</DialogDescription>
        </DialogHeader>
        <div className="grid gap-2">
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
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">Torrent clients</h2>
        <AddTorrentClientDialog />
      </div>
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
              <div className="flex justify-end gap-1 border-t pt-3">
                <TestButton id={tc.id} />
                <DisksDialog torrentClientId={tc.id} disks={tc.disks} />
                <EditTorrentClientDialog tc={tc} />
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
