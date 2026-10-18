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

// Le liste della libreria pesano MB: anche quando il server risponde 304, il
// browser passa a JS il corpo in cache, che va riletto e confrontato (decine
// di ms, di più su un telefono). Per 30 s dopo l'ultima lettura passare da
// una vista all'altra, o tornare alla scheda, non le richiede di nuovo; le
// invalidazioni (un seed finito, un'esclusione) le richiedono comunque.
export const LIBRARY_STALE_MS = 30_000

// gcTime almeno quanto la cache persistita, ma solo per le query persistite:
// una query ripristinata da IndexedDB non deve essere scartata dopo i 5
// minuti di default. Le altre (schede di dettaglio, ricerche, anteprime dei
// nomi) restano ai 5 minuti, invece di restare in memoria per tutta la sessione.
export function applyPersistedDefaults(queryClient: QueryClient): void {
  for (const view of LIST_VIEWS) {
    queryClient.setQueryDefaults(['library', view], { gcTime: CACHE_MAX_AGE_MS, staleTime: LIBRARY_STALE_MS })
  }
  queryClient.setQueryDefaults(TRACKER_SETTING_KEY, { gcTime: CACHE_MAX_AGE_MS })
  dropIdleTrackerVariants(queryClient)
}

// Il gcTime di default di TanStack: quanto resta in memoria una query che
// nessuno guarda più.
export const IDLE_VARIANT_GC_MS = 5 * 60_000

function isTrackerView(query: Query): boolean {
  const [root, view] = query.queryKey
  return root === 'library' && typeof view === 'string' && TRACKER_VIEWS.has(view)
}

// Una variante per un filtro per tracker non più scelto non si salva, ma col
// gcTime di sette giorni restava in memoria per tutta la sessione: 4-10 MB
// l'una, una in più a ogni cambio di filtro. Non guardata da nessuno, dopo i
// soliti 5 minuti si scarta, come ogni altra query; quella del filtro scelto
// resta, perché è la cache persistita. Il gcTime di una query non si può
// accorciare (TanStack tiene il massimo), quindi lo fa un timer (audit 2026-10-18).
function dropIdleTrackerVariants(queryClient: QueryClient): void {
  const cache = queryClient.getQueryCache()
  // Un timer per query, ripartito a ogni nuovo abbandono: i 5 minuti contano
  // dall'ultima volta che qualcuno l'ha guardata.
  const timers = new Map<string, ReturnType<typeof setTimeout>>()
  const dropLater = (query: Query) => {
    clearTimeout(timers.get(query.queryHash))
    timers.set(
      query.queryHash,
      setTimeout(() => {
        timers.delete(query.queryHash)
        if (cache.get(query.queryHash) !== query || query.getObserversCount() > 0) return
        if (query.queryKey[3] === activeTrackerFilter(queryClient)) return
        cache.remove(query)
      }, IDLE_VARIANT_GC_MS),
    )
  }
  cache.subscribe((event) => {
    // La vista ha lasciato la variante (cambio di filtro o di pagina).
    if (event.type === 'observerRemoved') {
      if (isTrackerView(event.query) && event.query.getObserversCount() === 0) dropLater(event.query)
      return
    }
    // Il filtro è cambiato con la vista chiusa: le varianti già senza
    // osservatori non riceverebbero più nessun evento.
    const [root, key] = event.query.queryKey
    if (event.type === 'updated' && event.action.type === 'success' && root === 'settings' && key === TRACKER_FILTER_SETTING) {
      for (const query of cache.getAll()) if (isTrackerView(query) && query.getObserversCount() === 0) dropLater(query)
    }
  })
}

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
// La cache ripristinata più vecchia di CACHE_MAX_AGE_MS si butta, e la sua
// età è quella dell'ultima scrittura: una libreria che non cambia per una
// settimana, aperta ogni giorno, la perderebbe lo stesso. Una volta al giorno
// si riscrive anche identica, solo per rinfrescarne la data.
export const CACHE_REFRESH_MS = 24 * 60 * 60 * 1000

export function skipUnchanged(persister: Persister, now: () => number = Date.now): Persister {
  let saved: unknown[] | null = null
  let writtenAt = 0
  return {
    persistClient: (client) => {
      const next = snapshot(client)
      if (saved && sameSnapshot(saved, next) && now() - writtenAt < CACHE_REFRESH_MS) return
      saved = next
      writtenAt = now()
      return persister.persistClient(client)
    },
    restoreClient: async () => {
      const client = await persister.restoreClient()
      // Ripristinata, la cache contiene esattamente questi oggetti: il primo
      // evento dopo l'apertura non la riscrive identica.
      saved = client ? snapshot(client) : null
      writtenAt = client?.timestamp ?? 0
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
