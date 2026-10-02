import { BugIcon, ExternalLinkIcon, GitPullRequestIcon, RefreshCwIcon, TagIcon } from 'lucide-react'

import { useAppInfo, useUpdateCheck } from '@/api/hooks/system'
import { GitHubMark } from '@/components/GitHubMark'
import { RingLogo } from '@/components/RingLogo'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { RestartTourCard } from '@/onboarding/RestartTourCard'
import { t } from '@/lib/i18n'
import { GITHUB_REPO, GITHUB_URL, PROJECT_LICENSE } from '@/lib/project'
import { cn } from '@/lib/utils'
import { parseApiDate } from '@/lib/time'

function formatUptime(startedAt: string): string {
  const totalMinutes = Math.max(0, Math.floor((Date.now() - parseApiDate(startedAt).getTime()) / 60_000))
  const days = Math.floor(totalMinutes / 1440)
  const hours = Math.floor((totalMinutes % 1440) / 60)
  const minutes = totalMinutes % 60
  const parts: string[] = []
  if (days) parts.push(`${days}d`)
  if (days || hours) parts.push(`${hours}h`)
  parts.push(`${minutes}m`)
  return parts.join(' ')
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between border-b py-2 text-sm last:border-b-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono">{value}</span>
    </div>
  )
}

function ContributeCard() {
  const links = [
    { label: t('application.viewOnGitHub'), href: GITHUB_URL, icon: GitHubMark },
    { label: t('application.reportBug'), href: `${GITHUB_URL}/issues/new`, icon: BugIcon },
    { label: t('application.howToContribute'), href: `${GITHUB_URL}#contributing`, icon: GitPullRequestIcon },
    { label: t('application.releases'), href: `${GITHUB_URL}/releases`, icon: TagIcon },
  ]
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-3">
          <GitHubMark className="size-7 shrink-0" />
          <CardTitle>{t('application.contributeTitle')}</CardTitle>
        </div>
        <CardDescription>{t('application.contributeDescription')}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="grid gap-1 text-sm">
          <InfoRow label={t('application.repository')} value={GITHUB_REPO} />
          <InfoRow label={t('application.license')} value={PROJECT_LICENSE} />
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          {links.map(({ label, href, icon: Icon }) => (
            <Button
              key={href}
              variant="outline"
              className="justify-start"
              render={<a href={href} target="_blank" rel="noreferrer" />}
            >
              <Icon className="size-4" />
              {label}
              <ExternalLinkIcon className="ml-auto size-3.5 text-muted-foreground" />
            </Button>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

export function ApplicationSection() {
  const { data: info } = useAppInfo()
  const { data: updateCheck, isFetching, refetch } = useUpdateCheck(false)

  return (
    <>
      {/* Card principale: logo, cos'è Nazgarr, build in esecuzione e aggiornamenti.
          Stessa intestazione delle card di Integrations: logo e titolo sulla
          stessa riga, azione a destra, descrizione sotto. Il tour subito
          sotto, nella stessa colonna del masonry: un solo blocco. */}
      <div className="grid content-start gap-6">
        <Card>
          <CardHeader>
            <div className="flex w-full items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <RingLogo size={28} />
                <CardTitle>Nazgarr</CardTitle>
              </div>
              <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isFetching}>
                <RefreshCwIcon className={cn('size-4', isFetching && 'animate-spin')} />
                {t('application.checkForUpdates')}
              </Button>
            </div>
            <CardDescription>{t('application.tagline')}</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            {info && (
              <div>
                <InfoRow label={t('application.version')} value={info.version} />
                <InfoRow label={t('application.commit')} value={info.commit ?? '—'} />
                <InfoRow label={t('application.pythonVersion')} value={info.python_version} />
                <InfoRow label={t('application.platform')} value={info.platform} />
                <InfoRow label={t('application.uptime')} value={formatUptime(info.started_at)} />
              </div>
            )}
            {updateCheck && (
              <div className="rounded-md border p-3 text-sm">
                {updateCheck.note ? (
                  <p className="text-muted-foreground">{updateCheck.note}</p>
                ) : updateCheck.update_available ? (
                  <p className="font-medium">
                    {t('application.updateAvailable', { version: updateCheck.latest_version ?? '' })}
                  </p>
                ) : (
                  <p className="text-muted-foreground">{t('application.upToDate')}</p>
                )}
                {updateCheck.channel && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    {updateCheck.channel === 'stable' ? t('application.channelStable') : t('application.channelTest')}
                  </p>
                )}
              </div>
            )}
          </CardContent>
        </Card>
        <RestartTourCard />
      </div>
      <ContributeCard />
    </>
  )
}
