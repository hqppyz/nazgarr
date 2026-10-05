import { ExternalLinkIcon, PencilIcon, PlusIcon, ServerIcon, TrashIcon, ZapIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import {
  useCreateInstance,
  useDeleteInstance,
  useInstances,
  useSetLocalName,
  useTestInstance,
  useUpdateInstance,
  type Instance,
} from '@/api/hooks/instances'
import { instanceDot } from '@/components/instances/InstanceSwitcher'
import { SettingsHeader } from '@/components/SettingsHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ConfirmButton } from '@/components/ConfirmButton'
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
import { t } from '@/lib/i18n'
import { activeInstanceId, switchInstance } from '@/lib/instance'
import { safeHref } from '@/lib/safeUrl'
import { cn } from '@/lib/utils'

// Aggiungere o modificare un'istanza: nome, indirizzo, API key (nazgarr/integrations/instances.py).
// La chiave non torna mai indietro dal server: in modifica, vuota = la stessa.
function InstanceDialog({ instance }: { instance?: Instance }) {
  const [open, setOpen] = useState(false)
  const [label, setLabel] = useState(instance?.label ?? '')
  const [url, setUrl] = useState(instance?.base_url ?? '')
  const [apiKey, setApiKey] = useState('')
  const create = useCreateInstance()
  const update = useUpdateInstance()
  const pending = create.isPending || update.isPending

  function submit() {
    const done = {
      onSuccess: (saved: Instance) => {
        setOpen(false)
        setApiKey('')
        const status = saved.status?.status
        if (status === 'ok') toast.success(`${saved.label}: ${t('instances.status.ok')}`)
        else toast.warning(`${saved.label}: ${t(`instances.status.${status ?? 'unreachable'}`)}`)
      },
      onError: (error: Error) => toast.error(error.message),
    }
    if (instance) update.mutate({ id: instance.id, body: { label, base_url: url, api_key: apiKey || null } }, done)
    else create.mutate({ label, base_url: url, api_key: apiKey }, done)
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          instance ? (
            <Button variant="ghost" size="icon-sm" title={t('common.edit')}>
              <PencilIcon className="size-4" />
            </Button>
          ) : (
            <Button data-tour="instances.add">
              <PlusIcon className="size-4" />
              {t('instances.add')}
            </Button>
          )
        }
      />
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{instance ? instance.label : t('instances.add')}</DialogTitle>
          <DialogDescription>{t('instances.description')}</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor="instance-label">{t('instances.label')}</Label>
            <Input id="instance-label" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Seedbox" />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="instance-url">{t('instances.url')}</Label>
            <Input id="instance-url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="http://nas:3019" />
            <p className="text-xs text-muted-foreground">{t('instances.urlHelp')}</p>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="instance-key">{t('instances.apiKey')}</Label>
            <Input id="instance-key" type="password" autoComplete="off" value={apiKey}
                   onChange={(e) => setApiKey(e.target.value)} placeholder="nzg_…" />
            <p className="text-xs text-muted-foreground">
              {instance ? t('instances.newApiKeyHelp') : t('instances.apiKeyHelp')}
            </p>
          </div>
        </div>
        <DialogFooter>
          <Button onClick={submit} disabled={pending || !label || !url || (!instance && !apiKey)}>
            {instance ? t('common.save') : t('instances.create')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function StatusLines({ instance }: { instance: Instance }) {
  const status = instance.status
  if (!status) return <span className="text-xs text-muted-foreground">{t('instances.loading')}</span>
  return (
    <div className="grid gap-1 text-xs">
      <span className="flex flex-wrap items-center gap-1.5">
        <span className={cn('size-2 rounded-full', instanceDot(instance))} />
        {t(`instances.status.${status.status}`)}
        {status.version && <span className="text-muted-foreground">· {t('instances.version', { version: status.version })}</span>}
        {status.level && (
          <Badge variant="secondary" className="h-4 px-1.5 text-[10px]">{t(`instances.level.${status.level}`)}</Badge>
        )}
      </span>
      {status.status === 'ok' && (
        <span className={cn('text-muted-foreground', status.compatibility.startsWith('block') && 'text-red-600 dark:text-red-400',
                            status.compatibility === 'warn' && 'text-amber-600 dark:text-amber-400')}>
          {t(`instances.compat.${status.compatibility}`)}
        </span>
      )}
      {status.error && <span className="break-words text-muted-foreground">{status.error}</span>}
    </div>
  )
}

function LocalNameCard({ saved }: { saved: string }) {
  const [name, setName] = useState(saved)
  const save = useSetLocalName()
  return (
    <Card>
      <CardContent className="grid gap-2 py-4">
        <Label htmlFor="instance-local-name">{t('instances.localName')}</Label>
        <form className="flex max-w-md gap-2"
              onSubmit={(e) => {
                e.preventDefault()
                save.mutate(name, { onSuccess: () => toast.success(t('common.saved')) })
              }}>
          <Input id="instance-local-name" value={name} maxLength={60}
                 placeholder={t('instances.thisInstance')} onChange={(e) => setName(e.target.value)} />
          <Button type="submit" variant="outline" disabled={save.isPending || name.trim() === saved}>
            {t('common.save')}
          </Button>
        </form>
        <p className="text-xs text-muted-foreground">{t('instances.localNameHelp')}</p>
      </CardContent>
    </Card>
  )
}

export function InstancesSection() {
  const { data, isPending } = useInstances(true)
  const remove = useDeleteInstance()
  const test = useTestInstance()
  const current = activeInstanceId()

  return (
    <div className="grid content-start gap-4">
      <SettingsHeader title={t('instances.title')} description={t('instances.description')} action={<InstanceDialog />} />
      {isPending && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}
      {data && <LocalNameCard key={data.local_name ?? ''} saved={data.local_name ?? ''} />}
      {data?.instances.length === 0 && (
        <Card>
          <CardContent className="py-6 text-center text-sm text-muted-foreground">{t('instances.none')}</CardContent>
        </Card>
      )}
      <div className="grid gap-4 xl:grid-cols-2 2xl:grid-cols-3">
        {data?.instances.map((instance) => (
          <Card key={instance.id} className="min-w-0">
            <CardHeader className="flex flex-row items-center gap-3">
              <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-muted">
                <ServerIcon className="size-4.5 text-muted-foreground" />
              </span>
              <div className="grid min-w-0 flex-1 gap-0.5">
                <CardTitle className="truncate text-base">{instance.label}</CardTitle>
                <a href={safeHref(instance.base_url)} target="_blank" rel="noreferrer"
                   className="flex items-center gap-1 truncate font-mono text-xs text-muted-foreground hover:underline">
                  {instance.base_url}
                  <ExternalLinkIcon className="size-3 shrink-0" />
                </a>
              </div>
            </CardHeader>
            <CardContent className="grid min-w-0 gap-3 text-sm">
              <StatusLines instance={instance} />
              <div className="flex items-center gap-1 border-t pt-3">
                <Button variant="outline" size="sm" disabled={test.isPending} onClick={() => test.mutate(instance.id)}>
                  <ZapIcon className="size-4" />
                  {t('instances.test')}
                </Button>
                <Button variant="ghost" size="sm" disabled={current === instance.id}
                        onClick={() => switchInstance(instance.id)}>
                  {t('instances.open')}
                </Button>
                <span className="flex-1" />
                <InstanceDialog instance={instance} />
                {/* La stessa conferma degli altri elimina, non window.confirm. */}
                <ConfirmButton
                  trigger={
                    <Button variant="ghost" size="icon-sm" title={t('common.delete')}>
                      <TrashIcon className="size-4" />
                    </Button>
                  }
                  title={t('instances.removeTitle', { label: instance.label })}
                  description={t('instances.removeDescription')}
                  pending={remove.isPending}
                  onConfirm={() =>
                    remove.mutate(instance.id, { onSuccess: () => current === instance.id && switchInstance(null) })
                  }
                />
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
