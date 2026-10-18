// Se un torrent non importato si può togliere dal client (Torrent › Non
// importati): lo usano la riga, il menu e la conferma.

import type { Schemas } from '@/api/client'

type Torrent = Schemas['NotImportedItem']

// Quali avvisi impediscono la rimozione lo dice il server (blocking,
// nazgarr/api/torrents.py BLOCKING_WARNINGS): gli altri, come "ultimo
// seeder", si mostrano nella conferma ma non la bloccano.
export function canRemove(torrent: Torrent): boolean {
  return (
    torrent.seed_requirement?.status === 'met' &&
    !(torrent.removal_warnings ?? []).some((warning) => warning.blocking)
  )
}
