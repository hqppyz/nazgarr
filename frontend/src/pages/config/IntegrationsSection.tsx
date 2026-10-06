import type { UseMutationResult } from '@tanstack/react-query'
import { PencilIcon, PlusIcon, TrashIcon, ZapIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import {
  type ArrKind,
  useCreateRadarrInstance,
  useCreateSonarrInstance,
  useDeleteRadarrInstance,
  useDeleteSonarrInstance,
  useRadarrInstances,
  useSonarrInstances,
  useTestRadarrConnection,
  useTestRadarrInstance,
  useTestSonarrConnection,
  useTestSonarrInstance,
  useUpdateRadarrInstance,
  useUpdateSonarrInstance,
} from '@/api/hooks/arrInstances'
import type { Schemas } from '@/api/client'
import { Button } from '@/components/ui/button'
import { ConfirmButton } from '@/components/ConfirmButton'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ServiceLogo } from '@/components/ServiceLogo'
import { ArrWebhookDialog } from '@/pages/config/ArrWebhookDialog'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { t } from '@/lib/i18n'
import { autosaveFeedback } from '@/lib/autosave'
import { arrConnectionBody, arrInstanceBody, emptyArrForm, type ArrInstanceForm } from '@/lib/arrInstanceForm'

// Radarr e Sonarr non sono ancora consumati da nessun adapter (nessun
// resolver li chiama davvero) — ma la tabella è già multi-istanza da
// subito, stesso pattern di Tracker/TorrentClient, per evitare una
// migrazione dolorosa quando arriverà l'adapter vero. Test Connection
// invece è reale già oggi: Radarr/Sonarr condividono lo stesso endpoint
// Servarr /api/v3/system/status, non serve un adapter completo per quello.
interface ArrInstance {
  id: number
  label: string
  base_url: string
  enabled: boolean
  priority: number
  timeout_seconds: number
  basic_auth_username: string | null
  webhook_enabled?: boolean
  webhook_last_event?: Schemas['ArrWebhookEventSummary'] | null
}

interface ArrInstanceWriteBody {
  label: string
  base_url: string
  api_key: string
  priority?: number
  timeout_seconds?: number
  basic_auth_username?: string
  basic_auth_password?: string
}

interface ArrInstanceUpdateBody {
  label?: string
  base_url?: string
  api_key?: string
  enabled?: boolean
  priority?: number
  timeout_seconds?: number
  basic_auth_username?: string
  basic_auth_password?: string
}

interface ArrConnectionTestBody {
  base_url: string
  api_key: string
  timeout_seconds?: number
  basic_auth_username?: string
  basic_auth_password?: string
}

interface ArrInstanceTestResult {
  status: string
  version?: string | null
  error?: string | null
}

function toastTestResult(result: ArrInstanceTestResult) {
  if (result.status === 'ok') toast.success(t('integrations.connectedSuccess', { version: result.version ?? '?' }))
  else toast.error(t('integrations.connectionFailed', { message: result.error ?? '' }))
}

function TestConnectionButton({
  onTest,
  isPending,
  disabled,
}: {
  onTest: () => void
  isPending: boolean
  disabled?: boolean
}) {
  return (
    <Button type="button" variant="outline" onClick={onTest} disabled={disabled || isPending}>
      <ZapIcon className="size-4" />
      {t('integrations.testConnection')}
    </Button>
  )
}

function BasicAuthFields({
  enabled,
  onEnabledChange,
  username,
  onUsernameChange,
  password,
  onPasswordChange,
  passwordPlaceholder,
}: {
  enabled: boolean
  onEnabledChange: (enabled: boolean) => void
  username: string
  onUsernameChange: (value: string) => void
  password: string
  onPasswordChange: (value: string) => void
  passwordPlaceholder?: string
}) {
  return (
    <div className="grid gap-3 rounded-md border p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <Label>{t('integrations.basicAuth')}</Label>
          <p className="text-xs text-muted-foreground">{t('integrations.basicAuthDescription')}</p>
        </div>
        <Switch checked={enabled} onCheckedChange={onEnabledChange} />
      </div>
      {enabled && (
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="grid gap-1.5">
            <Label>{t('integrations.basicAuthUsername')}</Label>
            <Input value={username} onChange={(e) => onUsernameChange(e.target.value)} />
          </div>
          <div className="grid gap-1.5">
            <Label>{t('integrations.basicAuthPassword')}</Label>
            <Input
              type="password"
              value={password}
              onChange={(e) => onPasswordChange(e.target.value)}
              placeholder={passwordPlaceholder}
            />
          </div>
        </div>
      )}
    </div>
  )
}

