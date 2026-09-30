import {
  UploadIcon,
  ChevronRightIcon,
  CornerDownRightIcon,
  ExternalLinkIcon,
  EyeOffIcon,
  FileIcon,
  FileVideoIcon,
  Loader2Icon,
  RefreshCwIcon,
  SearchIcon,
} from 'lucide-react'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import type { Schemas } from '@/api/client'
import { useExcludeFile, useItemDetail, useSearchNow } from '@/api/hooks/library'
import { useApproveReview, useReconcileNow, useRejectReview } from '@/api/hooks/reviews'
import { AuthedPoster } from '@/components/AuthedPoster'
import { FullCheckButton } from '@/components/FullCheckButton'
import { StateBadge, StatusBadge, StoppedBadge } from '@/components/StateBadge'
import { VerifyStatus } from '@/components/VerifyStatus'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { t } from '@/lib/i18n'
import { formatBytes } from '@/lib/library-filters'
import { STATUS_STYLES } from '@/lib/status-styles'
import { relativeFromNow } from '@/lib/time'
import { newUploadLink } from '@/lib/upload'
import { cn } from '@/lib/utils'

type Detail = Schemas['ItemDetailResponse']
type DetailFile = Schemas['DetailFile']

export interface OpenItem {
  contentType: string
  tmdbId: number
}

function episodeCode(f: DetailFile): string | null {
  if (f.season_number == null || f.episode_number == null) return null
  return `S${String(f.season_number).padStart(2, '0')}E${String(f.episode_number).padStart(2, '0')}`
}

function Section({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <section className="grid gap-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">{title}</h3>
        {action}
      </div>
      {children}
    </section>
  )
}

function ExternalLinks({ detail }: { detail: Detail }) {
  const links = [
    {
      label: 'TMDB',
      href: `https://www.themoviedb.org/${detail.content_type === 'tv' ? 'tv' : 'movie'}/${detail.tmdb_id}`,
    },
    detail.imdb_id ? { label: 'IMDb', href: `https://www.imdb.com/title/${detail.imdb_id}/` } : null,
    detail.arr_url ? { label: detail.arr_kind === 'sonarr' ? 'Sonarr' : 'Radarr', href: detail.arr_url } : null,
  ].filter((l): l is { label: string; href: string } => l !== null)
  return (
    <div className="flex flex-wrap gap-1.5">
      {links.map((l) => (
        <Button key={l.label} size="xs" variant="outline" render={<a href={l.href} target="_blank" rel="noreferrer" />}>
          {l.label}
          <ExternalLinkIcon className="size-3" />
        </Button>
      ))}
    </div>
  )
}

