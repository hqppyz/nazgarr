import { CheckIcon, SearchIcon, TriangleAlertIcon } from 'lucide-react'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'

import {
  posterUrl,
  useMetadataDetails,
  useMetadataSearch,
  type MetadataCandidate,
  type MetadataDetails,
} from '@/api/hooks/metadata'
import { useSetting } from '@/api/hooks/settings'
import { useConfirmMatch, useReidentify, type UploadJob } from '@/api/hooks/uploads'
import { AuthedPoster } from '@/components/AuthedPoster'
import { ChoiceCards } from '@/components/ChoiceCards'
import { ForcedIdFields } from '@/components/upload/ForcedIdFields'
import { MetadataLinks } from '@/components/upload/MetadataLinks'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ToggleGroupItem, ToggleGroupSingle } from '@/components/ui/toggle-group'
import { t } from '@/lib/i18n'
import { fromForcedIds, missingEpisodes, toForcedIds, type UploadKind } from '@/lib/upload'
import { cn } from '@/lib/utils'

interface Layout {
  kind: UploadKind
  videos: { relative_path: string; size_bytes: number; season: number | null; episodes: number[] }[]
  episodes_by_season: Record<string, number[]>
  seasons: number[]
}

const keyOf = (c: Pick<MetadataCandidate, 'content_type' | 'tmdb_id'>) => `${c.content_type}:${c.tmdb_id}`

function sourceLabel(source: string | undefined) {
  if (!source || source === 'search') return null
  return t(`upload.match.source.${source}`)
}

function CandidateCard({
  candidate,
  selected,
  onSelect,
}: {
  candidate: MetadataCandidate
  selected: boolean
  onSelect: () => void
}) {
  const label = sourceLabel(candidate.source)
  return (
    <button type="button" onClick={onSelect} className="group text-left" aria-pressed={selected}>
      <div
        className={cn(
          'relative aspect-[2/3] overflow-hidden rounded-md border transition',
          selected ? 'ring-2 ring-primary' : 'group-hover:ring-2 group-hover:ring-primary/50',
        )}
      >
        <AuthedPoster
          contentType={candidate.content_type}
          tmdbId={candidate.tmdb_id}
          hasPoster
          url={posterUrl(candidate)}
          className="h-full w-full"
        />
        <div className="absolute inset-x-1.5 top-1.5 flex items-start justify-between gap-1">
          <Badge className="bg-black/70 text-[10px] text-white">
            {candidate.content_type === 'tv' ? t('upload.match.series') : t('upload.match.movie')}
          </Badge>
          {selected && (
            <span className="flex size-5 items-center justify-center rounded-full bg-primary text-primary-foreground">
              <CheckIcon className="size-3.5" />
            </span>
          )}
        </div>
        <div className="absolute inset-x-0 bottom-0 grid gap-0.5 bg-gradient-to-t from-black/90 via-black/60 to-transparent px-2 pt-8 pb-1.5">
          <p className="line-clamp-2 text-xs font-medium text-white">{candidate.title ?? `#${candidate.tmdb_id}`}</p>
          <p className="flex items-center justify-between gap-1 text-[10px] text-white/70">
            <span>{candidate.year ?? '—'}</span>
            {label && <span className="rounded bg-white/15 px-1">{label}</span>}
            {/* Quanto è sicuro (nazgarr/upload_match_score.py): sopra la soglia la cartella osservata lo conferma da sola. */}
            {candidate.confidence != null && (
              <span
                className={cn('ml-auto rounded px-1 tabular-nums', candidate.ambiguous ? 'bg-amber-500/40' : 'bg-white/15')}
                title={candidate.ambiguous ? t('upload.match.ambiguous') : confidenceExplained(candidate)}
              >
                {Math.round(candidate.confidence * 100)}%
              </span>
            )}
          </p>
        </div>
      </div>
    </button>
  )
}

const percent = (value: number | undefined) => `${Math.round((value ?? 0) * 100)}%`

