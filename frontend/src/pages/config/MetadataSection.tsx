import { useState } from 'react'
import { toast } from 'sonner'

import { useSetSetting, useSetting } from '@/api/hooks/settings'
import { ConfirmButton } from '@/components/ConfirmButton'
import { ServiceLogo } from '@/components/ServiceLogo'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { t } from '@/lib/i18n'

// La chiave di un servizio esterno si scrive e basta: l'API non la rilegge
// (dice solo is_set), come i segreti di tracker e client (audit 2026-10-18).
// Salva resta spento finché non si scrive qualcosa: un campo lasciato vuoto
// non cancella la chiave, per toglierla c'è Rimuovi (con conferma).
function ApiKeyField({ settingKey, service, description }: { settingKey: string; service: string; description: string }) {
  const { data, isPending } = useSetting(settingKey)
  const setSetting = useSetSetting(settingKey)
  const [draft, setDraft] = useState('')
  const isSet = data?.is_set ?? false
  const label = t('metadata.apiKey')

  function save(value: string, done: string) {
    setSetting.mutate(value, {
      onSuccess: () => {
        toast.success(done)
        setDraft('')
      },
      onError: (error) => toast.error(t('common.saveFailed', { message: error.message })),
    })
  }

  return (
    <div className="grid gap-1.5">
      <Label htmlFor={settingKey}>{label}</Label>
      <p className="text-xs text-muted-foreground">{description}</p>
      <div className="flex items-center gap-2">
        <Input
          id={settingKey}
          type="password"
          autoComplete="off"
          value={draft}
          placeholder={isPending ? t('common.loading') : isSet ? t('metadata.keySaved') : undefined}
          onChange={(e) => setDraft(e.target.value)}
        />
        <Button
          variant="outline"
          disabled={setSetting.isPending || !draft.trim()}
          onClick={() => save(draft.trim(), t('common.itemSaved', { item: label }))}
        >
          {t('common.save')}
        </Button>
        {isSet && (
          <ConfirmButton
            trigger={<Button variant="ghost" disabled={setSetting.isPending}>{t('metadata.keyRemove')}</Button>}
            title={t('metadata.keyRemoveTitle', { service })}
            confirmLabel={t('metadata.keyRemove')}
            pending={setSetting.isPending}
            onConfirm={() => save('', t('metadata.keyRemoved', { service }))}
          />
        )}
      </div>
    </div>
  )
}

export function MetadataSection() {
  // Per il tour: TVDB impostato, si va avanti da soli dopo il salvataggio.
  const { data: tvdb } = useSetting('tvdb_api_key')
  return (
    <>
      <Card data-tour="metadata.tmdb">
        <CardHeader className="flex flex-row gap-3">
          <ServiceLogo src="/logos/tmdb.svg" alt="TMDB" />
          <div>
            <CardTitle>{t('metadata.tmdbTitle')}</CardTitle>
            <CardDescription>{t('metadata.tmdbDescription')}</CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <ApiKeyField
            settingKey="tmdb_api_key"
            service={t('metadata.tmdbTitle')}
            description={t('metadata.tmdbApiKeyDescription')}
          />
        </CardContent>
      </Card>

      <Card data-tour="metadata.tvdb" data-tour-filled={tvdb?.is_set ? 'true' : undefined}>
        <CardHeader className="flex flex-row gap-3">
          <ServiceLogo src="/logos/tvdb.svg" alt="TVDB" />
          <div>
            <CardTitle>{t('metadata.tvdbTitle')}</CardTitle>
            <CardDescription>{t('metadata.tvdbDescription')}</CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <ApiKeyField
            settingKey="tvdb_api_key"
            service={t('metadata.tvdbTitle')}
            description={t('metadata.tvdbApiKeyDescription')}
          />
        </CardContent>
      </Card>
    </>
  )
}
