import { ExternalLinkIcon } from 'lucide-react'


interface Service {
  key: string
  label: string
  logo: string
  url: string
}

// Gli id di un contenuto: di un job di upload o di un candidato al match.
export interface MetadataIds {
  content_type: string | null
  tmdb_id: number | null
  imdb_id?: string | null
  tvdb_id?: number | null
  mal_id?: number | null
}

function servicesOf(job: MetadataIds): Service[] {
  const tv = job.content_type === 'tv'
  const out: Service[] = []
  if (job.tmdb_id) {
    out.push({ key: 'tmdb', label: 'TMDB', logo: '/logos/tmdb.svg', url: `https://www.themoviedb.org/${tv ? 'tv' : 'movie'}/${job.tmdb_id}` })
  }
  if (job.imdb_id) out.push({ key: 'imdb', label: 'IMDb', logo: '/logos/imdb.svg', url: `https://www.imdb.com/title/${job.imdb_id}/` })
  if (job.tvdb_id) {
    out.push({ key: 'tvdb', label: 'TVDB', logo: '/logos/tvdb.svg', url: `https://thetvdb.com/dereferrer/${tv ? 'series' : 'movie'}/${job.tvdb_id}` })
  }
  if (job.mal_id) out.push({ key: 'mal', label: 'MyAnimeList', logo: '/logos/mal.svg', url: `https://myanimelist.net/anime/${job.mal_id}` })
  return out
}

// I link ai servizi di metadati come pulsanti con il logo del servizio.
export function MetadataLinks({ job }: { job: MetadataIds }) {
  const services = servicesOf(job)
  if (services.length === 0) return null
  return (
    <div className="flex flex-wrap gap-2">
      {services.map((service) => (
        <a
          key={service.key}
          href={service.url}
          target="_blank"
          rel="noreferrer"
          title={service.label}
          className="inline-flex h-8 items-center gap-2 rounded-md border bg-background px-2.5 text-xs font-medium hover:bg-muted"
        >
          <img src={service.logo} alt="" className="h-4 w-auto max-w-10 object-contain" />
          <span>{service.label}</span>
          <ExternalLinkIcon className="size-3 text-muted-foreground" />
        </a>
      ))}
    </div>
  )
}