function FileRow({ file, showEpisode, uploadTmdb }: { file: DetailFile; showEpisode: boolean; uploadTmdb: string }) {
  const exclude = useExcludeFile()
  const navigate = useNavigate()
  // Un video orfano (in libreria, non in seed): upload o reseed dal flusso di upload.
  const orphan = file.is_video && !file.excluded && file.state !== 'seeding'
  const code = showEpisode ? episodeCode(file) : null
  return (
    <div className={cn('grid gap-1 rounded-md border p-2.5', file.excluded && 'opacity-60')}>
      <div className="flex items-start gap-2">
        {file.is_video ? (
          <FileVideoIcon className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
        ) : (
          <FileIcon className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
        )}
        <div className="min-w-0 flex-1">
          <p className="font-mono text-xs break-all">
            {code && <span className="mr-1.5 font-sans font-medium">{code}</span>}
            {file.relative_path}
          </p>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            {file.excluded ? (
              // Escluso = fuori da ogni controllo: nessuno stato, solo "excluded".
              <StatusBadge status="excluded">{t('library.excluded')}</StatusBadge>
            ) : (
              <>
                <StateBadge state={file.state} />
                {file.stopped && <StoppedBadge />}
                {file.in_review && <StatusBadge status="review">{t('itemDetail.inReview')}</StatusBadge>}
                {file.duplicates.length > 0 && (
                  <StatusBadge status="duplicate">{t('itemDetail.duplicate')}</StatusBadge>
                )}
              </>
            )}
            <span className="text-xs text-muted-foreground tabular-nums">{formatBytes(file.size_bytes)}</span>
          </div>
        </div>
        {orphan && (
          <Button
            size="xs"
            variant="outline"
            title={t('itemDetail.uploadOrReseedHelp')}
            onClick={() =>
              navigate(newUploadLink({ diskId: file.disk_id, path: file.relative_path, isDir: false }, uploadTmdb))
            }
          >
            <UploadIcon className="size-3.5" />
            {t('itemDetail.uploadOrReseed')}
          </Button>
        )}
        {!file.excluded && (
          <Button
            size="icon-xs"
            variant="ghost"
            title={t('itemDetail.exclude')}
            disabled={exclude.isPending}
            onClick={() =>
              exclude.mutate(file.relative_path)
            }
          >
            <EyeOffIcon className="size-3.5" />
          </Button>
        )}
      </div>
      <div className="grid gap-0.5 pl-5 text-xs text-muted-foreground">
        {file.hardlinks.length === 0 ? (
          <p className="flex items-center gap-1">
            <CornerDownRightIcon className="size-3 shrink-0" />
            {t('itemDetail.noHardlink')}
          </p>
        ) : (
          file.hardlinks.map((link) => (
            <div key={link.relative_path} className="grid gap-0.5">
              <p className="flex items-start gap-1 font-mono break-all">
                <CornerDownRightIcon className="mt-0.5 size-3 shrink-0" />
                {link.relative_path}
              </p>
              {link.torrents.length === 0 ? (
                <p className="pl-4 text-destructive">{t('itemDetail.notInClient')}</p>
              ) : (
                link.torrents.map((torrent) => (
                  <p key={`${torrent.client}-${torrent.name}`} className="pl-4">
                    {[torrent.client, torrent.tracker, torrent.state].filter(Boolean).join(' · ')}
                    <span className="ml-1 opacity-70">({torrent.name})</span>
                  </p>
                ))
              )}
            </div>
          ))
        )}
        {file.duplicates.map((dup) => (
          <p key={dup.relative_path} className="flex items-start gap-1 break-all">
            <span className="shrink-0">{t('itemDetail.alsoAt')}</span>
            <span className="font-mono">{dup.relative_path}</span>
            {dup.same_file && <span className="shrink-0 italic">{t('itemDetail.sameFileHint')}</span>}
          </p>
        ))}
      </div>
    </div>
  )
}

// La cartella comune ai file di una stagione, se ce n'è una sola: da lì si
// carica la stagione intera come season pack.
function seasonFolder(files: DetailFile[]): { diskId: number; path: string } | null {
  const videos = files.filter((f) => f.is_video)
  if (videos.length < 2) return null
  const folders = new Set(videos.map((f) => `${f.disk_id}:${f.relative_path.split('/').slice(0, -1).join('/')}`))
  if (folders.size !== 1) return null
  const [disk, ...rest] = [...folders][0].split(':')
  const path = rest.join(':')
  return path ? { diskId: Number(disk), path } : null
}

function Seasons({ files, uploadTmdb }: { files: DetailFile[]; uploadTmdb: string }) {
  const navigate = useNavigate()
  const seasons = useMemo(() => {
    const bySeason = new Map<number, DetailFile[]>()
    for (const f of files) {
      const key = f.season_number ?? 0
      bySeason.set(key, [...(bySeason.get(key) ?? []), f])
    }
    return [...bySeason.entries()].sort(([a], [b]) => a - b)
  }, [files])
  return (
    <div className="grid gap-2">
      {seasons.map(([season, seasonFiles]) => {
        const videos = seasonFiles.filter((f) => f.is_video && !f.excluded)
        const seeding = videos.filter((f) => f.state === 'seeding').length
        const folder = seeding < videos.length ? seasonFolder(seasonFiles) : null
        return (
          <Collapsible key={season} className="rounded-md border">
            <CollapsibleTrigger className="group flex w-full items-center gap-2 px-3 py-2 text-left text-sm">
              <ChevronRightIcon className="size-4 text-muted-foreground transition-transform group-data-[panel-open]:rotate-90" />
              <span className="font-medium">{t('itemDetail.season', { n: season })}</span>
              <span className="ml-auto text-xs text-muted-foreground tabular-nums">
                {t('itemDetail.seasonSummary', { seeding, total: videos.length })}
              </span>
            </CollapsibleTrigger>
            <CollapsibleContent className="grid gap-2 px-3 pb-3">
              {folder && (
                <Button
                  size="xs"
                  variant="outline"
                  className="w-fit"
                  onClick={() => navigate(newUploadLink({ diskId: folder.diskId, path: folder.path, isDir: true }, uploadTmdb))}
                >
                  <UploadIcon className="size-3.5" />
                  {t('itemDetail.uploadSeason', { n: season })}
                </Button>
              )}
              {seasonFiles.map((f) => (
                <FileRow key={f.media_file_id} file={f} showEpisode uploadTmdb={uploadTmdb} />
              ))}
            </CollapsibleContent>
          </Collapsible>
        )
      })}
    </div>
  )
}

