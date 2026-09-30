import { CheckIcon, CopyIcon, KeyRoundIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { useApiKeys, useCreateApiKey, useRevokeApiKey } from '@/api/hooks/apiKeys'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ToggleGroupItem, ToggleGroupSingle } from '@/components/ui/toggle-group'
import { t } from '@/lib/i18n'
import { relativeFromNow } from '@/lib/time'
import { cn } from '@/lib/utils'

// API key per servizi e script (header X-Api-Key): lettura = solo GET,
// scrittura = tutto tranne gestire le chiavi. La chiave si vede una volta.
export function ApiKeysSection() {
  const { data: keys } = useApiKeys()
  const create = useCreateApiKey()
  const revoke = useRevokeApiKey()
  const [name, setName] = useState('')
  const [level, setLevel] = useState<'read' | 'write'>('read')
  const [created, setCreated] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [revoking, setRevoking] = useState<{ id: number; name: string } | null>(null)

  function submit() {
    create.mutate(
      { name, level },
      {
        onSuccess: (key) => {
          setCreated(key.key)
          setCopied(false)
          setName('')
        },
        onError: (error) => toast.error(t('common.saveFailed', { message: error.message })),
      },
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('security.apiKeysTitle')}</CardTitle>
        <CardDescription>{t('security.apiKeysDescription')}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="grid gap-2 sm:grid-cols-[1fr_auto_auto] sm:items-end">
          <div className="grid gap-1.5">
            <Label htmlFor="api-key-name">{t('security.apiKeyName')}</Label>
            <Input id="api-key-name" value={name} placeholder="grafana" onChange={(e) => setName(e.target.value)} />
          </div>
          <ToggleGroupSingle value={level} onValueChange={(v) => v && setLevel(v as 'read' | 'write')} variant="outline" size="sm">
            <ToggleGroupItem value="read">{t('security.apiKeyRead')}</ToggleGroupItem>
            <ToggleGroupItem value="write">{t('security.apiKeyWrite')}</ToggleGroupItem>
          </ToggleGroupSingle>
          <Button disabled={!name.trim() || create.isPending} onClick={submit}>
            {t('security.apiKeyCreate')}
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">{t(`security.apiKeyLevelHelp.${level}`)}</p>

        {(keys ?? []).length > 0 && (
          <ul className="grid gap-2">
            {keys!.map((key) => (
              <li
                key={key.id}
                className={cn('flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border p-2.5 text-sm', key.revoked_at && 'opacity-60')}
              >
                <KeyRoundIcon className="size-4 text-muted-foreground" />
                <span className="font-medium">{key.name}</span>
                <span className="font-mono text-xs text-muted-foreground">{key.prefix}…</span>
                <Badge variant="outline">{t(key.level === 'write' ? 'security.apiKeyWrite' : 'security.apiKeyRead')}</Badge>
                <span className="text-xs text-muted-foreground">
                  {key.revoked_at
                    ? t('security.apiKeyRevokedAt', { when: relativeFromNow(key.revoked_at) })
                    : key.last_used_at
                      ? t('security.apiKeyUsed', { when: relativeFromNow(key.last_used_at) })
                      : t('security.apiKeyNeverUsed')}
                </span>
                {!key.revoked_at && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="ml-auto text-destructive hover:text-destructive"
                    onClick={() => setRevoking({ id: key.id, name: key.name })}
                  >
                    {t('security.apiKeyRevoke')}
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </CardContent>

      {/* La chiave appena creata: l'unica volta che si vede. */}
      <Dialog open={created !== null} onOpenChange={(open) => !open && setCreated(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('security.apiKeyCreatedTitle')}</DialogTitle>
            <DialogDescription>{t('security.apiKeyCreatedDescription')}</DialogDescription>
          </DialogHeader>
          <div className="flex items-center gap-2">
            <code className="min-w-0 flex-1 rounded-md bg-muted px-3 py-2 font-mono text-xs break-all">{created}</code>
            <Button
              variant="outline"
              size="icon-sm"
              title={t('security.apiKeyCopy')}
              onClick={() =>
                created &&
                navigator.clipboard.writeText(created).then(
                  () => setCopied(true),
                  () => toast.error(t('security.apiKeyCopyFailed')),
                )
              }
            >
              {copied ? <CheckIcon className="size-4" /> : <CopyIcon className="size-4" />}
            </Button>
          </div>
          <DialogFooter>
            <Button onClick={() => setCreated(null)}>{t('security.apiKeyDone')}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

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
    </Card>
  )
}
