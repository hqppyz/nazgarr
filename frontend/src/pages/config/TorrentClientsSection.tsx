import { HardDriveIcon, PencilIcon, PlusIcon, TrashIcon, ZapIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { useDisks } from '@/api/hooks/disks'
import {
  useAssociateDisk,
  useCreateTorrentClient,
  useDeleteTorrentClient,
  useDissociateDisk,
  useTestTorrentClient,
  useTorrentClients,
  useUpdateTorrentClient,
} from '@/api/hooks/torrentClients'
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

function AddTorrentClientDialog() {
  const [open, setOpen] = useState(false)
  const [label, setLabel] = useState('')
  const [adapterType, setAdapterType] = useState<'qbittorrent' | 'qui'>('qbittorrent')
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

  const canSubmit = label && baseUrl && (isQui ? apiToken && quiInstanceId : true)

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button><PlusIcon className="size-4" />{t('torrentClients.addClient')}</Button>} />
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('torrentClients.addTorrentClient')}</DialogTitle>
        </DialogHeader>
        <div className="grid gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor="tc-label">{t('torrentClients.label')}</Label>
            <Input id="tc-label" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="qbit" />
          </div>
          <div className="grid gap-1.5">
            <Label>{t('torrentClients.type')}</Label>
            <Select value={adapterType} onValueChange={(v) => setAdapterType(v as 'qbittorrent' | 'qui')}>
              <SelectTrigger>
                <SelectValue>
                  {(v: string | null) => selectLabel(ADAPTER_TYPES, v, (a) => a.value, (a) => a.label, 'qBittorrent')}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {ADAPTER_TYPES.map((a) => (
                  <SelectItem key={a.value} value={a.value}>
                    {a.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">{t('torrentClients.plannedAdapters')}</p>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="tc-base-url">{t('torrentClients.url')}</Label>
            <Input
              id="tc-base-url"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder={isQui ? 'http://qui:7476' : 'http://qbittorrent:8080'}
            />
          </div>
          {isQui ? (
            <>
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
            </>
          ) : (
            <>
              <div className="grid gap-1.5">
                <Label htmlFor="tc-username">{t('torrentClients.username')}</Label>
                <Input id="tc-username" value={username} onChange={(e) => setUsername(e.target.value)} />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="tc-password">{t('torrentClients.password')}</Label>
                <Input id="tc-password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
              </div>
            </>
          )}
        </div>
        <DialogFooter>
          <Button onClick={submit} disabled={!canSubmit || createTorrentClient.isPending}>
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
        },
      },
      {
        onSuccess: () => {
          setOpen(false)
          setPassword('')
          setApiToken('')
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
          {isQui ? (
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
          <Button onClick={submit} disabled={!label || !baseUrl || updateTorrentClient.isPending}>
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
      <DialogTrigger render={<Button variant="ghost" size="icon-sm" title={t('torrentClients.enabledDisks')}><HardDriveIcon className="size-4" /></Button>} />
      <DialogContent>
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
          <Card key={tc.id} className={cn('min-w-0', !tc.enabled && 'opacity-70')}>
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