// Aggiungere (senza instance) o modificare un'istanza: gli stessi campi.
// Modificando, una API key non ridigitata (write-only) resta quella salvata, e
// la prova usa le credenziali salvate.
function ArrInstanceDialog({
  serviceName,
  urlPlaceholder,
  instance,
  createMutation,
  updateMutation,
  testConnectionMutation,
  testInstanceMutation,
}: {
  serviceName: string
  urlPlaceholder?: string
  instance?: ArrInstance
  createMutation?: UseMutationResult<ArrInstance, Error, ArrInstanceWriteBody>
  updateMutation?: UseMutationResult<ArrInstance, Error, { id: number; body: ArrInstanceUpdateBody }>
  testConnectionMutation: UseMutationResult<ArrInstanceTestResult, Error, ArrConnectionTestBody>
  testInstanceMutation?: UseMutationResult<ArrInstanceTestResult, Error, number>
}) {
  const editing = instance != null
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState<ArrInstanceForm>(() => emptyArrForm(instance))
  const set = <K extends keyof ArrInstanceForm>(field: K) => (value: ArrInstanceForm[K]) =>
    setForm((f) => ({ ...f, [field]: value }))
  const idPrefix = editing ? 'arr-edit' : 'arr-add'
  const pending = createMutation?.isPending || updateMutation?.isPending

  function submit() {
    const onError = (error: Error) =>
      toast.error(t(editing ? 'common.saveFailed' : 'integrations.createInstanceFailed', { message: error.message }))
    if (editing && updateMutation) {
      updateMutation.mutate(
        { id: instance.id, body: arrInstanceBody(form, true) },
        { onSuccess: () => { setOpen(false); setForm((f) => ({ ...f, apiKey: '', basicAuthPassword: '' })) }, onError },
      )
    } else if (createMutation) {
      createMutation.mutate(arrInstanceBody(form, false) as ArrInstanceWriteBody, {
        onSuccess: () => { setOpen(false); setForm(emptyArrForm()) },
        onError,
      })
    }
  }

  function test() {
    // La richiesta stessa fallita (rete, Nazgarr irraggiungibile): prima non si vedeva niente.
    const handlers = { onSuccess: toastTestResult, onError: (error: Error) => toast.error(error.message) }
    if (editing && !form.apiKey && testInstanceMutation) testInstanceMutation.mutate(instance.id, handlers)
    else testConnectionMutation.mutate(arrConnectionBody(form), handlers)
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          editing ? (
            <Button variant="ghost" size="icon-sm" title={t('common.edit')}>
              <PencilIcon className="size-4" />
            </Button>
          ) : (
            <Button size="sm">
              <PlusIcon className="size-4" />
              {t('integrations.addInstance')}
            </Button>
          )
        }
      />
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {t(editing ? 'integrations.editInstanceTitled' : 'integrations.addInstanceTitled', { name: serviceName })}
          </DialogTitle>
        </DialogHeader>
        <div className="grid gap-5">
          <div className="grid gap-1.5">
            <Label htmlFor={`${idPrefix}-label`}>{t('integrations.instanceLabel')}</Label>
            <Input id={`${idPrefix}-label`} value={form.label} onChange={(e) => set('label')(e.target.value)} />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor={`${idPrefix}-url`}>{t('integrations.instanceUrl')}</Label>
            <Input id={`${idPrefix}-url`} value={form.baseUrl} onChange={(e) => set('baseUrl')(e.target.value)} />
            {!editing && urlPlaceholder && (
              <p className="text-xs text-muted-foreground">{t('integrations.urlSuggestion', { url: urlPlaceholder })}</p>
            )}
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor={`${idPrefix}-key`}>{t('integrations.instanceApiKey')}</Label>
            <Input
              id={`${idPrefix}-key`}
              type="password"
              value={form.apiKey}
              onChange={(e) => set('apiKey')(e.target.value)}
              placeholder={editing ? t('common.leaveBlank') : undefined}
            />
            <p className="text-xs text-muted-foreground">{t('integrations.apiKeyHelp', { name: serviceName })}</p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <Label htmlFor={`${idPrefix}-priority`}>{t('integrations.priority')}</Label>
              <Input id={`${idPrefix}-priority`} type="number" value={form.priority} onChange={(e) => set('priority')(e.target.value)} />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor={`${idPrefix}-timeout`}>{t('integrations.timeoutSeconds')}</Label>
              <Input
                id={`${idPrefix}-timeout`}
                type="number"
                value={form.timeoutSeconds}
                onChange={(e) => set('timeoutSeconds')(e.target.value)}
              />
            </div>
          </div>
          <p className="-mt-3 text-xs text-muted-foreground">{t('integrations.priorityHelp')}</p>
          <BasicAuthFields
            enabled={form.basicAuth}
            onEnabledChange={set('basicAuth')}
            username={form.basicAuthUsername}
            onUsernameChange={set('basicAuthUsername')}
            password={form.basicAuthPassword}
            onPasswordChange={set('basicAuthPassword')}
            passwordPlaceholder={editing ? t('common.leaveBlank') : undefined}
          />
        </div>
        <DialogFooter className="sm:justify-between">
          <TestConnectionButton
            onTest={test}
            isPending={testConnectionMutation.isPending || (testInstanceMutation?.isPending ?? false)}
            disabled={!form.baseUrl || (!editing && !form.apiKey)}
          />
          <Button
            onClick={submit}
            disabled={
              !form.label || !form.baseUrl || (!editing && !form.apiKey) ||
              (form.basicAuth && !form.basicAuthUsername) || pending
            }
          >
            {t('common.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ArrInstancesCard({
  kind,
  title,
  logoSrc,
  urlPlaceholder,
  instances,
  isPending,
  createMutation,
  updateMutation,
  deleteMutation,
  testConnectionMutation,
  testInstanceMutation,
  tour,
}: {
  kind: ArrKind
  tour: string
  title: string
  logoSrc: string
  urlPlaceholder: string
  instances: ArrInstance[] | undefined
  isPending: boolean
  createMutation: UseMutationResult<ArrInstance, Error, ArrInstanceWriteBody>
  updateMutation: UseMutationResult<ArrInstance, Error, { id: number; body: ArrInstanceUpdateBody }>
  deleteMutation: UseMutationResult<void, Error, number>
  testConnectionMutation: UseMutationResult<ArrInstanceTestResult, Error, ArrConnectionTestBody>
  testInstanceMutation: UseMutationResult<ArrInstanceTestResult, Error, number>
}) {
  const actions = (instance: ArrInstance) => (
    <>
      <ArrWebhookDialog kind={kind} instance={instance} serviceName={title} />
      <ArrInstanceDialog
        serviceName={title}
        instance={instance}
        updateMutation={updateMutation}
        testConnectionMutation={testConnectionMutation}
        testInstanceMutation={testInstanceMutation}
      />
      <ConfirmButton
        trigger={
          <Button variant="ghost" size="icon-sm" title={t('common.delete')}>
            <TrashIcon className="size-4" />
          </Button>
        }
        title={t('integrations.deleteInstanceTitle', { label: instance.label })}
        description={t('integrations.deleteInstanceDescription', { name: title })}
        pending={deleteMutation.isPending}
        onConfirm={() => deleteMutation.mutate(instance.id)}
      />
    </>
  )
  return (
    <Card data-tour={tour} data-tour-filled={instances?.length ? 'true' : undefined}>
      <CardHeader>
        <div className="flex w-full items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <ServiceLogo src={logoSrc} alt={title} />
            <CardTitle>{title}</CardTitle>
          </div>
          <ArrInstanceDialog
            serviceName={title}
            urlPlaceholder={urlPlaceholder}
            createMutation={createMutation}
            testConnectionMutation={testConnectionMutation}
          />
        </div>
        <CardDescription>{t('integrations.arrUsageDescription')}</CardDescription>
      </CardHeader>
      <CardContent>
        {/* Da telefono cinque colonne non ci stanno (URL intero, azioni fuori
            schermo): una riga per istanza, URL sotto il nome. */}
        <ul className="divide-y sm:hidden">
          {isPending && <li className="py-2 text-center text-sm text-muted-foreground">{t('common.loading')}</li>}
          {instances?.map((instance) => (
            <li key={instance.id} className="grid gap-1 py-2">
              <div className="flex items-center gap-2">
                <span className="min-w-0 flex-1 truncate font-medium">{instance.label}</span>
                <Switch
                  checked={instance.enabled}
                  aria-label={t('integrations.instanceEnabled')}
                  onCheckedChange={(enabled) =>
                    updateMutation.mutate({ id: instance.id, body: { enabled } }, autosaveFeedback(instance.label))
                  }
                />
                {actions(instance)}
              </div>
              <p className="font-mono text-xs break-all text-muted-foreground">
                {instance.base_url} · {t('integrations.priority')} {instance.priority}
              </p>
            </li>
          ))}
          {instances?.length === 0 && (
            <li className="py-2 text-center text-sm text-muted-foreground">{t('integrations.noInstances')}</li>
          )}
        </ul>
        <div className="hidden sm:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('integrations.instanceLabel')}</TableHead>
              <TableHead>{t('integrations.instanceUrl')}</TableHead>
              <TableHead>{t('integrations.priority')}</TableHead>
              <TableHead>{t('integrations.instanceEnabled')}</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {isPending && (
              <TableRow>
                <TableCell colSpan={5} className="text-center text-sm text-muted-foreground">
                  {t('common.loading')}
                </TableCell>
              </TableRow>
            )}
            {instances?.map((instance) => (
              <TableRow key={instance.id}>
                <TableCell className="font-medium">{instance.label}</TableCell>
                <TableCell className="max-w-64 truncate font-mono text-xs" title={instance.base_url}>
                  {instance.base_url}
                </TableCell>
                <TableCell className="font-mono text-xs">{instance.priority}</TableCell>
                <TableCell>
                  <Switch
                    checked={instance.enabled}
                    onCheckedChange={(enabled) =>
                      updateMutation.mutate({ id: instance.id, body: { enabled } }, autosaveFeedback(instance.label))
                    }
                  />
                </TableCell>
                {/* I pulsanti in un div: un TableCell flex non è più una cella
                    e scompagina la riga. */}
                <TableCell>
                  <div className="flex justify-end gap-1">{actions(instance)}</div>
                </TableCell>
              </TableRow>
            ))}
            {instances?.length === 0 && (
              <TableRow>
                <TableCell colSpan={5} className="text-center text-sm text-muted-foreground">
                  {t('integrations.noInstances')}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
        </div>
      </CardContent>
    </Card>
  )
}

export function IntegrationsSection() {
  const { data: radarrInstances, isPending: radarrPending } = useRadarrInstances()
  const createRadarrInstance = useCreateRadarrInstance()
  const updateRadarrInstance = useUpdateRadarrInstance()
  const deleteRadarrInstance = useDeleteRadarrInstance()
  const testRadarrConnection = useTestRadarrConnection()
  const testRadarrInstance = useTestRadarrInstance()

  const { data: sonarrInstances, isPending: sonarrPending } = useSonarrInstances()
  const createSonarrInstance = useCreateSonarrInstance()
  const updateSonarrInstance = useUpdateSonarrInstance()
  const deleteSonarrInstance = useDeleteSonarrInstance()
  const testSonarrConnection = useTestSonarrConnection()
  const testSonarrInstance = useTestSonarrInstance()

  return (
    <>
      <ArrInstancesCard
        kind="radarr"
        tour="integrations.radarr"
        title="Radarr"
        logoSrc="/logos/radarr.svg"
        urlPlaceholder="http://radarr:7878"
        instances={radarrInstances}
        isPending={radarrPending}
        createMutation={createRadarrInstance}
        updateMutation={updateRadarrInstance}
        deleteMutation={deleteRadarrInstance}
        testConnectionMutation={testRadarrConnection}
        testInstanceMutation={testRadarrInstance}
      />

      <ArrInstancesCard
        kind="sonarr"
        tour="integrations.sonarr"
        title="Sonarr"
        logoSrc="/logos/sonarr.svg"
        urlPlaceholder="http://sonarr:8989"
        instances={sonarrInstances}
        isPending={sonarrPending}
        createMutation={createSonarrInstance}
        updateMutation={updateSonarrInstance}
        deleteMutation={deleteSonarrInstance}
        testConnectionMutation={testSonarrConnection}
        testInstanceMutation={testSonarrInstance}
      />
    </>
  )
}