function Reviews({ detail }: { detail: Detail }) {
  const approve = useApproveReview()
  const reject = useRejectReview()
  if (detail.reviews.length === 0) return null
  return (
    <Section title={t('itemDetail.awaitingApproval')}>
      {detail.reviews.map((r) => (
        <div key={r.id} className="grid gap-1.5 rounded-md border p-2.5">
          <p className="font-mono text-xs break-all">{r.candidate_name}</p>
          <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
            <Badge variant="secondary">{r.direction}</Badge>
            <span>{(r.confidence * 100).toFixed(0)}%</span>
            {r.status === 'auto_approved' && <Badge>{t('reseeding.autoApproved')}</Badge>}
            {r.ambiguity_reason && <span>{r.ambiguity_reason}</span>}
          </div>
          <VerifyStatus review={r} />
          <div className="flex gap-2">
            <Button
              size="sm"
              disabled={approve.isPending || r.verify_status === 'verifying'}
              title={r.verify_status === 'verifying' ? t('reseeding.verifyingHint') : undefined}
              onClick={() => approve.mutate(r.id)}
            >
              {r.verify_status === 'verifying' && <Loader2Icon className="size-3.5 animate-spin" />}
              {r.verify_status === 'verifying' ? t('reseeding.verifying') : t('reseeding.approve')}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={reject.isPending}
              onClick={() =>
                reject.mutate(r.id)
              }
            >
              {t('reseeding.reject')}
            </Button>
          </div>
        </div>
      ))}
    </Section>
  )
}

function Matching({ detail }: { detail: Detail }) {
  const search = useSearchNow()
  const [showCandidates, setShowCandidates] = useState(false)
  const orphans = detail.files.filter((f) => f.is_video && !f.excluded && f.state !== 'seeding').length
  return (
    <Section
      title={t('itemDetail.matching')}
      action={
        orphans > 0 && (
          <Button
            size="xs"
            variant="outline"
            disabled={search.isPending}
            onClick={() =>
              search.mutate({
                contentType: detail.content_type,
                tmdbId: detail.tmdb_id,
                label: detail.title ?? undefined,
              })
            }
          >
            {search.isPending ? <Loader2Icon className="size-3 animate-spin" /> : <SearchIcon className="size-3" />}
            {t('itemDetail.searchNow')}
          </Button>
        )
      }
    >
      {detail.searches.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          {orphans > 0 ? t('itemDetail.neverSearched') : t('itemDetail.nothingToSearch')}
        </p>
      ) : (
        detail.searches.map((s) => (
          <p key={s.tracker} className="text-xs text-muted-foreground">
            <span className="font-medium text-foreground">{s.tracker}</span>
            {' · '}
            {t('itemDetail.searched', { when: relativeFromNow(s.last_searched_at) })}
            {s.next_search_at && ` · ${t('itemDetail.nextSearch', { when: relativeFromNow(s.next_search_at) })}`}
          </p>
        ))
      )}
      {detail.candidates.length > 0 && (
        <Collapsible open={showCandidates} onOpenChange={setShowCandidates}>
          <CollapsibleTrigger className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
            <ChevronRightIcon className={cn('size-3.5 transition-transform', showCandidates && 'rotate-90')} />
            {t('itemDetail.candidatesEvaluated', { count: detail.candidates.length })}
          </CollapsibleTrigger>
          <CollapsibleContent className="mt-1.5 grid gap-1">
            {detail.candidates.map((c) => (
              <div key={c.id} className="flex items-start justify-between gap-2 text-xs">
                <span className="min-w-0 font-mono break-all">
                  {c.name}
                  {c.videos > 1 && <span className="ml-1 font-sans text-muted-foreground">({c.videos} videos)</span>}
                </span>
                <span className="grid shrink-0 justify-items-end gap-1 text-right text-muted-foreground tabular-nums">
                  <span>
                    {c.tracker} · {(c.confidence * 100).toFixed(0)}%
                    {c.ambiguity_reason && <span className="block">{c.ambiguity_reason}</span>}
                  </span>
                  <FullCheckButton target={{ candidateId: c.id }} label={c.name} />
                </span>
              </div>
            ))}
          </CollapsibleContent>
        </Collapsible>
      )}
    </Section>
  )
}

