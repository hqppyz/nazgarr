import { KeyRoundIcon, PlusIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { useApiKeys, useCreateApiKey, useRevokeApiKey } from '@/api/hooks/apiKeys'
import { OneTimeSecretDialog } from '@/components/OneTimeSecretDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { SettingsHeader } from '@/components/SettingsHeader'
import { Card, CardContent } from '@/components/ui/card'
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
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { ToggleGroupItem, ToggleGroupSingle } from '@/components/ui/toggle-group'
import { t } from '@/lib/i18n'
import { parseApiDate, relativeFromNow } from '@/lib/time'
import { cn } from '@/lib/utils'

function when(iso: string | null | undefined) {
  if (!iso) return null
  return { relative: relativeFromNow(iso), absolute: parseApiDate(iso).toLocaleString() }
}

// Nuova chiave: nome e accesso, in un dialog dal pulsante dell'intestazione
// (come i dischi, i client e i tracker). La chiave creata si vede una volta.
function AddApiKeyDialog({ onCreated }: { onCreated: (key: string) => void }) {
  const create = useCreateApiKey()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [level, setLevel] = useState<'read' | 'write'>('read')

  function submit() {
    create.mutate(
      { name, level },
      {
        onSuccess: (key) => {
          setOpen(false)
          setName('')
          setLevel('read')
          onCreated(key.key)
        },
        onError: (error) => toast.error(t('common.saveFailed', { message: error.message })),
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button data-tour="api-keys.add"><PlusIcon className="size-4" />{t('security.apiKeyAdd')}</Button>} />
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('security.apiKeyNewTitle')}</DialogTitle>
          <DialogDescription>{t('security.apiKeysDescription')}</DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            if (name.trim()) submit()
          }}
        >
          <div className="grid gap-1.5">
            <Label htmlFor="api-key-name">{t('security.apiKeyName')}</Label>
            <Input id="api-key-name" value={name} placeholder="grafana" onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="grid gap-1.5">
            <Label>{t('security.apiKeyAccess')}</Label>
            <ToggleGroupSingle value={level} onValueChange={(v) => v && setLevel(v as 'read' | 'write')} variant="outline">
              <ToggleGroupItem value="read">{t('security.apiKeyRead')}</ToggleGroupItem>
              <ToggleGroupItem value="write">{t('security.apiKeyWrite')}</ToggleGroupItem>
            </ToggleGroupSingle>
            <p className="text-xs text-muted-foreground">{t(`security.apiKeyLevelHelp.${level}`)}</p>
          </div>
          <DialogFooter>
            <Button type="submit" disabled={!name.trim() || create.isPending}>
              {t('security.apiKeyCreate')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// API key per servizi e script (header X-Api-Key): lettura = solo GET,
// scrittura = tutto tranne gestire le chiavi.
export function ApiKeysSection() {
  const { data: keys } = useApiKeys()
  const revoke = useRevokeApiKey()
  const [created, setCreated] = useState<string | null>(null)
  const [revoking, setRevoking] = useState<{ id: number; name: string } | null>(null)

  return (
    <>
      <SettingsHeader
        title={t('config.tabApiKeys')}
        description={t('security.apiKeysDescription')}
        action={<AddApiKeyDialog onCreated={setCreated} />}
      />
      <Card className="py-0">
        {(keys ?? []).length === 0 ? (
          <CardContent className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
            <KeyRoundIcon className="size-4" />
            {t('security.apiKeysNone')}
          </CardContent>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('security.apiKeyName')}</TableHead>
                <TableHead>{t('security.apiKeyColumnKey')}</TableHead>
                <TableHead>{t('security.apiKeyAccess')}</TableHead>
                <TableHead>{t('security.apiKeyColumnCreated')}</TableHead>
                <TableHead>{t('security.apiKeyColumnLastUsed')}</TableHead>
                <TableHead>{t('security.apiKeyColumnStatus')}</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {keys!.map((key) => {
                const createdAt = when(key.created_at)
                const usedAt = when(key.last_used_at)
                const revokedAt = when(key.revoked_at)
                return (
                  <TableRow key={key.id} className={cn(key.revoked_at && 'opacity-60')}>
                    <TableCell className="font-medium">{key.name}</TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">{key.prefix}…</TableCell>
                    <TableCell>
                      <Badge variant="outline">
                        {t(key.level === 'write' ? 'security.apiKeyWrite' : 'security.apiKeyRead')}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs whitespace-nowrap text-muted-foreground" title={createdAt?.absolute}>
                      {createdAt?.relative}
                    </TableCell>
                    <TableCell className="text-xs whitespace-nowrap text-muted-foreground" title={usedAt?.absolute}>
                      {usedAt?.relative ?? t('security.apiKeyNeverUsed')}
                    </TableCell>
                    <TableCell className="text-xs whitespace-nowrap">
                      {revokedAt ? (
                        <span className="text-muted-foreground" title={revokedAt.absolute}>
                          {t('security.apiKeyRevokedAt', { when: revokedAt.relative })}
                        </span>
                      ) : (
                        <span className="text-emerald-600 dark:text-emerald-400">{t('security.apiKeyActive')}</span>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      {!key.revoked_at && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-destructive hover:text-destructive"
                          onClick={() => setRevoking({ id: key.id, name: key.name })}
                        >
                          {t('security.apiKeyRevoke')}
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        )}
      </Card>

      {/* La chiave appena creata: l'unica volta che si vede. */}
      <OneTimeSecretDialog
        secret={created}
        title={t('security.apiKeyCreatedTitle')}
        description={t('security.apiKeyCreatedDescription')}
        onClose={() => setCreated(null)}
      />

      <Dialog open={revoking !== null} onOpenChange={(open) => !open && setRevoking(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('security.apiKeyRevokeTitle', { name: revoking?.name ?? '' })}</DialogTitle>
            <DialogDescription>{t('security.apiKeyRevokeDescription')}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setRevoking(null)}>
              {t('common.cancel')}
            </Button>
            <Button
              className="bg-destructive text-white hover:bg-destructive/90"
              disabled={revoke.isPending}
              onClick={() => revoking && revoke.mutate(revoking.id, { onSuccess: () => setRevoking(null) })}
            >
              {t('security.apiKeyRevoke')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
