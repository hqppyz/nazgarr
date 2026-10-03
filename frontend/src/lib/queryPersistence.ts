import { createAsyncStoragePersister } from '@tanstack/query-async-storage-persister'
import type { Query } from '@tanstack/react-query'
import { del, get, set } from 'idb-keyval'

import { activeInstanceId } from '@/lib/instance'

// Cache delle viste della libreria nel browser (IndexedDB: le liste file
// pesano diversi MB, troppi per localStorage). All'apertura la vista si
// disegna subito con i dati dell'ultima visita, poi TanStack Query li
// rivalida in background: il server risponde 304 in pochi ms se non è
// cambiato nulla (ETag, nazgarr/response_cache.py), altrimenti i dati nuovi
// sostituiscono quelli in cache.
export const CACHE_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000

// Da incrementare quando cambia la forma delle risposte persistite: una
// cache vecchia con campi diversi viene scartata invece di rompere la vista.
export const CACHE_BUSTER = 'library-v3' // v3: seed_requirement in Not imported

export const queryPersister = createAsyncStoragePersister({
  storage: { getItem: get, setItem: set, removeItem: del },
  // Una cache per istanza: i dati di due istanze non si mescolano.
  key: `nazgarr-query-cache${activeInstanceId() ? `-i${activeInstanceId()}` : ''}`,
  throttleTime: 2000,
})

// Solo le viste della libreria: tutto il resto (run, review, dashboard) deve
// arrivare sempre fresco dal server.
export function shouldPersistQuery(query: Query): boolean {
  return query.queryKey[0] === 'library' && query.state.status === 'success'
}

export async function clearPersistedQueries(): Promise<void> {
  await queryPersister.removeClient()
}
