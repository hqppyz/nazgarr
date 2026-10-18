import { createAsyncStoragePersister } from '@tanstack/query-async-storage-persister'
import type { Query, QueryClient } from '@tanstack/react-query'
import type { PersistedClient, Persister } from '@tanstack/react-query-persist-client'
import { del, get, set } from 'idb-keyval'

import { activeInstanceId } from '@/lib/instance'
import { TRACKER_FILTER_SETTING } from '@/lib/trackerFilter'

// Cache delle viste della libreria nel browser (IndexedDB: le liste file
// pesano diversi MB, troppi per localStorage). All'apertura la vista si
// disegna subito con i dati dell'ultima visita, poi TanStack Query li
// rivalida in background: il server risponde 304 in pochi ms se non è
// cambiato nulla (ETag, nazgarr/web/response_cache.py), altrimenti i dati nuovi
// sostituiscono quelli in cache.
export const CACHE_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000

// Da incrementare quando cambia la forma delle risposte persistite: una
// cache vecchia con campi diversi viene scartata invece di rompere la vista.
export const CACHE_BUSTER = 'library-v3' // v3: seed_requirement in Not imported

// Le viste che si salvano: le liste che una pagina disegna appena aperta.
// Non le schede di dettaglio (una per ogni titolo aperto, si accumulerebbero).
const LIST_VIEWS = new Set(['items', 'media-files', 'seed-files', 'duplicates', 'not-imported'])
// Queste dipendono dal filtro per tracker (4° elemento della chiave): si salva
// solo quella del filtro scelto, non ogni variante vista in sette giorni.
const TRACKER_VIEWS = new Set(['items', 'media-files', 'seed-files'])
const TRACKER_SETTING_KEY = ['settings', TRACKER_FILTER_SETTING]

// Le chiavi che restano in memoria quanto la cache persistita: una query
// ripristinata da IndexedDB non deve essere scartata dopo i 5 minuti di
// default (main.tsx, setQueryDefaults).
export const PERSISTED_KEYS: readonly (readonly string[])[] = [
  ...[...LIST_VIEWS].map((view) => ['library', view]),
  TRACKER_SETTING_KEY,
]

// Il filtro per tracker scelto, dalla cache: lo stesso valore di useTrackerFilter.
export function activeTrackerFilter(queryClient: QueryClient): string {
  return queryClient.getQueryData<{ value?: string | null }>(TRACKER_SETTING_KEY)?.value || 'all'
}

// Solo le viste della libreria e il filtro per tracker: tutto il resto (run,
// review, dashboard) deve arrivare sempre fresco dal server. Il filtro si
// salva perché all'apertura serve subito: senza, finché l'impostazione non
// arriva, le viste chiederebbero (e salverebbero) quella di "tutti i tracker".
export function shouldPersistQuery(query: Query, activeTracker = 'all'): boolean {
  if (query.state.status !== 'success') return false
  const [root, view, , tracker] = query.queryKey
  if (root === 'settings') return view === TRACKER_FILTER_SETTING
  if (root !== 'library' || typeof view !== 'string' || !LIST_VIEWS.has(view)) return false
  return !TRACKER_VIEWS.has(view) || tracker === activeTracker
}

// Quello che si scriverebbe, per riferimento: lo structural sharing di
// TanStack tiene lo stesso oggetto `data` quando una richiesta riporta gli
// stessi dati, quindi riferimenti uguali = niente di nuovo da scrivere.
function snapshot(client: PersistedClient): unknown[] {
  return client.clientState.queries.flatMap((query) => [query.queryHash, query.state.data])
}

function sameSnapshot(a: unknown[], b: unknown[]): boolean {
  return a.length === b.length && a.every((value, i) => value === b[i])
}

// Il persister di TanStack salva a ogni evento della cache, di qualunque
// query: ogni poll (dashboard, upload, controlli completi) riscriveva tutte
// le liste della libreria, decine di MB serializzati in JSON ogni pochi
// secondi a scheda aperta. Qui si scrive solo quando una query salvata è
// cambiata davvero (audit 2026-10-18).
export function skipUnchanged(persister: Persister): Persister {
  let saved: unknown[] | null = null
  return {
    persistClient: (client) => {
      const next = snapshot(client)
      if (saved && sameSnapshot(saved, next)) return
      saved = next
      return persister.persistClient(client)
    },
    restoreClient: async () => {
      const client = await persister.restoreClient()
      // Ripristinata, la cache contiene esattamente questi oggetti: il primo
      // evento dopo l'apertura non la riscrive identica.
      saved = client ? snapshot(client) : null
      return client
    },
    removeClient: () => {
      saved = null
      return persister.removeClient()
    },
  }
}

export const queryPersister = skipUnchanged(
  createAsyncStoragePersister({
    storage: { getItem: get, setItem: set, removeItem: del },
    // Una cache per istanza: i dati di due istanze non si mescolano.
    key: `nazgarr-query-cache${activeInstanceId() ? `-i${activeInstanceId()}` : ''}`,
    throttleTime: 2000,
  }),
)

export async function clearPersistedQueries(): Promise<void> {
  await queryPersister.removeClient()
}
