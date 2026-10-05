import { useSetSetting, useSetting } from '@/api/hooks/settings'
import { SettingField } from '@/components/SettingField'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { t } from '@/lib/i18n'
import { autosaveFeedback } from '@/lib/autosave'
import { ScheduleCard } from '@/pages/config/ScheduleCard'

// Spenta di default (nazgarr/reseed/review.py auto_execute_enabled): decisione
// dell'utente, niente che modifichi file o client parte senza la sua
// approvazione. Accesa solo con una scelta esplicita qui.
const AUTO_EXECUTE_KEY = 'auto_execute_above_threshold'
// Attiva di default (nazgarr/reseed/review.py verify_before_execute_enabled): mai
// salvata = attiva.
const VERIFY_KEY = 'verify_before_execute'
// Spenta di default (nazgarr/reseed/review.py skip_recheck_enabled): l'unica eccezione
// al recheck del client, solo insieme alla verifica completa.
const SKIP_RECHECK_KEY = 'skip_client_recheck_when_verified'
// Accesa di default (nazgarr/library/seeding.py cross_seed_enabled): un file in seed su
// un tracker si cerca anche sugli altri.
const CROSS_SEED_KEY = 'cross_seed_search'

function SettingSwitch({
  settingKey,
  defaultOn,
  label,
  help,
  disabled = false,
  first = false,
}: {
  settingKey: string
  defaultOn: boolean
  label: string
  help: string
  disabled?: boolean
  first?: boolean
}) {
  const { data } = useSetting(settingKey)
  const setSetting = useSetSetting(settingKey)
  const value = (data?.value ?? '').toLowerCase()
  const enabled = value === '' ? defaultOn : value === 'true'
  return (
    <div className={first ? 'flex items-start gap-3' : 'flex items-start gap-3 border-t pt-4'}>
      <Switch
        id={settingKey}
        checked={enabled && !disabled}
        disabled={disabled || setSetting.isPending}
        onCheckedChange={(on) => setSetting.mutate(on ? 'true' : 'false', autosaveFeedback(label))}
        className="mt-0.5"
      />
      <div className="grid gap-1">
        <Label htmlFor={settingKey} className={disabled ? 'text-muted-foreground' : undefined}>
          {label}
        </Label>
        <p className="text-xs text-muted-foreground">{help}</p>
      </div>
    </div>
  )
}

function ExecutionCard() {
  const { data: verify } = useSetting(VERIFY_KEY)
  const verifyOn = (verify?.value ?? 'true').toLowerCase() !== 'false'
  return (
    <Card data-tour="reseeding.execution">
      <CardHeader>
        <CardTitle>{t('integrations.executionTitle')}</CardTitle>
        <CardDescription>{t('integrations.executionDescription')}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <SettingSwitch
          settingKey={VERIFY_KEY}
          defaultOn
          first
          label={t('integrations.verifyLabel')}
          help={t('integrations.verifyHelp')}
        />
        <SettingSwitch
          settingKey={SKIP_RECHECK_KEY}
          defaultOn={false}
          disabled={!verifyOn}
          label={t('integrations.skipRecheckLabel')}
          help={verifyOn ? t('integrations.skipRecheckHelp') : t('integrations.skipRecheckNeedsVerify')}
        />
        <SettingSwitch
          settingKey={AUTO_EXECUTE_KEY}
          defaultOn={false}
          label={t('integrations.autoExecuteLabel')}
          help={t('integrations.autoExecuteHelp')}
        />
      </CardContent>
    </Card>
  )
}

function SearchCard() {
  return (
    <Card data-tour="reseeding.search">
      <CardHeader>
        <CardTitle>{t('reseeding.searchTitle')}</CardTitle>
        <CardDescription>{t('reseeding.searchDescription')}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <SettingSwitch
          settingKey={CROSS_SEED_KEY}
          defaultOn
          first
          label={t('reseeding.crossSeedLabel')}
          help={t('reseeding.crossSeedSettingHelp')}
        />
      </CardContent>
    </Card>
  )
}

export function AutoApproveSection() {
  return (
    <>
      <ScheduleCard />
      <SearchCard />
      <Card data-tour="reseeding.thresholds">
        <CardHeader>
          <CardTitle>{t('integrations.autoApproveThresholdsTitle')}</CardTitle>
          <CardDescription>{t('integrations.autoApproveThresholdsDescription')}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <SettingField
            settingKey="confidence_threshold_auto_media_to_torrent"
            label="media → torrent"
            description="Default: 0.95"
            type="number"
            placeholder="0.95"
          />
          <SettingField
            settingKey="confidence_threshold_auto_torrent_to_client"
            label="torrent → client"
            description="Default: 0.98"
            type="number"
            placeholder="0.98"
          />
        </CardContent>
      </Card>
      <ExecutionCard />
      <Card>
        <CardHeader>
          <CardTitle>{t('integrations.rematchTitle')}</CardTitle>
          <CardDescription>{t('integrations.rematchDescription')}</CardDescription>
        </CardHeader>
        <CardContent>
          <SettingField
            settingKey="rematch_interval_days"
            label={t('integrations.rematchLabel')}
            description={t('integrations.rematchHelp')}
            type="number"
            placeholder="7"
          />
        </CardContent>
      </Card>
    </>
  )
}
