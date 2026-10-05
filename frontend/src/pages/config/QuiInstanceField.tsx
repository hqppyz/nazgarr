import { ListIcon } from 'lucide-react'

import { useQuiInstances } from '@/api/hooks/torrentClients'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { t } from '@/lib/i18n'

// L'istanza di qui: "Carica le istanze" le chiede a qui con l'indirizzo e
// la API key del form (o quella salvata, modificando) e le mostra in un
// elenco; se non riesce, resta il numero da scrivere a mano.
export function QuiInstanceField({ idPrefix, baseUrl, apiToken, clientId, value, onChange, editing }: {
  idPrefix: string
  baseUrl: string
  apiToken: string
  clientId?: number
  value: string
  onChange: (value: string) => void
  editing: boolean
}) {
  const load = useQuiInstances()
  const instances = load.data?.status === 'ok' ? load.data.instances : null
  const canLoad = baseUrl.trim() !== '' && (apiToken.trim() !== '' || clientId !== undefined)
  const label = (id: string) => {
    const found = instances?.find((i) => String(i.id) === id)
    return found ? `#${found.id} · ${found.name}` : id ? `#${id}` : t('torrentClients.quiPickInstance')
  }
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={`${idPrefix}-qui-instance-id`}>{t('torrentClients.instance')}</Label>
      <div className="flex gap-2">
        {instances && instances.length > 0 ? (
          <Select value={value} onValueChange={(v) => onChange(String(v))}>
            <SelectTrigger id={`${idPrefix}-qui-instance-id`} className="flex-1">
              <SelectValue>{(v: string | null) => label(v ?? "")}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              {instances.map((instance) => (
                <SelectItem key={instance.id} value={String(instance.id)}>
                  <span className="grid">
                    <span>#{instance.id} · {instance.name}</span>
                    <span className="text-xs text-muted-foreground">
                      {instance.host}
                      {!instance.active ? ` · ${t('torrentClients.quiDisabled')}` : !instance.connected ? ` · ${t('torrentClients.quiDisconnected')}` : ''}
                    </span>
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <Input
            id={`${idPrefix}-qui-instance-id`}
            type="number"
            className="flex-1"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder={editing ? undefined : t('torrentClients.instanceIdPlaceholder')}
          />
        )}
        <Button
          type="button"
          variant="outline"
          disabled={!canLoad || load.isPending}
          onClick={() =>
            load.mutate({ base_url: baseUrl.trim(), api_token: apiToken.trim() || null, torrent_client_id: clientId ?? null })
          }
        >
          <ListIcon className="size-4" />
          {t('torrentClients.quiLoadInstances')}
        </Button>
      </div>
      {load.data?.status === 'error' && (
        <p className="text-xs text-red-700 dark:text-red-300">{t('torrentClients.quiLoadFailed', { error: load.data.error ?? '' })}</p>
      )}
      {load.error && <p className="text-xs text-red-700 dark:text-red-300">{load.error.message}</p>}
      {instances?.length === 0 && <p className="text-xs text-muted-foreground">{t('torrentClients.quiNoInstances')}</p>}
      {!editing && !instances && <p className="text-xs text-muted-foreground">{t('torrentClients.instanceHelp')}</p>}
    </div>
  )
}