// Da cosa viene la confidence di un candidato (nazgarr/upload_match_score.py).
function confidenceExplained(candidate: MetadataCandidate): string {
  const parts = candidate.confidence_parts
  if (!parts) return t('upload.match.confidence')
  if (parts.basis !== 'name') return t(`upload.match.basis.${parts.basis}`)
  return t('upload.match.basis.name', { title: percent(parts.title), year: percent(parts.year), type: percent(parts.type) })
}

// Quanto è affidabile il candidato scelto e da cosa viene, contro la soglia
// del match automatico (Settings › Releases): per capire a che valore metterla.
function ConfidenceDetail({ candidate }: { candidate: MetadataCandidate }) {
  const { data } = useSetting('upload_auto_match_threshold')
  if (candidate.confidence == null) return null
  const raw = data?.value
  const threshold = raw == null || raw === '' ? 0.9 : Number(raw)
  const off = !(threshold > 0 && threshold <= 1)
  const passes = !off && !candidate.ambiguous && candidate.confidence >= threshold
  return (
    <div className="grid gap-1 border-t pt-3 text-xs">
      <p className="font-medium">
        {t('upload.match.reliability', { confidence: percent(candidate.confidence) })}
        <span className={cn('ml-1.5 font-normal', passes ? 'text-emerald-600 dark:text-emerald-400' : 'text-muted-foreground')}>
          {off
            ? t('upload.match.summaryOff')
            : candidate.ambiguous
              ? t('upload.match.summaryAmbiguous')
              : t(passes ? 'upload.match.summaryAbove' : 'upload.match.summaryBelow', { threshold: percent(threshold) })}
        </span>
      </p>
      <p className="text-muted-foreground">{confidenceExplained(candidate)}</p>
    </div>
  )
}

function CandidateGrid({
  candidates,
  selectedKey,
  onSelect,
}: {
  candidates: MetadataCandidate[]
  selectedKey: string | null
  onSelect: (candidate: MetadataCandidate) => void
}) {
  return (
    <div className="grid grid-cols-3 gap-3 sm:grid-cols-4 xl:grid-cols-5">
      {candidates.map((candidate) => (
        <CandidateCard
          key={keyOf(candidate)}
          candidate={candidate}
          selected={keyOf(candidate) === selectedKey}
          onSelect={() => onSelect(candidate)}
        />
      ))}
    </div>
  )
}

function DetailPanel({ candidate, details, isPending }: {
  candidate: MetadataCandidate
  details: MetadataDetails | undefined
  isPending: boolean
}) {
  const info = details ?? candidate
  return (
    <div className="grid gap-3">
      <div className="flex gap-3">
        <AuthedPoster
          contentType={candidate.content_type}
          tmdbId={candidate.tmdb_id}
          hasPoster
          url={posterUrl(candidate)}
          className="aspect-[2/3] w-20 shrink-0 overflow-hidden rounded"
        />
        <div className="grid min-w-0 content-start gap-1">
          <p className="font-medium leading-tight">
            {info.title} {info.year && <span className="text-muted-foreground">({info.year})</span>}
          </p>
          {info.original_title && info.original_title !== info.title && (
            <p className="text-xs text-muted-foreground italic">{info.original_title}</p>
          )}
          <div className="flex flex-wrap gap-1">
            <Badge variant="outline">
              {candidate.content_type === 'tv' ? t('upload.match.series') : t('upload.match.movie')}
            </Badge>
            {details?.genres.slice(0, 3).map((genre) => (
              <Badge key={genre} variant="secondary">
                {genre}
              </Badge>
            ))}
          </div>
          {details?.runtime && (
            <p className="text-xs text-muted-foreground">{t('upload.match.runtime', { minutes: details.runtime })}</p>
          )}
        </div>
      </div>
      {isPending && !details && <p className="text-xs text-muted-foreground">{t('common.loading')}</p>}
      {info.overview && <p className="line-clamp-6 text-xs leading-relaxed">{info.overview}</p>}
      {details && details.cast.length > 0 && (
        <p className="text-xs text-muted-foreground">
          <span className="font-medium text-foreground">{t('upload.match.cast')}:</span> {details.cast.join(', ')}
        </p>
      )}
      <MetadataLinks
        job={{
          content_type: candidate.content_type,
          tmdb_id: candidate.tmdb_id,
          imdb_id: details?.imdb_id,
          tvdb_id: details?.tvdb_id,
        }}
      />
      <ConfidenceDetail candidate={candidate} />
    </div>
  )
}

