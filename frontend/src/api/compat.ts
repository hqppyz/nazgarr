import type { components } from './schema'

import { instancePath, isRemote } from '@/lib/instance'

type Schemas = components['schemas']

// Un'istanza remota di una versione già rilasciata (le 0.9.x) non ha gli
// endpoint a pagine che due pagine chiamano appena aperte: lo storico degli
// upload (/api/uploads/history) e la coda delle review (/api/reviews/queue).
// Attraverso il proxy rispondono 404 o 405, o 422 (lo storico finisce su
// /api/uploads/{upload_id}), e la compatibilità dice "ok" per la stessa minor:
// la pagina degli upload diventava l'anello caduto, la coda delle review
// "Nessuna review in attesa" (audit 2026-10-18). Qui la stessa risposta,
// costruita dall'endpoint di prima, che quelle istanze hanno: tutto in una
// pagina sola. Solo verso un'altra istanza: questa ha sempre gli endpoint
// della sua interfaccia, e un suo errore resta un errore.

const MISSING = new Set([404, 405, 422])
// Come nazgarr/upload/jobs.py FINAL_STATES: quelli che lo storico elenca.
const FINAL_STATES = new Set(['done', 'partial', 'failed', 'cancelled'])

type Build = (old: unknown, url: URL) => unknown

interface Fallback {
  path: string // l'endpoint di prima, con lo stesso proxy
  build: Build
}

const FALLBACKS: Record<string, Fallback> = {
  '/api/uploads/history': {
    // Senza scope l'elenco di tutti gli upload, dal più recente.
    path: '/api/uploads',
    build: (old, url): Schemas['UploadHistoryResponse'] => {
      const finished = (old as Schemas['UploadJobSummary'][])
        .filter((job) => FINAL_STATES.has(job.status))
        .sort((a, b) => b.id - a.id)
      const before = Number(url.searchParams.get('before_id'))
      const jobs = Number.isInteger(before) && before > 0 ? finished.filter((job) => job.id < before) : finished
      return { jobs, total: finished.length, next_before_id: null }
    },
  },
  '/api/reviews/queue': {
    // Tutta la coda, nello stesso ordine.
    path: '/api/reviews',
    build: (old, url): Schemas['ReviewQueuePage'] => {
      const items = old as Schemas['ReviewResponse'][]
      const offset = Math.max(0, Number(url.searchParams.get('offset')) || 0)
      return { items: items.slice(offset), total: items.length, offset, next_offset: null }
    },
  },
}

/**
 * La risposta di un endpoint che l'istanza remota non ha, rifatta con quello
 * di prima; null quando non serve (questa istanza, un altro endpoint, o la
 * risposta non dice che manca). La risposta di prima con un errore passa
 * così com'è.
 */
export async function olderRemoteFallback(
  schemaPath: string,
  request: Request,
  response: Response,
  fetch: (input: Request) => Promise<Response>,
): Promise<Response | null> {
  const fallback = FALLBACKS[schemaPath]
  if (!fallback || request.method !== 'GET' || !MISSING.has(response.status) || !isRemote()) return null
  const url = new URL(request.url)
  const target = new URL(instancePath(fallback.path), url)
  const old = await fetch(
    new Request(target, {
      method: 'GET',
      headers: request.headers,
      signal: request.signal,
      credentials: request.credentials,
    }),
  )
  if (!old.ok) return old
  const body = fallback.build(await old.json(), url)
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}