function History({ detail }: { detail: Detail }) {
  const reconcile = useReconcileNow()
  if (detail.seed_jobs.length === 0) return null
  const waiting = detail.seed_jobs.some((job) => job.final_status === 'in_progress')
  return (
    <Section
      title={t('itemDetail.history')}
      action={
        waiting && (
          <Button
            size="xs"
            variant="outline"
            disabled={reconcile.isPending}
            title={t('itemDetail.checkNowHint')}
            onClick={() =>
              reconcile.mutate()
            }
          >
            {reconcile.isPending ? <Loader2Icon className="size-3 animate-spin" /> : <RefreshCwIcon className="size-3" />}
            {t('itemDetail.checkNow')}
          </Button>
        )
      }
    >
      {detail.seed_jobs.map((job) => (
        <div key={job.id} className="grid gap-0.5 text-xs">
          <p className="font-mono break-all">{job.candidate_name}</p>
          <p className="text-muted-foreground">
            <StateBadge state={job.display_status} />{' '}
            {job.recheck_status && t('itemDetail.recheck', { status: job.recheck_status })}
            {job.torrent_added_at && ` · ${relativeFromNow(job.torrent_added_at)}`}
          </p>
          {job.error_message && <p className="text-destructive">{job.error_message}</p>}
          {job.display_status !== 'seeding' && (
            <div>
              <FullCheckButton target={{ candidateId: job.candidate_id, seedJobId: job.id }} label={job.candidate_name} />
            </div>
          )}
        </div>
      ))}
    </Section>
  )
}

export function ItemDetailSheet({ item, onClose }: { item: OpenItem | null; onClose: () => void }) {
  const { data: detail, isPending, error } = useItemDetail(item?.contentType ?? null, item?.tmdbId ?? null)
  const counts = useMemo(() => {
    const videos = (detail?.files ?? []).filter((f) => f.is_video && !f.excluded)
    return {
      seeding: videos.filter((f) => f.state === 'seeding').length,
      orphan: videos.filter((f) => f.state !== 'seeding').length,
      videos: videos.length,
    }
  }, [detail])

  return (
    <Sheet open={item != null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full overflow-y-auto data-[side=right]:sm:max-w-2xl">
        {isPending || !detail ? (
          <div className="grid h-full place-items-center text-sm text-muted-foreground">
            {error ? error.message : <Loader2Icon className="size-5 animate-spin" />}
          </div>
        ) : (
          <>
            <SheetHeader className="flex-row gap-4">
              <AuthedPoster
                contentType={detail.content_type}
                tmdbId={detail.tmdb_id}
                hasPoster={detail.has_poster}
                className="aspect-[2/3] w-24 shrink-0 overflow-hidden rounded-md border"
              />
              <div className="grid min-w-0 content-start gap-1.5 pr-8">
                <SheetTitle className="text-lg">
                  {detail.title ?? `#${detail.tmdb_id}`}
                  {detail.year && <span className="ml-1.5 font-normal text-muted-foreground">({detail.year})</span>}
                </SheetTitle>
                <SheetDescription>
                  {[
                    detail.content_type === 'tv' ? t('itemDetail.series') : t('library.movie'),
                    detail.content_type === 'tv' ? t('library.episodesCount', { count: counts.videos }) : null,
                    formatBytes(detail.total_size_bytes),
                    detail.quality,
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                </SheetDescription>
                <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                  {counts.seeding > 0 && (
                    <span className="flex items-center gap-1">
                      <span className={cn('size-2 rounded-full', STATUS_STYLES.seeding.dot)} />
                      {t('library.status.seeding')} {detail.content_type === 'tv' && counts.seeding}
                    </span>
                  )}
                  {counts.orphan > 0 && (
                    <span className="flex items-center gap-1">
                      <span className={cn('size-2 rounded-full', STATUS_STYLES.orphan.dot)} />
                      {t('library.status.orphan')} {detail.content_type === 'tv' && counts.orphan}
                    </span>
                  )}
                </div>
                <ExternalLinks detail={detail} />
              </div>
            </SheetHeader>
            <div className="grid gap-6 px-4 pb-6">
              <Reviews detail={detail} />
              <Section title={t('itemDetail.files')}>
                {detail.content_type === 'tv' ? (
                  <Seasons files={detail.files} uploadTmdb={`${detail.content_type}/${detail.tmdb_id}`} />
                ) : (
                  detail.files.map((f) => (
                    <FileRow
                      key={f.media_file_id}
                      file={f}
                      showEpisode={false}
                      uploadTmdb={`${detail.content_type}/${detail.tmdb_id}`}
                    />
                  ))
                )}
              </Section>
              <Matching detail={detail} />
              <History detail={detail} />
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}