function defaultKind(job: UploadJob, contentType: string): UploadKind {
  const detected = (job.kind ?? 'movie') as UploadKind
  if (contentType === 'movie') return 'movie'
  if (detected !== 'movie') return detected
  return job.is_dir ? 'season_pack' : 'episode'
}

function SeasonPicker({
  job,
  layout,
  details,
  kind,
  seasons,
  onSeasonsChange,
  episode,
  onEpisodeChange,
}: {
  job: UploadJob
  layout: Layout | null
  details: MetadataDetails | undefined
  kind: UploadKind
  seasons: number[]
  onSeasonsChange: (seasons: number[]) => void
  episode: number | null
  onEpisodeChange: (episode: number | null) => void
}) {
  const detected = new Set(job.seasons)
  const found = layout?.episodes_by_season ?? {}
  // Le stagioni di TMDB, più quelle trovate nella sorgente che TMDB non
  // conosce (numerazione diversa): si vedono comunque, con l'avviso.
  const tmdbSeasons = details?.seasons ?? []
  const known = new Set(tmdbSeasons.map((s) => s.season_number))
  const rows = [
    ...tmdbSeasons.filter((s) => s.season_number > 0 || detected.has(0)),
    ...[...detected].filter((n) => !known.has(n)).map((n) => ({ season_number: n, name: null, episode_count: 0, air_date: null })),
  ].sort((a, b) => a.season_number - b.season_number)
  const unknownDetected = details ? [...detected].filter((n) => !known.has(n)) : []
  const multiple = kind === 'complete_pack'

  const toggle = (n: number) => {
    if (!multiple) return onSeasonsChange([n])
    onSeasonsChange(seasons.includes(n) ? seasons.filter((s) => s !== n) : [...seasons, n].sort((a, b) => a - b))
  }

  return (
    <div className="grid gap-2">
      <Label>{multiple ? t('upload.match.seasonsLabel') : t('upload.match.seasonLabel')}</Label>
      {detected.size === 0 && (
        <p className="flex items-center gap-1.5 text-xs text-amber-600 dark:text-amber-400">
          <TriangleAlertIcon className="size-3.5" />
          {t('upload.match.noSeasonDetected')}
        </p>
      )}
      {unknownDetected.length > 0 && (
        <p className="flex items-center gap-1.5 text-xs text-amber-600 dark:text-amber-400">
          <TriangleAlertIcon className="size-3.5" />
          {t('upload.match.seasonUnknownToTmdb', { seasons: unknownDetected })}
        </p>
      )}
      <div className="grid max-h-64 gap-1 overflow-auto">
        {rows.map((season) => {
          const n = season.season_number
          const episodes = found[String(n)] ?? []
          const missing = season.episode_count ? missingEpisodes(episodes, season.episode_count) : []
          const active = seasons.includes(n)
          return (
            <button
              key={n}
              type="button"
              role={multiple ? 'checkbox' : 'radio'}
              aria-checked={active}
              onClick={() => toggle(n)}
              className={cn(
                'flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-left text-xs transition',
                active ? 'border-primary bg-primary/10' : 'hover:bg-muted',
              )}
            >
              <span
                className={cn(
                  'flex size-3.5 shrink-0 items-center justify-center border',
                  multiple ? 'rounded-sm' : 'rounded-full',
                  active && 'border-primary bg-primary text-primary-foreground',
                )}
              >
                {active && <CheckIcon className="size-2.5" />}
              </span>
              <span className="font-medium">{t('upload.match.seasonN', { n })}</span>
              {detected.has(n) && <Badge variant="secondary" className="h-4 px-1 text-[10px]">{t('upload.match.detected')}</Badge>}
              <span className="ml-auto text-muted-foreground tabular-nums">
                {season.episode_count
                  ? t('upload.match.episodesFound', { found: episodes.length, expected: season.episode_count })
                  : t('upload.match.episodesFoundNoTotal', { found: episodes.length })}
              </span>
              {episodes.length > 0 && missing.length > 0 && kind !== 'episode' && (
                <span className="text-amber-600 dark:text-amber-400" title={missing.map((e) => `E${e}`).join(' ')}>
                  {t('upload.match.missingCount', { count: missing.length })}
                </span>
              )}
            </button>
          )
        })}
      </div>
      {kind === 'episode' && (
        <div className="grid max-w-40 gap-1.5">
          <Label htmlFor="match-episode">{t('upload.match.episodeLabel')}</Label>
          <Input
            id="match-episode"
            type="number"
            min={0}
            value={episode ?? ''}
            onChange={(e) => onEpisodeChange(e.target.value === '' ? null : Number(e.target.value))}
          />
        </div>
      )}
    </div>
  )
}

export function MatchStep({ job }: { job: UploadJob }) {
  const candidates = job.candidates as unknown as MetadataCandidate[]
  const layout = job.layout as unknown as Layout | null
  const [selected, setSelected] = useState<MetadataCandidate | null>(candidates[0] ?? null)
  const [searchType, setSearchType] = useState<'movie' | 'tv'>((job.content_type as 'movie' | 'tv') ?? 'movie')
  const [searchDraft, setSearchDraft] = useState(job.title ?? '')
  const [searchQuery, setSearchQuery] = useState('')
  const search = useMetadataSearch(searchType, searchQuery, null)
  const details = useMetadataDetails(selected?.content_type ?? null, selected?.tmdb_id ?? null)
  const [kind, setKind] = useState<UploadKind>(() => defaultKind(job, selected?.content_type ?? 'movie'))
  const [seasons, setSeasons] = useState<number[]>(job.seasons)
  const [episode, setEpisode] = useState<number | null>(job.episode ?? null)
  const [ids, setIds] = useState(() => fromForcedIds(job.forced_ids))
  const confirm = useConfirmMatch(job.id)
  const reidentify = useReidentify(job.id)

  const searchResults = useMemo(() => {
    const shown = new Set(candidates.map(keyOf))
    return (search.data ?? []).filter((c) => !shown.has(keyOf(c)))
  }, [search.data, candidates])

  function select(candidate: MetadataCandidate) {
    setSelected(candidate)
    setKind(defaultKind(job, candidate.content_type))
  }

  const isTv = selected?.content_type === 'tv'
  const kindChoices = [
    { value: 'episode' as const, title: t('upload.kind.episode'), description: t('upload.kind.episodeHelp') },
    { value: 'season_pack' as const, title: t('upload.kind.season_pack'), description: t('upload.kind.season_packHelp') },
    { value: 'complete_pack' as const, title: t('upload.kind.complete_pack'), description: t('upload.kind.complete_packHelp') },
  ].filter((choice) => (job.is_dir ? choice.value !== 'episode' || (layout?.videos.length ?? 0) <= 1 : choice.value === 'episode'))

  const invalid =
    selected === null ||
    (isTv && seasons.length === 0) ||
    (isTv && kind !== 'complete_pack' && seasons.length !== 1) ||
    (isTv && kind === 'episode' && episode === null)

  function submit() {
    if (!selected || invalid) return
    confirm.mutate(
      {
        content_type: selected.content_type,
        tmdb_id: selected.tmdb_id,
        kind: isTv ? kind : 'movie',
        seasons: isTv ? seasons : [],
        episode: isTv && kind === 'episode' ? episode : null,
      },
      { onError: (error) => toast.error(t('upload.match.confirmFailed', { message: error.message })) },
    )
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
      <div className="grid content-start gap-4">
        <Card>
          <CardHeader>
            <CardTitle>{t('upload.match.title')}</CardTitle>
            <CardDescription>{t('upload.match.description')}</CardDescription>
          </CardHeader>
          <CardContent>
            {candidates.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t('upload.match.noCandidates')}</p>
            ) : (
              <CandidateGrid candidates={candidates} selectedKey={selected && keyOf(selected)} onSelect={select} />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t('upload.match.searchTitle')}</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4">
            <form
              className="flex flex-wrap gap-2"
              onSubmit={(e) => {
                e.preventDefault()
                setSearchQuery(searchDraft.trim())
              }}
            >
              <ToggleGroupSingle
                value={searchType}
                onValueChange={(value) => setSearchType(value as 'movie' | 'tv')}
                variant="outline"
              >
                <ToggleGroupItem value="movie">{t('upload.match.movie')}</ToggleGroupItem>
                <ToggleGroupItem value="tv">{t('upload.match.series')}</ToggleGroupItem>
              </ToggleGroupSingle>
              <Input
                className="min-w-48 flex-1"
                value={searchDraft}
                placeholder={t('upload.match.searchPlaceholder')}
                onChange={(e) => setSearchDraft(e.target.value)}
              />
              <Button type="submit" variant="outline" disabled={!searchDraft.trim()}>
                <SearchIcon className="size-4" />
                {t('upload.match.search')}
              </Button>
            </form>
            {search.isFetching && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}
            {search.isError && <p className="text-sm text-destructive">{search.error.message}</p>}
            {searchQuery && search.data && searchResults.length === 0 && (
              <p className="text-sm text-muted-foreground">{t('upload.match.noSearchResults')}</p>
            )}
            {searchResults.length > 0 && (
              <CandidateGrid candidates={searchResults} selectedKey={selected && keyOf(selected)} onSelect={select} />
            )}

            <Collapsible>
              <CollapsibleTrigger className="text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground">
                {t('upload.match.forceIds')}
              </CollapsibleTrigger>
              <CollapsibleContent className="grid gap-3 pt-3">
                <ForcedIdFields ids={ids} onChange={setIds} />
                <Button
                  variant="outline"
                  className="w-fit"
                  disabled={reidentify.isPending}
                  onClick={() =>
                    reidentify.mutate(toForcedIds(ids), {
                      onError: (error) => toast.error(error.message),
                    })
                  }
                >
                  {t('upload.match.identifyAgain')}
                </Button>
              </CollapsibleContent>
            </Collapsible>
          </CardContent>
        </Card>
      </div>

      <Card className="h-fit lg:sticky lg:top-4">
        <CardHeader>
          <CardTitle className="text-base">{t('upload.match.selected')}</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4">
          {selected ? (
            <DetailPanel candidate={selected} details={details.data} isPending={details.isPending} />
          ) : (
            <p className="text-sm text-muted-foreground">{t('upload.match.nothingSelected')}</p>
          )}
          {selected && isTv && (
            <>
              <ChoiceCards
                label={t('upload.match.kindLabel')}
                choices={kindChoices}
                value={kind}
                onSelect={(value) => {
                  setKind(value)
                  if (value !== 'complete_pack') setSeasons((prev) => prev.slice(0, 1))
                }}
              />
              <SeasonPicker
                job={job}
                layout={layout}
                details={details.data}
                kind={kind}
                seasons={seasons}
                onSeasonsChange={setSeasons}
                episode={episode}
                onEpisodeChange={setEpisode}
              />
            </>
          )}
          {selected && !isTv && job.kind !== 'movie' && (
            <p className="flex items-center gap-1.5 text-xs text-amber-600 dark:text-amber-400">
              <TriangleAlertIcon className="size-3.5" />
              {t('upload.match.movieButSeriesDetected')}
            </p>
          )}
          <Button disabled={invalid || confirm.isPending} onClick={submit}>
            {t('upload.match.confirm')}
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}
